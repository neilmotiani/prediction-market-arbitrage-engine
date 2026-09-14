import asyncio
import json
from datetime import timedelta
from decimal import Decimal as D

import httpx
import pytest
from app.config import Settings
from app.connectors.polymarket.client import PolymarketConnector
from app.connectors.polymarket.discovery import discover, parse_market
from app.connectors.polymarket.signals import MarketSignals
from app.database.session import Database
from app.models.orderbook import OrderBook
from app.schemas.domain import Level, now
from app.services.diagnostics import scan_diagnostics
from app.services.market_data import ResearchRuntime
from conftest import snapshot
from test_connectors import pair, raw
from test_live import live_pair, market


def test_profit_sizing_recovers_small_edge_hidden_by_large_order(engine, settings):
    y = snapshot(".40").model_copy(
        update={
            "asks": (
                Level(price=".40", size=10),
                Level(price=".65", size=90),
            )
        }
    )
    n = snapshot(".50", "NO")
    assert engine.evaluate(y, n).status == "theoretical"
    settings.sizing_policy = "profit"
    op = engine.evaluate(y, n)
    assert op.status == "executable" and op.available_size == 10
    assert op.expected_profit == 1 and op.requested_size == 100
    assert all(e.fill.filled_size == 10 for e in op.estimates)


def test_profit_sizing_recovers_complete_small_pair(engine, settings):
    settings.sizing_policy = "profit"
    op = engine.evaluate(snapshot(size="12"), snapshot(".50", "NO", size="16"))
    assert op.status == "executable" and op.available_size == 12
    assert op.expected_profit == D(".60")


def test_profit_sizing_keeps_fixed_cost_and_minimum_order_constraints(engine, settings):
    settings.sizing_policy = "profit"
    settings.network_cost = D(".40")
    y, n = snapshot(size="10"), snapshot(".50", "NO")
    assert engine.evaluate(y, n).status != "executable"
    settings.network_cost = 0
    assert (
        engine.evaluate(y.model_copy(update={"minimum_order_size": D(20)}), n).status
        != "executable"
    )


@pytest.mark.parametrize(
    "fee_bps,network,slippage", [(0, 0, ".02"), (20, ".05", ".01"), (200, ".15", ".05")]
)
def test_profit_sizing_agrees_with_exhaustive_feasible_profit(
    engine, settings, fee_bps, network, slippage
):
    settings.sizing_policy = "profit"
    settings.fee_bps, settings.network_cost, settings.max_slippage = (
        D(fee_bps),
        D(network),
        D(slippage),
    )
    settings.max_capital_per_opportunity = D(20)
    y = snapshot().model_copy(
        update={"asks": (Level(price=".40", size=13), Level(price=".47", size=30))}
    )
    n = snapshot(".5", "NO", size="40")
    feasible = []
    for quantity in range(1, 41):
        estimates = [engine.execution.estimate(OrderBook(s), D(quantity)) for s in (y, n)]
        cost = sum(e.total_cost for e in estimates)
        profit = quantity - cost
        if (
            cost <= 20
            and profit / quantity >= settings.min_net_edge
            and sum(e.fill.slippage for e in estimates) <= settings.max_slippage
        ):
            feasible.append((profit, -quantity))
    best = max(feasible)
    op = engine.evaluate(y, n, requested=D(40))
    assert op.status == "executable" and op.available_size == -best[1]
    assert op.expected_profit == best[0]


def test_no_profit_policy_can_manufacture_edge(engine, settings):
    settings.sizing_policy = "profit"
    assert engine.evaluate(snapshot(".51"), snapshot(".51", "NO")).status == "rejected"


def test_profit_sizing_uses_net_depth_after_live_share_fees(engine, settings):
    settings.mode, settings.sizing_policy = "live", "profit"
    y, n = live_pair(".07")
    legs = [
        s.model_copy(update={"asks": (s.asks[0].model_copy(update={"size": D(100)}),)})
        for s in (y, n)
    ]
    op = engine.evaluate(*legs)
    assert op.status == "executable" and op.available_size == 96
    assert op.estimated_fees > 0 and op.expected_profit > 0
    assert all(e.fill.filled_size == 96 for e in op.estimates)


def test_discovery_excludes_past_end_markets():
    with pytest.raises(ValueError, match="scheduled end"):
        parse_market(market(endDate=(now() - timedelta(seconds=1)).isoformat()))


async def test_discovery_paginates_and_diversifies_event_exposure():
    offsets = []

    def response(request):
        if request.url.host == "gamma-api.polymarket.com":
            offset = int(request.url.params["offset"])
            offsets.append(offset)
            if offset == 0:
                return httpx.Response(
                    200,
                    json=[
                        market(conditionId=f"first-{i}", events=[{"id": "same-event"}])
                        for i in range(100)
                    ],
                )
            return httpx.Response(
                200, json=[market(conditionId="next", events=[{"id": "other-event"}])]
            )
        condition = request.url.path.split("/")[-1]
        return httpx.Response(
            200,
            json={
                "condition_id": condition,
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

    stats = {}
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        selected = await discover(client, 3, pages=2, per_event=2, diagnostics=stats)
    assert offsets == [0, 100]
    assert [p["market_id"] for p in selected] == ["first-0", "first-1", "next"]
    assert stats["selected_events"] == 2 and stats["discovery_rows"] == 101


async def test_batch_normalization_uses_identity_not_response_order():
    connector = PolymarketConnector(Settings(_env_file=None))

    def response(request):
        assert request.method == "POST" and request.url.path == "/books"
        assert json.loads(request.content) == [{"token_id": "Y"}, {"token_id": "N"}]
        return httpx.Response(200, json=[raw("N"), raw("Y")])

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        books = await connector.fetch_batch(client, [pair()])
    assert [b.outcome for b in books] == ["YES", "NO"]


@pytest.mark.parametrize(
    "rows", [[raw("Y")], [raw("Y"), raw("Y")], [raw("Y"), {**raw("N"), "market": "wrong"}]]
)
async def test_batch_never_exposes_half_or_mismatched_pair(rows):
    connector = PolymarketConnector(Settings(_env_file=None))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=rows))
    ) as client:
        with pytest.raises(ValueError, match="No complete"):
            await connector.fetch_batch(client, [pair()])
    assert connector.diagnostics["book_errors"] > 0


