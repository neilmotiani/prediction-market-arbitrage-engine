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
from app.connectors.polymarket.signals import MarketSignals
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
        self.diagnostics: dict[str, Any] = {
            "transport": "starting",
            "ws_events": 0,
            "book_errors": 0,
        }
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

    async def fetch_batch(
        self,
        client: httpx.AsyncClient,
        pairs: list[dict[str, Any]],
    ) -> list[MarketSnapshot]:
        """Fetch paired tokens together; never combine half of a failed pair."""
        semaphore = asyncio.Semaphore(2)

        async def chunk(group: list[dict[str, Any]]) -> list[MarketSnapshot]:
            async with semaphore:
                try:
                    response = await client.post(
                        "https://clob.polymarket.com/books",
                        json=[{"token_id": p[k]} for p in group for k in ("yes_token", "no_token")],
                    )
                    response.raise_for_status()
                    indexed = {}
                    for raw in response.json():
                        token = str(raw["asset_id"])
                        if token in indexed:
                            raise ValueError("Duplicate book in batch response")
                        indexed[token] = raw
                    result = []
                    for pair in group:
                        try:
                            legs = [
                                normalize_book(indexed[pair[o.lower() + "_token"]], pair, o)
                                for o in ("YES", "NO")
                            ]
                            result.extend(legs)
                        except (KeyError, ValueError, TypeError):
                            self.diagnostics["book_errors"] += 1
                    return result
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    self.diagnostics["book_errors"] += len(group)
                    logging.getLogger(__name__).warning("book_batch_failed")
                    return []

        chunks = await asyncio.gather(*(chunk(pairs[i : i + 25]) for i in range(0, len(pairs), 25)))
        result = [s for batch in chunks for s in batch]
        if pairs and not result:
            raise ValueError("No complete book pairs returned")
        return result

    async def discovered_stream(
        self, client: httpx.AsyncClient
    ) -> AsyncIterator[list[MarketSnapshot]]:
        refreshed = full_refresh = last_fetch = -float("inf")
        signals: MarketSignals | None = None
        signal_task: asyncio.Task | None = None
        try:
            while True:
                if monotonic() - refreshed >= self.settings.live_discovery_interval:
                    self.pairs = await discover(
                        client,
                        self.settings.live_market_limit,
                        pages=self.settings.live_discovery_pages,
                        per_event=self.settings.live_event_market_limit,
                        diagnostics=self.diagnostics,
                    )
                    if signal_task:
                        signal_task.cancel()
                        await asyncio.gather(signal_task, return_exceptions=True)
                    signals = MarketSignals(self.pairs, self.diagnostics)
                    if self.settings.polymarket_websocket and self.pairs:
                        signal_task = asyncio.create_task(signals.run())
                    else:
                        self.diagnostics["transport"] = "rest_polling"
                    refreshed, full_refresh = monotonic(), -float("inf")
                assert signals is not None
                remaining = self.settings.poll_interval - (monotonic() - full_refresh)
                if remaining > 0 and not signals.pending:
                    try:
                        await asyncio.wait_for(signals.ready.wait(), timeout=remaining)
                    except TimeoutError:
                        pass
                await asyncio.sleep(
                    max(0, self.settings.live_refresh_interval - (monotonic() - last_fetch))
                )
                dirty = signals.take()
                full = monotonic() - full_refresh >= self.settings.poll_interval
                pairs = self.pairs if full else [p for p in self.pairs if p["market_id"] in dirty]
                if not pairs:
                    raise ValueError("No eligible discovered markets")
                batch = await self.fetch_batch(client, pairs)
                # A transient quote combination is evidence to recheck, not a fill.
                positive = {
                    y.market_id
                    for y, n in zip(batch[::2], batch[1::2], strict=True)
                    if y.best_ask is not None
                    and n.best_ask is not None
                    and y.best_ask + n.best_ask < 1
                }
                if positive:
                    self.diagnostics["gross_rechecks"] = self.diagnostics.get(
                        "gross_rechecks", 0
                    ) + len(positive)
                    confirmation = await self.fetch_batch(
                        client, [p for p in pairs if p["market_id"] in positive]
                    )
                    # Remove any pair missing from confirmation; stale first reads cannot execute.
                    batch = [s for s in batch if s.market_id not in positive] + confirmation
                last_fetch = monotonic()
                if full:
                    full_refresh = last_fetch
                self.diagnostics["book_refreshes"] = self.diagnostics.get("book_refreshes", 0) + 1
                yield batch
        finally:
            if signal_task:
                signal_task.cancel()
                await asyncio.gather(signal_task, return_exceptions=True)

    async def stream(self) -> AsyncIterator[list[MarketSnapshot]]:
        async with httpx.AsyncClient(timeout=10, limits=httpx.Limits(max_connections=8)) as client:
            if self.settings.live_auto_discover and not self.settings.polymarket_token_pairs:
                async for batch in self.discovered_stream(client):
                    yield batch
                return
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
