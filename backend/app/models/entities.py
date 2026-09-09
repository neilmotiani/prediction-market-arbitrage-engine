from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.schemas.domain import now


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class Market(Record, Base):
    __tablename__ = "markets"


class SnapshotRecord(Record, Base):
    __tablename__ = "market_snapshots"
    market_key: Mapped[str] = mapped_column(String(255), index=True)
    __table_args__ = (Index("ix_snapshot_market_time", "market_key", "timestamp"),)


class OpportunityRecord(Record, Base):
    __tablename__ = "opportunities"


class TradeRecord(Record, Base):
    __tablename__ = "simulated_trades"


class MappingRecord(Record, Base):
    __tablename__ = "contract_mappings"


class MetricRecord(Record, Base):
    __tablename__ = "system_metrics"
