"""Read-only final resolution checks for live Polymarket paper positions."""

from typing import Any

import httpx

from app.connectors.polymarket.discovery import CLOB, GAMMA
from app.schemas.domain import now


def final_resolution(gamma: dict[str, Any], clob: dict[str, Any], condition: str) -> str | None:
    if (
        gamma.get("conditionId") != condition
        or clob.get("condition_id") != condition
        or gamma.get("closed") is not True
        or clob.get("closed") is not True
        or gamma.get("umaResolutionStatus") != "resolved"
    ):
        return None
    tokens = clob.get("tokens", [])
    if len(tokens) != 2 or {t.get("outcome", "").upper() for t in tokens} != {"YES", "NO"}:
        return None
    winners = [t["outcome"].upper() for t in tokens if t.get("winner") is True]
    return winners[0] if len(winners) == 1 else None


async def fetch_resolution(client: httpx.AsyncClient, key: str) -> dict[str, Any] | None:
    venue, condition = key.split(":", 1)
    if venue != "polymarket":
        return None
    response = await client.get(GAMMA, params={"condition_ids": condition})
    response.raise_for_status()
    markets = response.json()
    if len(markets) != 1 or markets[0].get("umaResolutionStatus") != "resolved":
        return None
    response = await client.get(f"{CLOB}/markets/{condition}")
    response.raise_for_status()
    clob = response.json()
    outcome = final_resolution(markets[0], clob, condition)
    if outcome is None:
        return None
    return {
        "outcome": outcome,
        "checked_at": now().isoformat(),
        "gamma_url": f"{GAMMA}/{markets[0]['id']}",
        "clob_url": f"{CLOB}/markets/{condition}",
        "gamma": markets[0],
        "clob": clob,
    }
