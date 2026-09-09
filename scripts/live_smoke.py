"""Opt-in public-data connectivity check. No orders or credentials."""

import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import Settings
from app.connectors.kalshi.client import normalize_orderbook
from app.connectors.polymarket.client import PolymarketConnector


async def main() -> None:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            "https://gamma-api.polymarket.com/markets",
            params={"limit": 10, "active": "true", "closed": "false"},
        )
        response.raise_for_status()
        market = next(
            m
            for m in response.json()
            if m.get("enableOrderBook") and json.loads(m["outcomes"]) == ["Yes", "No"]
        )
        yes, no = json.loads(market["clobTokenIds"])
        pair = {
            "market_id": market["conditionId"],
            "title": market["question"],
            "yes_token": yes,
            "no_token": no,
        }
        connector = PolymarketConnector(Settings(_env_file=None, polymarket_token_pairs=[pair]))
        books = await connector.fetch(client)
        print(
            f"Polymarket REST: {len(books)} normalized books, {sum(len(b.asks) + len(b.bids) for b in books)} levels"
        )
        stream = connector.stream()
        try:
            await anext(stream)  # Initial REST batch.
            batch = await asyncio.wait_for(anext(stream), timeout=20)
            print(f"Polymarket WebSocket + refresh: {len(batch)} normalized books")
        finally:
            await stream.aclose()
        try:
            response = await client.get(
                "https://external-api.kalshi.com/trade-api/v2/markets",
                params={"limit": 1, "status": "open"},
            )
            response.raise_for_status()
            market = response.json()["markets"][0]
            response = await client.get(
                f"https://external-api.kalshi.com/trade-api/v2/markets/{market['ticker']}/orderbook"
            )
            response.raise_for_status()
            books = normalize_orderbook(response.json(), market["ticker"], market["title"])
            print(f"Kalshi REST: {len(books)} normalized books")
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            print(f"Kalshi unavailable: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
