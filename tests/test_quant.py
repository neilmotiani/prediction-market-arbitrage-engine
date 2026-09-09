from datetime import timedelta
from decimal import Decimal as D

import pytest
from app.models.orderbook import OrderBook
from app.schemas.domain import ContractMapping, Level, now
from app.services.contract_matching import normalize_title, similarity
from conftest import snapshot
from pydantic import ValidationError


def test_complement_math(engine):
    op = engine.evaluate(snapshot(), snapshot("0.50", "NO"))
    assert op.gross_edge == D("0.05")
    assert op.net_edge == D("0.05")
    assert op.expected_profit == 5
    assert op.status == "executable"


@pytest.mark.parametrize("yes,no", [("0.51", "0.51"), ("0.50", "0.50"), ("1", "0")])
def test_no_arbitrage(engine, yes, no):
    op = engine.evaluate(snapshot(yes), snapshot(no, "NO"))
    assert op.status == "rejected"
    assert "no_theoretical_arbitrage" in op.rejection_reason


def test_fees_and_network_counted_once(engine, settings):
    settings.fee_bps = D(100)
    settings.network_cost = D("0.10")
    settings.latency_buffer_bps = D(10)
    op = engine.evaluate(snapshot(), snapshot("0.50", "NO"))
    assert op.estimated_fees == D("0.0095")
    assert op.execution_costs == D("0.004")
    assert op.net_edge == D("0.0365")
    assert op.expected_profit == D("3.65")


def test_fees_remove_edge(engine, settings):
    settings.fee_bps = D(600)
    op = engine.evaluate(snapshot(), snapshot("0.50", "NO"))
    assert op.status == "theoretical" and op.net_edge < 0


def test_walk_aggregates_sorts_and_partial_fill():
    s = snapshot().model_copy(
        update={
            "asks": (
                Level(price="0.50", size=50),
                Level(price="0.45", size=20),
                Level(price="0.45", size=30),
            )
        }
    )
    book = OrderBook(s)
    fill = book.estimate_fill("buy", D(80))
    assert fill.filled_size == 80
    assert fill.notional == D("37.5")
    assert fill.average_price == D("0.46875")
    assert fill.slippage == D("0.01875")
    assert book.available_depth("buy", D("0.45")) == 50
    assert book.estimate_fill("buy", D(120)).filled_size == 100


def test_bid_side_and_empty():
    s = snapshot().model_copy(
        update={"bids": (Level(price="0.43", size=10), Level(price="0.42", size=10))}
    )
    b = OrderBook(s)
    assert b.best_bid() == D("0.43")
    assert b.spread() == D("0.02") and b.mid_price() == D("0.44")
    assert b.estimate_fill("sell", D(20)).average_price == D("0.425")
    assert b.available_depth("sell", D("0.43")) == 10
    empty = OrderBook(s.model_copy(update={"bids": (), "asks": ()}))
    assert empty.mid_price() is None and empty.spread() is None
    assert empty.estimate_fill("buy", D(10)).average_price is None


@pytest.mark.parametrize("q", [D(0), D(-1), D("NaN"), D("Infinity")])
def test_invalid_quantity(q):
    with pytest.raises(ValueError):
        OrderBook(snapshot()).estimate_fill("buy", q)


@pytest.mark.parametrize("price,size", [("-0.1", 1), ("1.1", 1), ("NaN", 1), ("0.5", 0)])
def test_level_validation(price, size):
    with pytest.raises(ValidationError):
        Level(price=price, size=size)


def test_insufficient_depth_has_no_claimed_profit(engine):
    op = engine.evaluate(snapshot(size="10"), snapshot("0.50", "NO"))
    assert op.available_size == 10 and op.net_edge is None and op.expected_profit is None
    assert "insufficient_depth" in op.rejection_reason


def test_liquidity(engine, settings):
    settings.min_liquidity = D(60)
    assert (
        "minimum_liquidity" in engine.evaluate(snapshot(), snapshot("0.50", "NO")).rejection_reason
    )


