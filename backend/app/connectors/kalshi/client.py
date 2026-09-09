"""Public REST attempt; authentication failures stay isolated in connector status."""

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings
from app.connectors.base import VenueConnector
from app.schemas.domain import Level, MarketSnapshot, now


def normalize_orderbook(
    raw: dict[str, Any], ticker: str, title: str, resolution_key: str = ""
) -> list[MarketSnapshot]:
    # Current fixed-point schema is dollar strings. Legacy integer schema is cents.
    if "orderbook_fp" in raw:
        book = raw["orderbook_fp"]
        yes, no, divisor = book["yes_dollars"] or [], book["no_dollars"] or [], Decimal(1)
    elif "orderbook" in raw:
        book = raw["orderbook"]
        yes, no, divisor = book["yes"] or [], book["no"] or [], Decimal(100)
    else:
        raise ValueError("Unrecognized Kalshi order-book schema")
    stamp = now()
    result = []
    for outcome, bids, opposite in (("YES", yes, no), ("NO", no, yes)):
        result.append(
            MarketSnapshot(
                venue="kalshi",
                market_id=ticker,
                title=title,
                outcome=outcome,
                timestamp=stamp,
                received_at=stamp,
                timestamp_source="receipt",
                fee_verified=False,
                resolution_key=resolution_key or f"kalshi:{ticker}",
                bids=tuple(
                    Level(price=Decimal(str(price)) / divisor, size=size) for price, size in bids
                ),
                asks=tuple(
                    Level(price=1 - Decimal(str(price)) / divisor, size=size)
                    for price, size in opposite
                ),
            )
        )
    return result


class KalshiConnector(VenueConnector):
    def __init__(self, settings: Settings):
        self.settings = settings

    async def stream(self) -> AsyncIterator[list[MarketSnapshot]]:
        async with httpx.AsyncClient(
            base_url="https://external-api.kalshi.com/trade-api/v2", timeout=10
        ) as client:
            titles: dict[str, str] = {}
            while True:
                batch = []
                for ticker in self.settings.kalshi_tickers:
                    path = f"/markets/{quote(ticker, safe='')}"
                    if ticker not in titles:
                        response = await client.get(path)
                        response.raise_for_status()
                        titles[ticker] = response.json()["market"]["title"]
                    response = await client.get(f"{path}/orderbook")
                    response.raise_for_status()
                    batch.extend(
                        normalize_orderbook(
                            response.json(),
                            ticker,
                            titles[ticker],
                            self.settings.kalshi_resolution_keys.get(ticker, ""),
                        )
                    )
                yield batch
                await asyncio.sleep(self.settings.poll_interval)
