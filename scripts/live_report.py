"""Record a real feed observation without injecting quotes or forcing trades."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.schemas.domain import now  # noqa: E402


async def main() -> None:
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=20) as client:

        async def get(path: str):
            response = await client.get(path)
            response.raise_for_status()
            return response.json()

        first = await get("/metrics")
        assert first["mode"] == "live" and first["execution_provider"] == "paper"
        async with connect("ws://localhost:8000/ws/opportunities", open_timeout=10) as ws:
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
            assert event["type"] == "opportunities"
        await asyncio.sleep(10)
        final = await get("/metrics")
        assert final["snapshots_processed"] > first["snapshots_processed"]
        markets, opportunities, trades = (
            await get("/markets"),
            await get("/opportunities"),
            await get("/trades"),
        )
        assert markets and all(
            s["timestamp_source"] != "synthetic" for m in markets for s in m["snapshots"]
        )
        dashboard = await client.get("http://localhost:3000")
        dashboard.raise_for_status()
        report = {
            "observed_at": now().isoformat(),
            "scope": "Public real-time data with paper execution. No synthetic input or forced trade.",
            "observation_seconds": final["uptime_seconds"] - first["uptime_seconds"],
            "snapshots_during_observation": final["snapshots_processed"]
            - first["snapshots_processed"],
            "websocket_received": True,
            "dashboard_http_status": dashboard.status_code,
            "metrics": final,
            "markets": [{"id": m["id"], "title": m["title"], "venue": m["venue"]} for m in markets],
            "decisions": [
                {
                    "market": o["market"],
                    "gross_edge": o["gross_edge"],
                    "net_edge": o["net_edge"],
                    "status": o["status"],
                    "rejection_reason": o["rejection_reason"],
                }
                for o in opportunities
            ],
            "paper_trades_recorded": len(trades),
        }
        await asyncio.to_thread(
            Path("docs/live-run.json").write_text, json.dumps(report, indent=2) + "\n"
        )
        print(
            json.dumps(
                {k: v for k, v in report.items() if k not in ("markets", "decisions")}, indent=2
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
