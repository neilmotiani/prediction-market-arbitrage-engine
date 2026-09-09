import asyncio
import math
from collections.abc import AsyncIterator
from decimal import Decimal

from app.connectors.base import VenueConnector
from app.schemas.domain import Level, MarketSnapshot, now

SCENARIOS = [
    ("macro-rate", "Fed rate below 4% on December 31, 2026?", "0.51", "0.51", 120),
    ("btc-fees", "Bitcoin above $120,000 on December 31, 2026?", "0.495", "0.503", 100),
    ("eth-edge", "Ethereum above $5,000 on December 31, 2026?", "0.45", "0.50", 90),
    ("growth-thin", "US real GDP growth above 2% in 2026?", "0.44", "0.49", 2),
    ("inflation", "US CPI below 3% for December 2026?", "0.43", "0.59", 150),
]


def demo_batch(tick: int = 0) -> list[MarketSnapshot]:
    """Seeded deterministic oscillation plus five auditable scenario families."""
    result: list[MarketSnapshot] = []
    stamp = now()
    for idx, (key, title, yes, no, size) in enumerate(SCENARIOS):
        wave = Decimal(str(round(math.sin(tick / 3 + idx) * 0.003, 4))) if tick else Decimal(0)
        # Executable windows close periodically, producing visible state transitions.
        premium = Decimal("0.05") if key == "eth-edge" and tick % 16 >= 10 else Decimal(0)
        for outcome, base in (("YES", Decimal(yes) + wave), ("NO", Decimal(no) - wave + premium)):
            asks = tuple(
                Level(price=base + Decimal("0.006") * j, size=size * (j + 1)) for j in range(4)
            )
            bids = tuple(
                Level(price=base - Decimal("0.012") - Decimal("0.007") * j, size=size * (j + 1))
                for j in range(4)
            )
            result.append(
                MarketSnapshot(
                    venue="polymarket",
                    market_id=key,
                    title=title,
                    outcome=outcome,
                    timestamp=stamp,
                    received_at=stamp,
                    bids=bids,
                    asks=asks,
                    volume=Decimal(25000 + idx * 17500),
                    resolution_key=f"demo:{key}",
                )
            )
    for outcome, price in (("YES", "0.50"), ("NO", "0.52")):
        base = Decimal(price)
        result.append(
            MarketSnapshot(
                venue="kalshi",
                market_id="inflation-k",
                title="US CPI below 3% for December 2026?",
                outcome=outcome,
                timestamp=stamp,
                received_at=stamp,
                resolution_key="demo:inflation",
                asks=tuple(
                    Level(price=base + Decimal("0.005") * j, size=150 * (j + 1)) for j in range(4)
                ),
                bids=tuple(
                    Level(price=base - Decimal("0.01") - Decimal("0.005") * j, size=200)
                    for j in range(4)
                ),
                volume=Decimal(90000),
            )
        )
    return result


class MockConnector(VenueConnector):
    def __init__(self, interval: float = 3):
        self.interval = interval

    async def stream(self) -> AsyncIterator[list[MarketSnapshot]]:
        tick = 0
        while True:
            yield demo_batch(tick)
            tick += 1
            await asyncio.sleep(self.interval)
