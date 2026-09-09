from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.database.session import Database
from app.models.entities import TradeRecord
from app.models.orderbook import OrderBook
from app.schemas.domain import ZERO, MarketSnapshot, Opportunity, now
from app.services.arbitrage import ArbitrageEngine


class ExecutionProvider(ABC):
    @abstractmethod
    async def execute_order(
        self, opportunity: Opportunity, snapshots: dict[str, MarketSnapshot]
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_position(self, market_key: str) -> Decimal:
        raise NotImplementedError


class PaperExecutionProvider(ExecutionProvider):
    """Atomic paired fills in simulation only. Caller holds the runtime mutation lock."""

    def __init__(self, db: Database, engine: ArbitrageEngine):
        self.db, self.engine = db, engine
        self.trades: list[dict[str, Any]] = []
        self.consumed: set[str] = set()

    async def restore(self) -> None:
        async with self.db.sessions() as session:
            records = (
                await session.scalars(select(TradeRecord).order_by(TradeRecord.timestamp))
            ).all()
        self.trades = [r.payload for r in records]
        self.consumed = {f for t in self.trades for f in t["book_fingerprints"]}

    @staticmethod
    def fingerprint(snapshot: MarketSnapshot) -> str:
        if snapshot.timestamp_source != "synthetic":
            # Receipt time alone is not evidence of replenished liquidity.
            levels = [
                (str(x.price.normalize()), str(x.size.normalize()))
                for x in OrderBook(snapshot).asks
            ]
            return f"{snapshot.book_key}:{sha256(repr(levels).encode()).hexdigest()}"
        return f"{snapshot.book_key}:{snapshot.timestamp.isoformat()}"

    @property
    def exposure(self) -> dict[str, Decimal]:
        exposure: dict[str, Decimal] = {}
        for t in self.trades:
            if t["status"] == "open":
                for key in t["market_keys"]:
                    exposure[key] = exposure.get(key, ZERO) + Decimal(t["total_cost"])
        return exposure

    @property
    def realized_pnl(self) -> Decimal:
        return sum(
            (Decimal(t["realized_pnl"]) for t in self.trades if t["realized_pnl"] is not None), ZERO
        )

    @property
    def free_capital(self) -> Decimal:
        committed = sum(
            (Decimal(t["total_cost"]) for t in self.trades if t["status"] == "open"), ZERO
        )
        return self.engine.settings.paper_capital + self.realized_pnl - committed

    def get_position(self, market_key: str) -> Decimal:
        return sum(
            (
                Decimal(t["quantity"])
                for t in self.trades
                if t["status"] == "open" and market_key in t["market_keys"]
            ),
            ZERO,
        )

    async def cancel_order(self, order_id: str) -> bool:
        # FOK paper orders either fill immediately or raise; there are no resting orders.
        if any(o["id"] == order_id for t in self.trades for o in t["orders"]):
            return False
        raise ValueError("Unknown order")

    async def execute_order(
        self, opportunity: Opportunity, snapshots: dict[str, MarketSnapshot]
    ) -> dict[str, Any]:
        if any(t["opportunity_id"] == opportunity.id for t in self.trades):
            raise ValueError("Opportunity already consumed by a paper fill")
        if opportunity.status != "executable":
            raise ValueError("Opportunity did not pass execution constraints")
        legs = [snapshots.get(s.book_key) for s in opportunity.snapshots]
        if any(s is None for s in legs):
            raise ValueError("Current book unavailable")
        yes, no = legs
        assert yes is not None and no is not None
        fingerprints = [self.fingerprint(s) for s in (yes, no)]
        if any(f in self.consumed for f in fingerprints):
            raise ValueError("Book already consumed by a paper fill; await fresh snapshots")
        if self.engine.settings.mode == "live" and any(
            set(t["market_keys"]) & {yes.key, no.key}
            and (now() - datetime.fromisoformat(t["timestamp"])).total_seconds()
            < self.engine.settings.live_paper_cooldown_seconds
            for t in self.trades
        ):
            raise ValueError("Live paper market cooldown")
        current = self.engine.evaluate(
            yes, no, exposure=self.exposure, free_capital=self.free_capital
        )
        if current.status != "executable":
            raise ValueError(f"Revalidation failed: {current.rejection_reason}")
        quantity = current.available_size
        cost = sum((e.total_cost for e in current.estimates), ZERO)
        trade = {
            "id": str(uuid4()),
            "data_mode": self.engine.settings.mode,
            "settlement_source": None,
            "opportunity_id": opportunity.id,
            "timestamp": now().isoformat(),
            "market": current.market,
            "market_keys": current.market_keys,
            "strategy_type": current.strategy_type,
            "venue": current.venue,
            "quantity": str(quantity),
            "total_cost": str(cost),
            "expected_pnl": str(quantity - cost),
            "realized_pnl": None,
            "status": "open",
            "book_fingerprints": fingerprints,
            "orders": [
                {
                    "id": str(uuid4()),
                    "market_key": s.key,
                    "outcome": s.outcome,
                    "side": "buy",
                    "status": "filled",
                    "quantity": str(quantity),
                    "estimate": estimate.model_dump(mode="json"),
                    "snapshot": s.model_dump(mode="json"),
                }
                for s, estimate in zip((yes, no), current.estimates, strict=True)
            ],
        }
        async with self.db.sessions() as session:
            session.add(TradeRecord(id=trade["id"], payload=trade))
            await session.commit()
        self.trades.append(trade)
        self.consumed.update(fingerprints)
        return trade

    async def settle(self, trade_id: str, resolutions: dict[str, str]) -> dict[str, Any]:
        if self.engine.settings.mode != "mock":
            raise ValueError("Mock resolution is only available in MODE=mock")
        return await self._settle(trade_id, resolutions, "mock", {})

    async def settle_from_venue(self, trade_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
        from app.services.settlement import final_resolution

        resolutions = {}
        for key, item in evidence.items():
            venue, condition = key.split(":", 1)
            outcome = final_resolution(item["gamma"], item["clob"], condition)
            if venue != "polymarket" or outcome is None:
                raise ValueError("Resolution evidence is not final")
            resolutions[key] = outcome
        return await self._settle(trade_id, resolutions, "venue", evidence)

    async def _settle(
        self, trade_id: str, resolutions: dict[str, str], source: str, evidence: dict[str, Any]
    ) -> dict[str, Any]:
        original = next((t for t in self.trades if t["id"] == trade_id), None)
        if original is None:
            raise ValueError("Unknown trade")
        if original["status"] == "settled":
            raise ValueError("Trade already settled")
        if set(resolutions) != set(original["market_keys"]) or any(
            v not in ("YES", "NO") for v in resolutions.values()
        ):
            raise ValueError("Supply a YES or NO resolution for every venue contract")
        payout = sum(
            (
                Decimal(o["quantity"])
                for o in original["orders"]
                if resolutions[o["market_key"]] == o["outcome"]
            ),
            ZERO,
        )
        trade = {
            **original,
            "status": "settled",
            "resolutions": resolutions,
            "settlement_source": source,
            "settlement_evidence": evidence,
            "settled_at": now().isoformat(),
            "realized_pnl": str(payout - Decimal(original["total_cost"])),
        }
        async with self.db.sessions() as session:
            await session.merge(TradeRecord(id=trade_id, payload=trade))
            await session.commit()
        self.trades[self.trades.index(original)] = trade
        return trade