def test_websocket_signals_coalesce_and_validate_identity():
    stats = {}
    signals = MarketSignals([pair()], stats)
    message = json.dumps(
        {"event_type": "price_change", "market": "condition", "price_changes": [{"asset_id": "Y"}]}
    )
    for _ in range(100):
        signals.accept(message)
    signals.accept("PONG")
    signals.accept(json.dumps({"event_type": "book", "market": "wrong", "asset_id": "N"}))
    assert signals.pending == {"condition"} and signals.ready.is_set()
    assert signals.take() == {"condition"} and not signals.ready.is_set()


async def test_discovery_stream_rechecks_positive_quotes(monkeypatch):
    async def fake_discover(*args, **kwargs):
        return [pair()]

    monkeypatch.setattr("app.connectors.polymarket.client.discover", fake_discover)
    connector = PolymarketConnector(Settings(_env_file=None, polymarket_websocket=False))
    calls = 0

    def response(request):
        nonlocal calls
        calls += 1
        price = ".45" if calls == 1 else ".60"
        return httpx.Response(
            200,
            json=[
                {**raw("Y"), "asks": [{"price": price, "size": "100"}]},
                {**raw("N"), "asks": [{"price": ".50", "size": "100"}]},
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        stream = connector.discovered_stream(client)
        books = await anext(stream)
        await stream.aclose()
    assert calls == 2 and sum(b.best_ask for b in books) > 1
    assert connector.diagnostics["gross_rechecks"] == 1


async def test_rest_refresh_continues_without_venue_socket(monkeypatch):
    async def fake_discover(*args, **kwargs):
        return [pair()]

    async def disconnected(self):
        self.diagnostics["transport"] = "rest_fallback"
        await asyncio.Event().wait()

    monkeypatch.setattr("app.connectors.polymarket.client.discover", fake_discover)
    monkeypatch.setattr(MarketSignals, "run", disconnected)
    connector = PolymarketConnector(
        Settings(_env_file=None, poll_interval=0.1, live_refresh_interval=0.1)
    )
    rows = [{**raw(token), "asks": [{"price": ".55", "size": "100"}]} for token in ("Y", "N")]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=rows))
    ) as client:
        stream = connector.discovered_stream(client)
        assert len(await anext(stream)) == 2
        assert len(await asyncio.wait_for(anext(stream), timeout=1)) == 2
        await stream.aclose()
    assert connector.diagnostics["transport"] == "rest_fallback"
    assert connector.diagnostics["book_refreshes"] == 2


def test_diagnostics_separates_missing_quotes_gross_and_net(engine):
    opportunities = [
        engine.evaluate(snapshot(".51"), snapshot(".51", "NO")),
        engine.evaluate(snapshot(), snapshot(".50", "NO")),
        engine.evaluate(snapshot().model_copy(update={"asks": ()}), snapshot(".5", "NO")),
    ]
    result = scan_diagnostics(opportunities)
    assert result["quoted_pairs"] == 2 and result["positive_gross"] == 1
    assert result["positive_net"] == 1 and result["executable"] == 1
    assert result["cross_venue_pairs"] == 0
    assert result["rejection_reasons"]["missing_asks"] == 1


async def test_incremental_scan_preserves_other_markets_and_rejects_older_books(tmp_path):
    settings = Settings(
        _env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path}/incremental.db"
    )
    rt = ResearchRuntime(settings, Database(settings.database_url), connector_factory=lambda: [])
    await rt.start()
    a = [snapshot(), snapshot(".50", "NO")]
    b = [snapshot(market_id="second"), snapshot(".50", "NO", market_id="second")]
    await rt.ingest(a + b)
    assert rt.checks == 2
    await rt.ingest(a)
    assert rt.checks == 3 and len(rt.current_opportunities()) == 2
    await rt.ingest([a[0].model_copy(update={"timestamp": now() - timedelta(seconds=60)})])
    assert rt.checks == 3 and rt.out_of_order_books == 1
    assert rt.books[a[0].book_key].timestamp == a[0].timestamp
    await rt.stop()


async def test_incremental_scan_removes_pairs_that_no_longer_match(tmp_path):
    settings = Settings(_env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path}/rematch.db")
    rt = ResearchRuntime(settings, Database(settings.database_url), connector_factory=lambda: [])
    await rt.start()
    y, n = snapshot(), snapshot(".50", "NO", venue="kalshi")
    await rt.ingest([y, n])
    assert len(rt.opportunities) == 1
    await rt.ingest([n.model_copy(update={"title": "Unrelated event ending in 2028"})])
    assert rt.opportunities == []
    await rt.stop()
