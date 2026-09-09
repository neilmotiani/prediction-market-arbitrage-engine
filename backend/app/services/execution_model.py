from decimal import ROUND_CEILING, Decimal

from app.config import Settings
from app.models.orderbook import OrderBook
from app.schemas.domain import ZERO, ExecutionEstimate, Fill


class ExecutionModel:
    """Explicit research assumptions; live fee schedules must be verified separately."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def fees(self, venue: str, fill: Fill) -> Decimal:
        if venue == "kalshi":
            raw = sum(
                (
                    self.settings.kalshi_fee_coefficient * x.size * x.price * (1 - x.price)
                    for x in fill.levels
                ),
                ZERO,
            )
            return raw.quantize(Decimal("0.01"), rounding=ROUND_CEILING)
        return fill.notional * self.settings.fee_bps / 10000

    def estimate(self, book: OrderBook, quantity: Decimal) -> ExecutionEstimate:
        fill = book.estimate_fill("buy", quantity)
        fees = self.fees(book.snapshot.venue, fill)
        network = self.settings.network_cost if book.snapshot.venue == "polymarket" else ZERO
        reserve = fill.filled_size * self.settings.latency_buffer_bps / 10000
        return ExecutionEstimate(
            fill=fill,
            fees=fees,
            network_cost=network,
            latency_reserve=reserve,
            total_cost=fill.notional + fees + network + reserve,
        )
