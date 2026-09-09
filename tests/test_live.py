from datetime import timedelta
from decimal import Decimal as D

import httpx
import pytest
from app.config import Settings
from app.connectors.polymarket.discovery import discover, parse_market
from app.database.session import Database
from app.models.orderbook import OrderBook
from app.schemas.domain import FeeSchedule, now
from app.services.market_data import ResearchRuntime
from app.services.paper_trading import PaperExecutionProvider
from app.services.settlement import final_resolution
from conftest import snapshot


def market(**updates):
    return {
        "id": "123",
        "conditionId": "condition",
        "question": "Example?",
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "enableOrderBook": True,
        "negRisk": False,
        "outcomes": '["No", "Yes"]',
        "clobTokenIds": '["no-token", "yes-token"]',
        "feesEnabled": True,
        "feeSchedule": {"rate": 0.07, "exponent": 1, "takerOnly": True},
        **updates,
    }


def live_pair(rate="0"):
    fee = FeeSchedule(formula="polymarket_shares", rate=rate, source="https://example.test/fees")
    return [
        snapshot(p, o, size="200", timestamp_source="venue", fee_schedule=fee)
        for p, o in (("0.45", "YES"), ("0.50", "NO"))
    ]


def test_discovery_maps_by_label_and_does_not_guess_fees():
    pair = parse_market(market())
    assert pair["yes_token"] == "yes-token"
    assert pair["fee_schedule"].rate == D(".07")
    assert parse_market(market(feesEnabled=None))["fee_schedule"] is None
    assert parse_market(market(feeSchedule={"rate": 0.07, "exponent": 2}))["fee_schedule"] is None
    assert parse_market(market(feesEnabled=False))["fee_schedule"].formula == "zero"


@pytest.mark.parametrize(
    "updates",
    [
        {"closed": True},
        {"negRisk": True},
        {"acceptingOrders": False},
        {"outcomes": '["A", "B"]'},
        {"clobTokenIds": '["same", "same"]'},
    ],
)
def test_discovery_rejects_unsupported_markets(updates):
    with pytest.raises(ValueError):
        parse_market(market(**updates))


