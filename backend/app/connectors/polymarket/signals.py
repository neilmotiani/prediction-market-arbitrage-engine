"""Coalesce public market events into bounded, authoritative REST refresh work."""

import asyncio
import json
import logging
from collections.abc import Iterable
from typing import Any

from websockets.asyncio.client import connect

logger = logging.getLogger(__name__)


class MarketSignals:
    def __init__(self, pairs: Iterable[dict[str, Any]], diagnostics: dict[str, Any]):
        self.tokens = {p[k]: p["market_id"] for p in pairs for k in ("yes_token", "no_token")}
        self.pending: set[str] = set()
        self.ready = asyncio.Event()
        self.diagnostics = diagnostics

    def accept(self, message: str | bytes) -> None:
        if message == "PONG":
            return
        payload = json.loads(message)
        for event in payload if isinstance(payload, list) else [payload]:
            if not isinstance(event, dict):
                continue
            kind = event.get("event_type")
            if kind not in ("book", "price_change", "best_bid_ask", "market_resolved"):
                continue
            changes = event.get("price_changes", []) if kind == "price_change" else [event]
            tokens = (
                event.get("assets_ids", [])
                if kind == "market_resolved"
                else [c.get("asset_id") for c in changes]
            )
            for token in tokens:
                market = self.tokens.get(token)
                if market is not None and market == event.get("market"):
                    self.pending.add(market)
            self.diagnostics["ws_events"] = self.diagnostics.get("ws_events", 0) + 1
        if self.pending:
            self.ready.set()

    def take(self) -> set[str]:
        result, self.pending = self.pending, set()
        self.ready.clear()
        return result

    async def run(self) -> None:
        backoff = 1
        while True:
            try:
                self.diagnostics["transport"] = "websocket_connecting_rest_active"
                async with connect(
                    "wss://ws-subscriptions-clob.polymarket.com/ws/market",
                    open_timeout=10,
                    max_size=4 * 1024 * 1024,
                    max_queue=16,
                ) as ws:
                    await ws.send(json.dumps({"assets_ids": list(self.tokens), "type": "market"}))
                    self.diagnostics["transport"] = "websocket_triggered_rest"
                    backoff = 1
                    async with asyncio.TaskGroup() as group:

                        async def heartbeat() -> None:
                            while True:
                                await asyncio.sleep(10)
                                await ws.send("PING")

                        group.create_task(heartbeat())
                        while True:
                            self.accept(await ws.recv())
            except asyncio.CancelledError:
                raise
            except Exception:
                self.diagnostics["transport"] = "rest_fallback"
                self.diagnostics["ws_reconnects"] = self.diagnostics.get("ws_reconnects", 0) + 1
                logger.warning("market_websocket_reconnect")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