@pytest.mark.parametrize("delta", [-30, 10])
def test_stale_or_future(engine, delta):
    op = engine.evaluate(
        snapshot(timestamp=now() + timedelta(seconds=delta)), snapshot("0.50", "NO")
    )
    assert "stale_or_future_market_data" in op.rejection_reason


def test_asynchronous_legs(engine):
    op = engine.evaluate(snapshot(timestamp=now() - timedelta(seconds=7)), snapshot("0.50", "NO"))
    assert "asynchronous_legs" in op.rejection_reason


def test_missing_and_crossed(engine):
    y = snapshot().model_copy(update={"asks": ()})
    assert "missing_asks" in engine.evaluate(y, snapshot("0.5", "NO")).rejection_reason
    y = snapshot().model_copy(update={"bids": (Level(price="0.6", size=10),)})
    assert "crossed_order_book" in engine.evaluate(y, snapshot("0.5", "NO")).rejection_reason


def test_slippage_rejected(engine, settings):
    settings.max_slippage = D("0.01")
    y = snapshot().model_copy(
        update={"asks": (Level(price="0.4", size=1), Level(price="0.45", size=100))}
    )
    assert "slippage_limit" in engine.evaluate(y, snapshot("0.5", "NO")).rejection_reason


def test_sizing_limits_use_all_costs(engine, settings):
    settings.max_capital_per_opportunity = D(20)
    settings.fee_bps = D(100)
    op = engine.evaluate(snapshot(), snapshot("0.5", "NO"))
    assert sum(e.total_cost for e in op.estimates) <= 20
    assert op.available_size == 20
    limited = engine.evaluate(snapshot(), snapshot("0.5", "NO"), free_capital=D(0))
    assert limited.rejection_reason == "capital_limit"
    limited = engine.evaluate(
        snapshot(), snapshot("0.5", "NO"), exposure={"polymarket:test": D(2000)}
    )
    assert limited.rejection_reason == "capital_limit"


def test_title_matching():
    assert normalize_title("On December 31, 2026?") == normalize_title("On 2026-12-31!")
    assert similarity("CPI below 3% in 2026?", "CPI below 4% in 2026?") == 0
    assert similarity("CPI below 3%?", "CPI below 3%!") == 1
    assert similarity("", "") == 0


def mapping():
    return ContractMapping(
        left_key="polymarket:test",
        right_key="kalshi:test",
        resolution_key="same",
        approved_by="tester",
        evidence="Identical mock settlement rules.",
        same_payout=True,
        same_resolution=True,
        same_outcome_definition=True,
    )


def test_cross_market_requires_validation(engine):
    y, n = (
        snapshot("0.43", resolution_key="same"),
        snapshot("0.52", "NO", venue="kalshi", resolution_key="same"),
    )
    assert "unvalidated_contract_mapping" in engine.evaluate(y, n).rejection_reason
    engine.matcher.mappings.append(mapping())
    op = engine.evaluate(y, n)
    assert op.status == "executable" and op.net_edge == D("0.05")
    assert op.strategy_type == "cross_venue"
    assert not engine.matcher.validated(y, n.model_copy(update={"resolution_key": "other"}))


def test_invalid_mapping():
    with pytest.raises(ValidationError):
        ContractMapping.model_validate({**mapping().model_dump(), "same_resolution": False})


def test_kalshi_fee_round_up(engine, settings):
    settings.kalshi_fee_coefficient = D("0.07")
    fill = OrderBook(snapshot("0.43")).estimate_fill("buy", D(1))
    assert engine.execution.fees("kalshi", fill) == D("0.02")


def test_live_fees_fail_closed(engine):
    op = engine.evaluate(snapshot(fee_verified=False), snapshot("0.5", "NO"))
    assert "unverified_live_fee_schedule" in op.rejection_reason
