"""Discover ordinary binary contracts and validate identity against the CLOB."""

import asyncio
import json
import logging
from collections import Counter
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from app.schemas.domain import FeeSchedule, now

logger = logging.getLogger(__name__)
GAMMA = "https://gamma-api.polymarket.com/markets"
CLOB = "https://clob.polymarket.com"


def parse_market(raw: dict[str, Any]) -> dict[str, Any]:
    if not all(raw.get(k) is True for k in ("active", "acceptingOrders", "enableOrderBook")):
        raise ValueError("Market is not accepting orders")
    if raw.get("closed") is not False or raw.get("negRisk") is not False:
        raise ValueError("Only open ordinary binary markets are supported")
    if (
        raw.get("endDate")
        and datetime.fromisoformat(raw["endDate"].replace("Z", "+00:00")) <= now()
    ):
        raise ValueError("Market has passed its scheduled end; exclude pending resolutions")
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
        "event_id": str((raw.get("events") or [{}])[0].get("id") or raw["conditionId"]),
    }


async def discover(
    client: httpx.AsyncClient,
    limit: int,
    *,
    pages: int = 1,
    per_event: int = 2,
    diagnostics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    # Pagination broadens coverage beyond the original single popularity page.
    # Market IDs deduplicate records when the volume ranking moves during paging.
    for page in range(pages):
        response = await client.get(
            GAMMA,
            params={
                "active": "true",
                "closed": "false",
                "limit": 100,
                "offset": page * 100,
                "order": "volume24hr",
                "ascending": "false",
            },
        )
        response.raise_for_status()
        rows = response.json()
        counts["discovery_rows"] += len(rows)
        for raw in rows:
            try:
                pair = parse_market(raw)
                candidates[pair["market_id"]] = pair
            except (KeyError, ValueError, TypeError):
                counts["discovery_unsupported"] += 1
        if len(rows) < 100:
            break
    counts["discovery_eligible"] = len(candidates)
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

    selected: list[dict[str, Any]] = []
    event_counts: Counter[str] = Counter()
    pool = list(candidates.values())
    for offset in range(0, len(pool), 20):
        validated = await asyncio.gather(*(validate(p) for p in pool[offset : offset + 20]))
        for pair in validated:
            if pair is None:
                counts["discovery_validation_failed"] += 1
            elif event_counts[pair["event_id"]] < per_event and len(selected) < limit:
                selected.append(pair)
                event_counts[pair["event_id"]] += 1
        if len(selected) == limit:
            break
    if diagnostics is not None:
        diagnostics.update(counts)
        diagnostics["selected_markets"] = len(selected)
        diagnostics["selected_events"] = len(event_counts)
    return selected
