from decimal import Decimal
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    mode: Literal["mock", "live"] = "mock"
    database_url: str = "sqlite+aiosqlite:///./research.db"
    poll_interval: float = Field(default=3, ge=0.1)
    requested_size: int = Field(default=100, ge=1, le=100000)
    max_capital_per_opportunity: Decimal = Field(default=Decimal("100"), gt=0)
    max_capital_per_market: Decimal = Field(default=Decimal("500"), gt=0)
    paper_capital: Decimal = Field(default=Decimal("10000"), gt=0)
    min_net_edge: Decimal = Field(default=Decimal("0.005"), ge=0)
    min_liquidity: Decimal = Field(default=Decimal("20"), ge=0)
    max_slippage: Decimal = Field(default=Decimal("0.02"), ge=0)
    max_data_age_seconds: float = Field(default=15, gt=0)
    max_leg_skew_seconds: float = Field(default=5, ge=0)
    fee_bps: Decimal = Field(default=Decimal("20"), ge=0)
    kalshi_fee_coefficient: Decimal = Field(default=Decimal("0.07"), ge=0)
    network_cost: Decimal = Field(default=Decimal("0.02"), ge=0)
    latency_buffer_bps: Decimal = Field(default=Decimal("10"), ge=0)
    match_threshold: float = Field(default=0.85, ge=0, le=1)
    mapping_file: str = "docs/contract-mappings.json"
    cors_origins: list[str] = ["http://localhost:3000"]
    polymarket_token_pairs: list[dict[str, str]] = []
    kalshi_tickers: list[str] = []
    kalshi_resolution_keys: dict[str, str] = {}
    polymarket_websocket: bool = True
