from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from app.config import Settings
from app.models.orderbook import OrderBook
from app.services.execution_model import ExecutionModel


class PositionSizer:
    def __init__(self, settings: Settings, execution: ExecutionModel):
        self.settings, self.execution = settings, execution

    def size(
        self,
        books: list[OrderBook],
        requested: Decimal,
        exposure: dict[str, Decimal],
        free_capital: Decimal,
    ) -> Decimal:
        # Charge the entire pair to each market: conservative for cross-venue exposure.
        budget = min(
            self.settings.max_capital_per_opportunity,
            free_capital,
            *(
                self.settings.max_capital_per_market - exposure.get(b.snapshot.key, Decimal(0))
                for b in books
            ),
        )
        if budget <= 0:
            return Decimal(0)
        # Cost is monotone in quantity including fee rounding. Never divide by top quote only.
        low, high = 0, int(requested.to_integral_value(rounding=ROUND_FLOOR))
        while low < high:
            mid = (low + high + 1) // 2
            cost = sum(self.execution.estimate(b, Decimal(mid)).total_cost for b in books)
            if cost <= budget:
                low = mid
            else:
                high = mid - 1
        return Decimal(low)

    def profitable_size(
        self,
        books: list[OrderBook],
        requested: Decimal,
        exposure: dict[str, Decimal],
        free_capital: Decimal,
    ) -> Decimal | None:
        """Maximize modeled dollar profit over affordable, fully paired integer sizes.

        Searching only for the largest affordable order can walk past profitable
        depth. Enumerate the bounded quantity range so fee rounding and fixed
        costs cannot invalidate an assumed monotone net-edge predicate.
        None means no feasible size; the caller retains the requested-size
        rejection analysis rather than concealing why the pair failed.
        """
        upper = int(self.size(books, requested, exposure, free_capital))
        if upper == 0:
            return None
        capacity = min(self.execution.estimate(b, Decimal(upper)).fill.filled_size for b in books)
        upper = min(upper, int(capacity.to_integral_value(rounding=ROUND_FLOOR)))
        lower = int(
            max(b.snapshot.minimum_order_size for b in books).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
        if min(b.snapshot.liquidity for b in books) < self.settings.min_liquidity:
            return None
        best_size, best_profit = None, Decimal(0)
        for amount in range(lower, upper + 1):
            quantity = Decimal(amount)
            estimates = [self.execution.estimate(b, quantity) for b in books]
            if any(e.fill.filled_size != quantity for e in estimates):
                continue
            profit = quantity - sum(e.total_cost for e in estimates)
            slippage = sum(e.fill.slippage for e in estimates)
            if (
                profit / quantity >= self.settings.min_net_edge
                and slippage <= self.settings.max_slippage
                and profit > best_profit
            ):
                best_size, best_profit = quantity, profit
        return best_size
