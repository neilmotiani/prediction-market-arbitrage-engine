"""Compare sizing policies on actual public books; never inject quotes or trade."""

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import Settings  # noqa: E402
from app.connectors.polymarket.client import PolymarketConnector  # noqa: E402
from app.schemas.domain import now  # noqa: E402
from app.services.arbitrage import ArbitrageEngine  # noqa: E402
from app.services.contract_matching import ContractMatcher  # noqa: E402
from app.services.diagnostics import scan_diagnostics  # noqa: E402


async def run(seconds: float, markets: int, output: Path) -> None:
    settings = Settings(
        _env_file=None,
        mode="live",
        live_auto_discover=True,
        live_market_limit=markets,
        sizing_policy="profit",
    )
    connector = PolymarketConnector(settings)
    adaptive = ArbitrageEngine(settings, ContractMatcher(0.85, []))
    requested = ArbitrageEngine(
        settings.model_copy(update={"sizing_policy": "requested"}), ContractMatcher(0.85, [])
    )
    counts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    books, latest, recovered = {}, {}, []
    seen_markets: set[str] = set()
    started = perf_counter()
    stream = connector.stream()
    try:
        # Discovery time is included. No unbounded wait on a failed public feed.
        async with asyncio.timeout(seconds):
            async for batch in stream:
                books.update({s.book_key: s for s in batch})
                touched = {s.key for s in batch}
                seen_markets.update(touched)
                old = requested.scan(list(books.values()), changed_keys=touched)
                new = adaptive.scan(list(books.values()), changed_keys=touched)
                counts["batches"] += 1
                counts["snapshots"] += len(batch)
                counts["checks"] += len(new)
                counts["positive_gross"] += sum(o.gross_edge > 0 for o in new)
                counts["requested_policy_executable"] += sum(o.status == "executable" for o in old)
                counts["profit_policy_executable"] += sum(o.status == "executable" for o in new)
                for before, after in zip(old, new, strict=True):
                    latest[tuple(after.market_keys)] = after
                    reasons.update(filter(None, (after.rejection_reason or "").split("; ")))
                    if after.status == "executable" and before.status != "executable":
                        counts["recovered_by_sizing"] += 1
                        if len(recovered) < 20:
                            recovered.append(
                                {
                                    "before": before.model_dump(mode="json"),
                                    "after": after.model_dump(mode="json"),
                                }
                            )
    except TimeoutError:
        pass
    finally:
        await stream.aclose()
    if not books:
        raise RuntimeError("No live books observed; increase duration or check public feed access")
    report = {
        "observed_at": now().isoformat(),
        "duration_seconds": round(perf_counter() - started, 3),
        "method": "Read-only real-feed comparison; same risk/fee assumptions and uncommitted capital for both sizing policies. Counts are checks, not distinct trading episodes. No orders submitted.",
        "settings": settings.model_dump(
            mode="json", exclude={"database_url", "cors_origins", "mapping_file"}
        ),
        "markets_observed": len(seen_markets),
        "counts": dict(counts),
        "connector": connector.diagnostics,
        "rejections": dict(reasons.most_common()),
        "latest_scan": scan_diagnostics(list(latest.values())),
        "recovered_examples": recovered,
    }
    await asyncio.to_thread(output.write_text, json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k not in ("settings", "recovered_examples", "latest_scan")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--markets", type=int, default=60)
    parser.add_argument("--output", type=Path, default=Path("docs/research-scan.json"))
    args = parser.parse_args()
    asyncio.run(run(args.seconds, args.markets, args.output))
