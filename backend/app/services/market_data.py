import asyncio
import json
import logging
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

    async def start(self) -> None:
        await self.db.initialize()
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
            if self.settings.polymarket_token_pairs:
                from app.connectors.polymarket.client import PolymarketConnector

                connectors.append(PolymarketConnector(self.settings))
            if self.settings.kalshi_tickers:
                from app.connectors.kalshi.client import KalshiConnector

                connectors.append(KalshiConnector(self.settings))
        for connector in connectors:
            name = type(connector).__name__
            self.connections[name] = {"state": "connecting", "last_update": None}
            self.tasks.append(asyncio.create_task(self.consume(connector), name=name))

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
                    self.connections[name] = {"state": "connected", "last_update": self.last_update}
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
                }
                logger.exception("connector_error", extra={"connector": name})
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def ingest(self, batch: list[MarketSnapshot]) -> None:
        if not batch:
            raise ValueError("Empty market-data batch")
        async with self.lock:
            stamp = now()
            updated = {**self.books, **{s.book_key: s for s in batch}}
            start = perf_counter()
            ops = self.engine.scan(
                list(updated.values()), self.paper.exposure, self.paper.free_capital
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
                            delete(table).where(table.timestamp < stamp - timedelta(days=1))
                        )
                await session.commit()
            self.books, self.opportunities = updated, ops
            self.cycles += 1
            self.updates += len(batch)
            self.checks += len(ops)
            self.found += sum(o.gross_edge > 0 for o in ops)
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
                    "data": [o.model_dump(mode="json") for o in ops],
                    "metrics": metrics,
                }
            )

    def publish(self, event: dict[str, Any]) -> None:
        for queue in tuple(self.subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    def metrics(self) -> dict[str, Any]:
        elapsed = max(perf_counter() - self.started, 0.001)
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
            "uptime_seconds": round(elapsed, 1),
            "markets_monitored": len({s.key for s in self.books.values()}),
            "opportunities_detected": sum(o.gross_edge > 0 for o in self.opportunities),
            "executable_opportunities": sum(o.status == "executable" for o in self.opportunities),
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
