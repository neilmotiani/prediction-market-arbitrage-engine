from decimal import ROUND_FLOOR, Decimal

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
