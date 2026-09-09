from decimal import Decimal

import pytest
from app.config import Settings
from app.schemas.domain import Level, MarketSnapshot
from app.services.arbitrage import ArbitrageEngine
from app.services.contract_matching import ContractMatcher


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        fee_bps=0,
        kalshi_fee_coefficient=0,
        network_cost=0,
        latency_buffer_bps=0,
        min_liquidity=0,
        max_capital_per_opportunity=1000,
        max_capital_per_market=2000,
    )


@pytest.fixture
def engine(settings: Settings) -> ArbitrageEngine:
    return ArbitrageEngine(settings, ContractMatcher(0.85, []))


def snapshot(price: str = "0.45", outcome: str = "YES", size: str = "100", **kw) -> MarketSnapshot:
    return MarketSnapshot(
        venue=kw.pop("venue", "polymarket"),
        market_id=kw.pop("market_id", "test"),
        title="Test market",
        outcome=outcome,
        asks=(Level(price=Decimal(price), size=Decimal(size)),),
        **kw,
    )
