"""Read-only public CLOB books; WebSocket triggers authoritative REST refreshes."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime
from time import monotonic
from typing import Any

import httpx
from websockets.asyncio.client import connect

from app.config import Settings
from app.connectors.base import VenueConnector
from app.connectors.polymarket.discovery import discover
from app.schemas.domain import Level, MarketSnapshot, now


def normalize_book(raw: dict[str, Any], pair: dict[str, Any], outcome: str) -> MarketSnapshot:
    if raw.get("market") != pair["market_id"]:
        raise ValueError("CLOB condition ID differs from the configured binary market")
    if str(raw.get("asset_id")) != pair[outcome.lower() + "_token"]:
        raise ValueError("CLOB token identity mismatch")
    stamp = datetime.fromtimestamp(int(raw["timestamp"]) / 1000, UTC)
    return MarketSnapshot(
        venue="polymarket",
        market_id=pair["market_id"],
        title=pair["title"],
        outcome=outcome,
        timestamp=stamp,
        received_at=now(),
        timestamp_source="venue",
        bids=tuple(Level.model_validate(x) for x in raw["bids"]),
        asks=tuple(Level.model_validate(x) for x in raw["asks"]),
        resolution_key=pair.get("resolution_key", f"polymarket:{pair['market_id']}"),
        fee_verified=pair.get("fee_schedule") is not None,
        fee_schedule=pair.get("fee_schedule"),
        minimum_order_size=pair.get("minimum_order_size", 1),
        volume=pair.get("volume", 0),
    )


class PolymarketConnector(VenueConnector):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.pairs = settings.polymarket_token_pairs
        for pair in settings.polymarket_token_pairs:
            if not all(pair.get(k) for k in ("market_id", "title", "yes_token", "no_token")):
                raise ValueError(
                    "Each Polymarket pair requires market_id, title, yes_token, no_token"
                )
            if pair["yes_token"] == pair["no_token"]:
                raise ValueError("YES and NO tokens must be distinct")

    async def fetch(self, client: httpx.AsyncClient) -> list[MarketSnapshot]:
        async def one(pair: dict[str, Any], outcome: str) -> MarketSnapshot:
            response = await client.get(
                "https://clob.polymarket.com/book",
                params={"token_id": pair[outcome.lower() + "_token"]},
            )
            response.raise_for_status()
            return normalize_book(response.json(), pair, outcome)

        failures: list[Exception] = []

        async def pair_books(pair: dict[str, Any]) -> list[MarketSnapshot]:
            try:
                return list(await asyncio.gather(*(one(pair, o) for o in ("YES", "NO"))))
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                failures.append(exc)
                logging.getLogger(__name__).warning(
                    "book_pair_skipped", extra={"market": pair["market_id"]}
                )
                return []

        batches = await asyncio.gather(*(pair_books(p) for p in self.pairs))
        result = [s for batch in batches for s in batch]
        if not result and failures:
            raise failures[0]
        return result

    async def stream(self) -> AsyncIterator[list[MarketSnapshot]]:
        async with httpx.AsyncClient(timeout=10, limits=httpx.Limits(max_connections=8)) as client:
            if self.settings.live_auto_discover and not self.settings.polymarket_token_pairs:
                # Periodic REST gives authoritative full books and refreshes the universe
                # without relying on uninterrupted WebSocket delivery.
                refreshed = -float("inf")
                while True:
                    if monotonic() - refreshed >= self.settings.live_discovery_interval:
                        self.pairs = await discover(client, self.settings.live_market_limit)
                        refreshed = monotonic()
                    yield await self.fetch(client)
                    await asyncio.sleep(self.settings.poll_interval)
            yield await self.fetch(client)
            if not self.settings.polymarket_websocket:
                while True:
                    await asyncio.sleep(self.settings.poll_interval)
                    yield await self.fetch(client)
            tokens = [
                p[k]
                for p in self.settings.polymarket_token_pairs
                for k in ("yes_token", "no_token")
            ]
            async with connect(
                "wss://ws-subscriptions-clob.polymarket.com/ws/market",
                open_timeout=10,
                max_size=4 * 1024 * 1024,
                max_queue=16,
            ) as ws:
                await ws.send(json.dumps({"assets_ids": tokens, "type": "market"}))

                async def heartbeat() -> None:
                    while True:
                        await asyncio.sleep(10)
                        await ws.send("PING")

                ping = asyncio.create_task(heartbeat())
                last_fetch = monotonic()
                try:
                    while True:
                        try:
                            message = await asyncio.wait_for(
                                ws.recv(), timeout=self.settings.poll_interval
                            )
                            if message == "PONG":
                                continue
                            events = json.loads(message)
                            if not isinstance(events, list):
                                events = [events]
                            if not any(
                                e.get("event_type") in ("book", "price_change") for e in events
                            ):
                                continue
                        except TimeoutError:
                            pass
                        if monotonic() - last_fetch >= self.settings.poll_interval:
                            # Full refresh avoids unsafe reconstruction from missed or unordered deltas.
                            yield await self.fetch(client)
                            last_fetch = monotonic()
                finally:
                    ping.cancel()
                    with suppress(asyncio.CancelledError):
                        await ping
