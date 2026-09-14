import asyncio
import json
import logging
from collections import Counter
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select

from app.config import Settings
from app.connectors.base import VenueConnector
from app.connectors.mock import MockConnector
from app.database.session import Database
from app.models.entities import (
    MappingRecord,
    Market,
    MetricRecord,
    OpportunityRecord,
    SnapshotRecord,
)
from app.schemas.domain import ContractMapping, MarketSnapshot, Opportunity, now
from app.services.arbitrage import ArbitrageEngine
from app.services.contract_matching import ContractMatcher
from app.services.diagnostics import scan_diagnostics
from app.services.paper_trading import PaperExecutionProvider

logger = logging.getLogger(__name__)


class ResearchRuntime:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        connector_factory: Callable[[], list[VenueConnector]] | None = None,
    ):
        self.settings, self.db = settings, db
        self.matcher = ContractMatcher(settings.match_threshold, [])
        self.engine = ArbitrageEngine(settings, self.matcher)
        self.paper = PaperExecutionProvider(db, self.engine)
        self.books: dict[str, MarketSnapshot] = {}
        self.opportunities: list[Opportunity] = []
        self.lock = asyncio.Lock()
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.tasks: list[asyncio.Task] = []
        self.started = perf_counter()
        self.updates = self.checks = self.found = self.rejected = self.errors = self.cycles = 0
        self.last_update: str | None = None
        self.detection_ms = 0.0
        self.data_latency_ms = 0.0
        self.connector_factory = connector_factory
        self.connections: dict[str, dict[str, Any]] = {}
        self.auto_paper_fills = 0
        self.auto_paper_skips = 0
        self.rejection_counts: Counter[str] = Counter()
        self.positive_net_checks = 0
        self.out_of_order_books = 0

    async def start(self) -> None:
        await self.db.initialize()
        async with self.db.sessions() as session:
            marker = await session.get(MetricRecord, "dataset:mode")
            if marker is None:
                # Legacy databases were mock runs; do not reuse their capital in live mode.
                existing = await session.scalar(select(Market.id).limit(1))
                if existing and self.settings.mode == "live":
                    raise ValueError("Live mode requires a separate empty database")
                session.add(MetricRecord(id="dataset:mode", payload={"mode": self.settings.mode}))
                await session.commit()
            elif marker.payload["mode"] != self.settings.mode:
                raise ValueError("Database mode mismatch; use a separate database for live data")
        path = Path(self.settings.mapping_file)
        if await asyncio.to_thread(path.exists):
            self.matcher.mappings = [
                ContractMapping.model_validate(m)
                for m in json.loads(await asyncio.to_thread(path.read_text))
            ]
        async with self.db.sessions() as session:
            for record in (await session.scalars(select(MappingRecord))).all():
                mapping = ContractMapping.model_validate(record.payload)
                self.matcher.mappings = [
                    m
                    for m in self.matcher.mappings
                    if {m.left_key, m.right_key} != {mapping.left_key, mapping.right_key}
                ]
                self.matcher.mappings.append(mapping)
        await self.paper.restore()
        if self.connector_factory:
            connectors = self.connector_factory()
        elif self.settings.mode == "mock":
            connectors = [MockConnector(self.settings.poll_interval)]
        else:
            connectors = []
            if self.settings.polymarket_token_pairs or self.settings.live_auto_discover:
                from app.connectors.polymarket.client import PolymarketConnector

                connectors.append(PolymarketConnector(self.settings))
            if self.settings.kalshi_tickers:
                from app.connectors.kalshi.client import KalshiConnector

                connectors.append(KalshiConnector(self.settings))
        for connector in connectors:
            name = type(connector).__name__
            self.connections[name] = {"state": "connecting", "last_update": None}
            self.tasks.append(asyncio.create_task(self.consume(connector), name=name))

        if self.settings.mode == "live":
            self.tasks.append(asyncio.create_task(self.settlement_loop(), name="paper-settlement"))

    async def settlement_loop(self) -> None:
        import httpx

        from app.services.settlement import fetch_resolution

        async with httpx.AsyncClient(timeout=10) as client:
            while True:
                try:
                    keys = {
                        key
                        for t in self.paper.trades
                        if t["status"] == "open"
                        for key in t["market_keys"]
                    }
                    evidence = {}
                    for key in keys:
                        result = await fetch_resolution(client, key)
                        if result is not None:
                            evidence[key] = result
                    async with self.lock:
                        for trade in list(self.paper.trades):
                            if (
                                trade["status"] == "open"
                                and set(trade["market_keys"]) <= evidence.keys()
                            ):
                                await self.paper.settle_from_venue(
                                    trade["id"], {k: evidence[k] for k in trade["market_keys"]}
                                )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.errors += 1
                    logger.exception("settlement_poll_error")
                await asyncio.sleep(60)

    async def stop(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.db.close()

    async def consume(self, connector: VenueConnector) -> None:
        name = type(connector).__name__
        backoff = 1
        while True:
            try:
                async for batch in connector.stream():
                    await self.ingest(batch)
                    self.connections[name] = {
                        "state": "connected",
                        "last_update": self.last_update,
                        "diagnostics": getattr(connector, "diagnostics", {}),
                    }
                    backoff = 1
                raise RuntimeError("Market stream ended")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.errors += 1
                self.connections[name] = {
                    "state": "error",
                    "error": type(exc).__name__,
                    "last_update": self.connections[name].get("last_update"),
                    "diagnostics": getattr(connector, "diagnostics", {}),
                }
                logger.exception("connector_error", extra={"connector": name})
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def ingest(self, batch: list[MarketSnapshot]) -> None:
        if not batch:
            raise ValueError("Empty market-data batch")
        async with self.lock:
            stamp = now()
            accepted = []
            for snapshot in batch:
                previous = self.books.get(snapshot.book_key)
                if previous is not None and snapshot.timestamp < previous.timestamp:
                    self.out_of_order_books += 1
                else:
                    accepted.append(snapshot)
            batch = accepted
            if not batch:
                return
            updated = {
                k: s
                for k, s in self.books.items()
                if (stamp - s.received_at).total_seconds()
                < self.settings.live_discovery_interval * 2
            }
            updated.update({s.book_key: s for s in batch})
            affected_keys = {s.key for s in batch}
            start = perf_counter()
            ops = self.engine.scan(
                list(updated.values()),
                self.paper.exposure,
                self.paper.free_capital,
                changed_keys=affected_keys,
            )
            detection = (perf_counter() - start) * 1000
            async with self.db.sessions() as session:
                for s in batch:
                    await session.merge(
                        Market(
                            id=s.key,
                            payload={
                                "id": s.key,
                                "venue": s.venue,
                                "market_id": s.market_id,
                                "title": s.title,
                                "resolution_key": s.resolution_key,
                            },
                        )
                    )
                    session.add(
                        SnapshotRecord(
                            id=str(uuid4()),
                            market_key=s.key,
                            timestamp=s.timestamp,
                            payload=s.model_dump(mode="json"),
                        )
                    )
                session.add_all(
                    OpportunityRecord(id=o.id, payload=o.model_dump(mode="json")) for o in ops
                )
                # Bounded research retention: raw books/opportunities/metrics expire after 24h.
                if self.cycles % 100 == 0:
                    for table in (SnapshotRecord, OpportunityRecord, MetricRecord):
                        await session.execute(
                            delete(table).where(
                                table.timestamp < stamp - timedelta(days=1),
                                table.id != "dataset:mode",
                            )
                        )
                await session.commit()
            retained = [
                o
                for o in self.opportunities
                if not affected_keys.intersection(o.market_keys)
                and all(s.book_key in updated for s in o.snapshots)
            ]
            self.books, self.opportunities = updated, retained + ops
            if self.settings.auto_paper_trade:
                for op in sorted(ops, key=lambda o: o.expected_profit or 0, reverse=True):
                    if op.status == "executable":
                        try:
                            await self.paper.execute_order(op, self.books)
                            self.auto_paper_fills += 1
                        except ValueError:
                            self.auto_paper_skips += 1
            self.cycles += 1
            self.updates += len(batch)
            self.checks += len(ops)
            self.found += sum(o.gross_edge > 0 for o in ops)
            self.positive_net_checks += sum(o.net_edge is not None and o.net_edge > 0 for o in ops)
            for op in ops:
                self.rejection_counts.update(filter(None, (op.rejection_reason or "").split("; ")))
            self.rejected += sum(o.status != "executable" for o in ops)
            self.last_update = stamp.isoformat()
            self.detection_ms = detection
            self.data_latency_ms = max(
                0, max((stamp - s.timestamp).total_seconds() * 1000 for s in batch)
            )
            metrics = self.metrics()
            async with self.db.sessions() as session:
                session.add(MetricRecord(id=str(uuid4()), payload=metrics))
                await session.commit()
            logger.info(
                "market_batch",
                extra={"snapshots": len(batch), "checks": len(ops), "detection_ms": detection},
            )
            self.publish(
                {
                    "type": "opportunities",
                    "data": [o.model_dump(mode="json") for o in self.current_opportunities()],
                    "metrics": metrics,
                }
            )

    def publish(self, event: dict[str, Any]) -> None:
        for queue in tuple(self.subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    def current_opportunities(self) -> list[Opportunity]:
        """Revalidate on reads so a stopped feed cannot leave stale executable labels."""
        result = []
        for original in self.opportunities:
            yes, no = original.snapshots
            op = self.engine.evaluate(
                yes, no, exposure=self.paper.exposure, free_capital=self.paper.free_capital
            )
            op.id, op.timestamp = original.id, original.timestamp
            if op.status == "executable" and any(
                self.paper.fingerprint(s) in self.paper.consumed for s in (yes, no)
            ):
                op.status = "theoretical"
                op.rejection_reason = "paper_book_already_consumed"
                op.execution_score = 0
            result.append(op)
        return result

    def metrics(self) -> dict[str, Any]:
        elapsed = max(perf_counter() - self.started, 0.001)
        current = self.current_opportunities()
        connections = {}
        for name, conn in self.connections.items():
            state = dict(conn)
            if state.get("last_update"):
                from datetime import datetime

                if (
                    now() - datetime.fromisoformat(state["last_update"])
                ).total_seconds() > self.settings.max_data_age_seconds:
                    state["state"] = "stale"
            connections[name] = state
        return {
            "mode": self.settings.mode,
            "execution_provider": "paper",
            "auto_paper_trade": self.settings.auto_paper_trade,
            "auto_paper_fills": self.auto_paper_fills,
            "auto_paper_skips": self.auto_paper_skips,
            "fee_verified_books": sum(s.fee_verified for s in self.books.values()),
            "books_monitored": len(self.books),
            "venues_monitored": sorted({s.venue for s in self.books.values()}),
            "sizing_policy": self.settings.sizing_policy,
            "scan_diagnostics": scan_diagnostics(current),
            "rejection_reasons_total": dict(self.rejection_counts.most_common()),
            "positive_net_checks_total": self.positive_net_checks,
            "out_of_order_books": self.out_of_order_books,
            "uptime_seconds": round(elapsed, 1),
            "markets_monitored": len({s.key for s in self.books.values()}),
            "opportunities_detected": sum(o.gross_edge > 0 for o in self.opportunities),
            "executable_opportunities": sum(o.status == "executable" for o in current),
            "snapshots_processed": self.updates,
            "checks_total": self.checks,
            "market_updates_per_second": round(self.updates / elapsed, 2),
            "opportunities_checked_per_second": round(self.checks / elapsed, 2),
            "opportunities_found_total": self.found,
            "rejected_opportunities": self.rejected,
            "data_latency_ms": round(self.data_latency_ms, 2),
            "detection_latency_ms": round(self.detection_ms, 3),
            "api_errors": self.errors,
            "last_update": self.last_update,
            "connections": connections,
            "simulated_pnl": str(self.paper.realized_pnl),
            "free_capital": str(self.paper.free_capital),
            "expected_open_pnl": str(
                sum(float(t["expected_pnl"]) for t in self.paper.trades if t["status"] == "open")
            ),
        }
