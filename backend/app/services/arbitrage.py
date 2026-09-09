from decimal import Decimal

from app.config import Settings
from app.models.orderbook import OrderBook
from app.schemas.domain import ONE, ZERO, MarketSnapshot, Opportunity, now
from app.services.contract_matching import ContractMatcher
from app.services.execution_model import ExecutionModel
from app.services.sizing import PositionSizer


class ArbitrageEngine:
    def __init__(self, settings: Settings, matcher: ContractMatcher):
        self.settings, self.matcher = settings, matcher
        self.execution = ExecutionModel(settings)
        self.sizer = PositionSizer(settings, self.execution)

    def evaluate(
        self,
        yes: MarketSnapshot,
        no: MarketSnapshot,
        requested: Decimal | None = None,
        exposure: dict[str, Decimal] | None = None,
        free_capital: Decimal | None = None,
    ) -> Opportunity:
        q = requested if requested is not None else Decimal(self.settings.requested_size)
        if not q.is_finite() or q <= 0:
            raise ValueError("requested size must be positive and finite")
        books = [OrderBook(yes), OrderBook(no)]
        cross = yes.key != no.key
        op = Opportunity(
            market=yes.title,
            market_keys=list(dict.fromkeys([yes.key, no.key])),
            venue=" / ".join(dict.fromkeys([yes.venue, no.venue])),
            strategy_type="cross_venue" if cross else "complement",
            yes_price=yes.best_ask,
            no_price=no.best_ask,
            requested_size=q,
            snapshots=[yes, no],
        )
        reasons: list[str] = []
        if yes.outcome != "YES" or no.outcome != "NO":
            reasons.append("invalid_complementary_outcomes")
        if cross and (yes.venue == no.venue or not self.matcher.validated(yes, no)):
            reasons.append("unvalidated_contract_mapping")
        ages = [(now() - b.timestamp).total_seconds() for b in (yes, no)]
        if any(a > self.settings.max_data_age_seconds or a < -1 for a in ages):
            reasons.append("stale_or_future_market_data")
        if abs((yes.timestamp - no.timestamp).total_seconds()) > self.settings.max_leg_skew_seconds:
            reasons.append("asynchronous_legs")
        if not all(b.fee_verified for b in (yes, no)):
            reasons.append("unverified_live_fee_schedule")
        if self.settings.mode == "live":
            if any(b.timestamp_source == "synthetic" for b in (yes, no)):
                reasons.append("synthetic_data_in_live_mode")
            if any(b.fee_schedule is None for b in (yes, no)):
                reasons.append("missing_live_fee_metadata")
            elif any(
                not -1
                <= (now() - b.fee_schedule.verified_at).total_seconds()
                <= self.settings.live_discovery_interval * 2
                for b in (yes, no)
            ):
                reasons.append("stale_live_fee_metadata")
        if any(b.spread() is not None and b.spread() < 0 for b in books):
            reasons.append("crossed_order_book")
        if yes.best_ask is None or no.best_ask is None:
            op.rejection_reason = "; ".join(reasons + ["missing_asks"])
            return op
        op.gross_edge = ONE - yes.best_ask - no.best_ask
        if op.gross_edge <= ZERO:
            reasons.append("no_theoretical_arbitrage")
        size = self.sizer.size(
            books,
            q,
            exposure or {},
            self.settings.paper_capital if free_capital is None else free_capital,
        )
        if size <= 0:
            op.rejection_reason = "; ".join(reasons + ["capital_limit"])
            op.status = "theoretical" if op.gross_edge > 0 else "rejected"
            return op
        if any(size < b.minimum_order_size for b in (yes, no)):
            reasons.append("minimum_order_size")
        estimates = [self.execution.estimate(b, size) for b in books]
        op.estimates = estimates
        op.available_size = min(e.fill.filled_size for e in estimates)
        if any(e.fill.filled_size < size for e in estimates):
            reasons.append("insufficient_depth")
            # Never turn unequal partial fills into a claimed paired profit.
        else:
            op.estimated_fees = sum((e.fees for e in estimates), ZERO) / size
            op.estimated_slippage = sum((e.fill.slippage for e in estimates), ZERO)
            op.execution_costs = (
                sum((e.network_cost + e.latency_reserve for e in estimates), ZERO) / size
            )
            op.net_edge = ONE - sum((e.total_cost for e in estimates), ZERO) / size
            op.expected_profit = size * op.net_edge
            if op.net_edge < self.settings.min_net_edge:
                reasons.append("net_edge_below_threshold")
            if op.estimated_slippage > self.settings.max_slippage:
                reasons.append("slippage_limit")
        if min(yes.liquidity, no.liquidity) < self.settings.min_liquidity:
            reasons.append("minimum_liquidity")
        op.rejection_reason = "; ".join(reasons) or None
        op.status = (
            ("theoretical" if op.gross_edge > 0 else "rejected") if reasons else "executable"
        )
        # Readiness heuristic, not probability of profit or successful settlement.
        op.execution_score = (
            round(min(1, max(0, 1 - max(ages) / self.settings.max_data_age_seconds)), 3)
            if not reasons
            else 0
        )
        return op

    def scan(
        self,
        snapshots: list[MarketSnapshot],
        exposure: dict[str, Decimal] | None = None,
        free_capital: Decimal | None = None,
    ) -> list[Opportunity]:
        yeses = [s for s in snapshots if s.outcome == "YES"]
        nos = [s for s in snapshots if s.outcome == "NO"]
        pairs = [
            (y, n)
            for y in yeses
            for n in nos
            if y.key == n.key or (y.venue != n.venue and self.matcher.candidate(y, n))
        ]
        return [self.evaluate(y, n, exposure=exposure, free_capital=free_capital) for y, n in pairs]
