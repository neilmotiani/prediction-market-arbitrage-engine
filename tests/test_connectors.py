from decimal import Decimal as D

import httpx
import pytest
from app.config import Settings
from app.connectors.kalshi.client import normalize_orderbook
from app.connectors.polymarket.client import PolymarketConnector, normalize_book
from app.schemas.domain import now


def test_kalshi_bid_to_opposite_ask():
    books = normalize_orderbook(
        {"orderbook_fp": {"yes_dollars": [["0.43", "100"]], "no_dollars": [["0.52", "50"]]}},
        "T",
        "Test",
    )
    y, n = books
    assert y.best_bid == D("0.43") and y.best_ask == D("0.48")
    assert n.best_ask == D("0.57") and y.asks[0].size == 50
    assert y.timestamp_source == "receipt" and not y.fee_verified


def test_kalshi_legacy_and_empty():
    books = normalize_orderbook({"orderbook": {"yes": [[43, 10]], "no": None}}, "T", "Test")
    assert books[0].best_ask is None and books[1].best_ask == D("0.57")
    with pytest.raises(ValueError):
        normalize_orderbook({}, "T", "Test")


def pair():
    return {"market_id": "condition", "title": "Test", "yes_token": "Y", "no_token": "N"}


def raw(token="Y"):
    return {
        "market": "condition",
        "asset_id": token,
        "timestamp": str(int(now().timestamp() * 1000)),
        "asks": [{"price": "0.45", "size": "100"}],
        "bids": [],
    }


def test_polymarket_identity_and_timestamp():
    book = normalize_book(raw(), pair(), "YES")
    assert book.best_ask == D("0.45") and book.timestamp_source == "venue"
    assert not book.fee_verified
    with pytest.raises(ValueError):
        normalize_book({**raw(), "market": "different"}, pair(), "YES")
    with pytest.raises(ValueError):
        normalize_book(raw("N"), pair(), "YES")


async def test_polymarket_fetch_and_http_failure():
    connector = PolymarketConnector(Settings(_env_file=None, polymarket_token_pairs=[pair()]))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=raw(r.url.params["token_id"]))
        )
    ) as client:
        assert len(await connector.fetch(client)) == 2
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(403))
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await connector.fetch(client)
