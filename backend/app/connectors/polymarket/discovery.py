"""Discover ordinary binary contracts and validate identity against the CLOB."""

import asyncio
import json
import logging
from decimal import Decimal
from typing import Any

import httpx

from app.schemas.domain import FeeSchedule

logger = logging.getLogger(__name__)
GAMMA = "https://gamma-api.polymarket.com/markets"
CLOB = "https://clob.polymarket.com"


def parse_market(raw: dict[str, Any]) -> dict[str, Any]:
    if not all(raw.get(k) is True for k in ("active", "acceptingOrders", "enableOrderBook")):
        raise ValueError("Market is not accepting orders")
    if raw.get("closed") is not False or raw.get("negRisk") is not False:
        raise ValueError("Only open ordinary binary markets are supported")
    outcomes = raw["outcomes"]
    tokens = raw["clobTokenIds"]
    outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
    tokens = json.loads(tokens) if isinstance(tokens, str) else tokens
    labels = [x.upper() for x in outcomes]
    if len(labels) != 2 or set(labels) != {"YES", "NO"} or len(set(tokens)) != 2:
        raise ValueError("Not a distinct YES/NO pair")
    fee = None
    source = f"{GAMMA}/{raw['id']}"
    if raw.get("feesEnabled") is False:
        fee = FeeSchedule(formula="zero", rate=0, source=source)
    elif raw.get("feesEnabled") is True:
        schedule = raw.get("feeSchedule") or {}
        if schedule.get("exponent") == 1 and schedule.get("takerOnly") is True:
            fee = FeeSchedule(formula="polymarket_shares", rate=schedule["rate"], source=source)
    return {
        "market_id": raw["conditionId"],
        "title": raw["question"],
        "yes_token": str(tokens[labels.index("YES")]),
        "no_token": str(tokens[labels.index("NO")]),
        "fee_schedule": fee,
        "volume": Decimal(str(raw.get("volume24hr") or 0)),
    }


async def discover(client: httpx.AsyncClient, limit: int) -> list[dict[str, Any]]:
    response = await client.get(
        GAMMA,
        params={
            "active": "true",
            "closed": "false",
            "limit": 100,
            "order": "volume24hr",
            "ascending": "false",
        },
    )
    response.raise_for_status()
    candidates = []
    for raw in response.json():
        try:
            candidates.append(parse_market(raw))
        except (KeyError, ValueError, TypeError):
            continue
    semaphore = asyncio.Semaphore(4)

    async def validate(pair: dict[str, Any]) -> dict[str, Any] | None:
        async with semaphore:
            try:
                response = await client.get(f"{CLOB}/markets/{pair['market_id']}")
                response.raise_for_status()
                raw = response.json()
                if (
                    raw.get("condition_id") != pair["market_id"]
                    or raw.get("closed") is not False
                    or raw.get("neg_risk") is not False
                    or raw.get("accepting_orders") is not True
                    or raw.get("active") is not True
                ):
                    return None
                identities = {t["outcome"].upper(): str(t["token_id"]) for t in raw["tokens"]}
                if identities != {"YES": pair["yes_token"], "NO": pair["no_token"]}:
                    return None
                pair["minimum_order_size"] = Decimal(str(raw["minimum_order_size"]))
                return pair
            except (httpx.HTTPError, KeyError, ValueError, TypeError):
                logger.warning("discovery_market_skipped", extra={"market": pair["market_id"]})
                return None

    validated = await asyncio.gather(*(validate(p) for p in candidates[: limit * 2]))
    return [p for p in validated if p is not None][:limit]