async def test_discovery_clob_identity_and_partial_failure():
    def response(request):
        if request.url.host == "gamma-api.polymarket.com":
            return httpx.Response(200, json=[market(), market(conditionId="bad")])
        if request.url.path.endswith("bad"):
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "condition_id": "condition",
                "closed": False,
                "active": True,
                "neg_risk": False,
                "accepting_orders": True,
                "minimum_order_size": 5,
                "tokens": [
                    {"outcome": "YES", "token_id": "yes-token"},
                    {"outcome": "NO", "token_id": "no-token"},
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        pairs = await discover(client, 2)
    assert len(pairs) == 1 and pairs[0]["minimum_order_size"] == 5


def test_buy_fee_gross_up_and_net_deliverable_depth(engine):
    y, _ = live_pair("0.07")
    estimate = engine.execution.estimate(OrderBook(y), D(100))
    # q_net = q_gross * (1 - rate*(1-p)); cash = q_gross*p.
    expected_cash = D(100) * D(".45") / (1 - D(".07") * D(".55"))
    assert estimate.total_cost >= expected_cash
    assert estimate.total_cost - expected_cash < D(".00001")
    shallow = y.model_copy(update={"asks": (y.asks[0].model_copy(update={"size": D(100)}),)})
    partial = engine.execution.estimate(OrderBook(shallow), D(100))
    assert partial.fill.filled_size == D("96.15")


def test_live_metadata_freshness_and_minimum_size(engine):
    engine.settings.mode = "live"
    y, n = live_pair()
    assert engine.evaluate(y, n).status == "executable"
    missing = y.model_copy(update={"fee_schedule": None})
    assert "missing_live_fee_metadata" in engine.evaluate(missing, n).rejection_reason
    old = y.fee_schedule.model_copy(update={"verified_at": now() - timedelta(hours=1)})
    assert (
        "stale_live_fee_metadata"
        in engine.evaluate(y.model_copy(update={"fee_schedule": old}), n).rejection_reason
    )
    assert (
        "minimum_order_size"
        in engine.evaluate(y.model_copy(update={"minimum_order_size": D(150)}), n).rejection_reason
    )
    assert "synthetic_data_in_live_mode" in engine.evaluate(snapshot(), n).rejection_reason


async def test_live_auto_execution_and_persistent_book_dedup(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="live",
        auto_paper_trade=True,
        database_url=f"sqlite+aiosqlite:///{tmp_path}/live.db",
    )
    rt = ResearchRuntime(settings, Database(settings.database_url), connector_factory=lambda: [])
    await rt.start()
    y, n = live_pair()
    await rt.ingest([y, n])
    assert len(rt.paper.trades) == 1
    assert rt.paper.trades[0]["data_mode"] == "live"
    assert rt.paper.trades[0]["realized_pnl"] is None
    # Re-fetching unchanged real books is not replenishment.
    await rt.ingest([s.model_copy(update={"timestamp": now()}) for s in (y, n)])
    assert len(rt.paper.trades) == 1
    restored = PaperExecutionProvider(rt.db, rt.engine)
    await restored.restore()
    assert restored.consumed == rt.paper.consumed
    with pytest.raises(ValueError, match="only available"):
        await restored.settle(restored.trades[0]["id"], {y.key: "YES"})
    await rt.stop()


async def test_database_mode_isolation(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/mode.db"
    mock = ResearchRuntime(
        Settings(_env_file=None, database_url=url), Database(url), connector_factory=lambda: []
    )
    await mock.start()
    await mock.stop()
    live = ResearchRuntime(
        Settings(_env_file=None, mode="live", database_url=url),
        Database(url),
        connector_factory=lambda: [],
    )
    with pytest.raises(ValueError, match="mode mismatch"):
        await live.start()
    await live.db.close()


def resolution():
    return (
        {"conditionId": "test", "closed": True, "umaResolutionStatus": "resolved"},
        {
            "condition_id": "test",
            "closed": True,
            "tokens": [{"outcome": "YES", "winner": True}, {"outcome": "NO", "winner": False}],
        },
    )


def test_only_final_unambiguous_resolution_is_accepted():
    gamma, clob = resolution()
    assert final_resolution(gamma, clob, "test") == "YES"
    assert final_resolution({**gamma, "umaResolutionStatus": "proposed"}, clob, "test") is None
    assert final_resolution(gamma, {**clob, "closed": False}, "test") is None
    assert final_resolution(gamma, clob, "other") is None
    clob["tokens"][1]["winner"] = True
    assert final_resolution(gamma, clob, "test") is None


async def test_live_settlement_uses_verified_evidence(engine, tmp_path):
    engine.settings.mode = "live"
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/settle.db")
    await db.initialize()
    provider = PaperExecutionProvider(db, engine)
    y, n = live_pair()
    trade = await provider.execute_order(engine.evaluate(y, n), {s.book_key: s for s in (y, n)})
    gamma, clob = resolution()
    evidence = {y.key: {"gamma": gamma, "clob": clob}}
    result = await provider.settle_from_venue(trade["id"], evidence)
    assert result["settlement_source"] == "venue"
    assert D(result["realized_pnl"]) == 5
    with pytest.raises(ValueError, match="already settled"):
        await provider.settle_from_venue(trade["id"], evidence)
    await db.close()


def test_book_fingerprint_ignores_encoding_and_reordered_levels():
    from app.schemas.domain import Level

    y, _ = live_pair()
    equivalent = y.model_copy(
        update={
            "asks": (
                Level(price=".4500", size="120.00"),
                Level(price=".45", size="80"),
            )
        }
    )
    assert PaperExecutionProvider.fingerprint(y) == PaperExecutionProvider.fingerprint(equivalent)


async def test_resolution_http_flow_retains_evidence():
    from app.services.settlement import fetch_resolution

    gamma, clob = resolution()
    gamma["id"] = "123"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, json=[gamma] if r.url.host == "gamma-api.polymarket.com" else clob
            )
        )
    ) as client:
        evidence = await fetch_resolution(client, "polymarket:test")
        assert evidence["outcome"] == "YES"
        assert evidence["gamma"] == gamma and evidence["clob"] == clob
        assert await fetch_resolution(client, "kalshi:test") is None
    gamma["umaResolutionStatus"] = "proposed"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[gamma]))
    ) as client:
        assert await fetch_resolution(client, "polymarket:test") is None
