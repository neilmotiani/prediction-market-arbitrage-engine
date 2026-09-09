from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, computed_field, model_validator

ZERO = Decimal("0")
ONE = Decimal("1")


def now() -> datetime:
    return datetime.now(UTC)


class Level(BaseModel):
    model_config = ConfigDict(frozen=True)
    price: Decimal = Field(ge=0, le=1, allow_inf_nan=False)
    size: Decimal = Field(gt=0, allow_inf_nan=False)


class FeeSchedule(BaseModel):
    model_config = ConfigDict(frozen=True)
    formula: Literal["polymarket_shares", "zero"]
    rate: Decimal = Field(ge=0, lt=1, allow_inf_nan=False)
    verified_at: AwareDatetime = Field(default_factory=now)
    source: str


class MarketSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    venue: str
    market_id: str
    title: str
    outcome: Literal["YES", "NO"]
    timestamp: AwareDatetime = Field(default_factory=now)
    received_at: AwareDatetime = Field(default_factory=now)
    timestamp_source: Literal["venue", "receipt", "synthetic"] = "synthetic"
    bids: tuple[Level, ...] = ()
    asks: tuple[Level, ...] = ()
    volume: Decimal = Field(default=ZERO, ge=0, allow_inf_nan=False)
    resolution_key: str = ""
    fee_verified: bool = True
    fee_schedule: FeeSchedule | None = None
    minimum_order_size: Decimal = Field(default=Decimal("1"), gt=0)

    @computed_field
    @property
    def best_bid(self) -> Decimal | None:
        return max((x.price for x in self.bids), default=None)

    @computed_field
    @property
    def best_ask(self) -> Decimal | None:
        return min((x.price for x in self.asks), default=None)

    @computed_field
    @property
    def liquidity(self) -> Decimal:
        """Ask-side notional dollars, not volume or open interest."""
        return sum((x.price * x.size for x in self.asks), ZERO)

    @property
    def key(self) -> str:
        return f"{self.venue}:{self.market_id}"

    @property
    def book_key(self) -> str:
        return f"{self.key}:{self.outcome}"


class Fill(BaseModel):
    requested_size: Decimal
    filled_size: Decimal
    average_price: Decimal | None
    notional: Decimal
    slippage: Decimal
    levels: list[Level]


class ExecutionEstimate(BaseModel):
    fill: Fill
    fees: Decimal
    network_cost: Decimal
    latency_reserve: Decimal
    total_cost: Decimal


class Opportunity(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    market: str
    market_keys: list[str]
    venue: str
    strategy_type: Literal["complement", "cross_venue"]
    yes_price: Decimal | None
    no_price: Decimal | None
    gross_edge: Decimal = ZERO
    estimated_fees: Decimal = ZERO
    estimated_slippage: Decimal = ZERO
    execution_costs: Decimal = ZERO
    net_edge: Decimal | None = None
    available_size: Decimal = ZERO
    requested_size: Decimal
    expected_profit: Decimal | None = None
    timestamp: AwareDatetime = Field(default_factory=now)
    execution_score: float = 0
    status: Literal["executable", "theoretical", "rejected"] = "rejected"
    rejection_reason: str | None = None
    estimates: list[ExecutionEstimate] = []
    snapshots: list[MarketSnapshot] = []


class ContractMapping(BaseModel):
    left_key: str
    right_key: str
    resolution_key: str = Field(min_length=3)
    approved_by: str = Field(min_length=3)
    evidence: str = Field(min_length=15)
    same_payout: bool
    same_resolution: bool
    same_outcome_definition: bool
    enabled: bool = True

    @model_validator(mode="after")
    def validate_equivalence(self) -> "ContractMapping":
        if self.left_key == self.right_key:
            raise ValueError("Mapping must connect distinct contracts")
        if not all((self.same_payout, self.same_resolution, self.same_outcome_definition)):
            raise ValueError("Payout, resolution and outcome semantics must all be validated")
        return self


class SimulationRequest(BaseModel):
    action: Literal["execute", "settle"] = "execute"
    opportunity_id: str | None = None
    trade_id: str | None = None
    resolutions: dict[str, Literal["YES", "NO"]] = {}
