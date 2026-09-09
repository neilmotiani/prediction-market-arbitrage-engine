from decimal import Decimal
from typing import Literal

from app.schemas.domain import ZERO, Fill, Level, MarketSnapshot


class OrderBook:
    """Immutable normalized book; buy consumes asks and sell consumes bids."""

    def __init__(self, snapshot: MarketSnapshot):
        self.snapshot = snapshot
        self.asks = self._aggregate(snapshot.asks, reverse=False)
        self.bids = self._aggregate(snapshot.bids, reverse=True)

    @staticmethod
    def _aggregate(levels: tuple[Level, ...], reverse: bool) -> list[Level]:
        sizes: dict[Decimal, Decimal] = {}
        for level in levels:
            sizes[level.price] = sizes.get(level.price, ZERO) + level.size
        return [Level(price=p, size=sizes[p]) for p in sorted(sizes, reverse=reverse)]

    def best_bid(self) -> Decimal | None:
        return self.bids[0].price if self.bids else None

    def best_ask(self) -> Decimal | None:
        return self.asks[0].price if self.asks else None

    def mid_price(self) -> Decimal | None:
        bid, ask = self.best_bid(), self.best_ask()
        return (bid + ask) / 2 if bid is not None and ask is not None else None

    def spread(self) -> Decimal | None:
        bid, ask = self.best_bid(), self.best_ask()
        return ask - bid if bid is not None and ask is not None else None

    def available_depth(self, side: Literal["buy", "sell"], max_price: Decimal) -> Decimal:
        """For sell, max_price acts as a minimum acceptable price (limit floor)."""
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        return sum(
            (
                x.size
                for x in (self.asks if side == "buy" else self.bids)
                if (x.price <= max_price if side == "buy" else x.price >= max_price)
            ),
            ZERO,
        )

    def estimate_fill(self, side: Literal["buy", "sell"], quantity: Decimal) -> Fill:
        if not quantity.is_finite() or quantity <= 0:
            raise ValueError("quantity must be positive and finite")
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        levels = self.asks if side == "buy" else self.bids
        remaining, notional = quantity, ZERO
        used: list[Level] = []
        for level in levels:
            take = min(remaining, level.size)
            used.append(Level(price=level.price, size=take))
            notional += take * level.price
            remaining -= take
            if remaining == 0:
                break
        filled = quantity - remaining
        average = notional / filled if filled else None
        slip = abs(average - levels[0].price) if average is not None else ZERO
        return Fill(
            requested_size=quantity,
            filled_size=filled,
            average_price=average,
            notional=notional,
            slippage=slip,
            levels=used,
        )
