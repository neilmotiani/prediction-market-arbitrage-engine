"""CPU microbenchmark: JSON validation, candidate matching, depth/cost/sizing checks.

No network, persistence, dashboard, or settlement I/O is included.
"""

import argparse
import json
import platform
import sys
from pathlib import Path
from time import perf_counter, perf_counter_ns

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import Settings
from app.connectors.mock import demo_batch
from app.schemas.domain import ContractMapping, MarketSnapshot, now
from app.services.arbitrage import ArbitrageEngine
from app.services.contract_matching import ContractMatcher

ROOT = Path(__file__).resolve().parents[1]


def run(iterations: int) -> dict:
    settings = Settings(_env_file=None)
    mappings = [
        ContractMapping.model_validate(m)
        for m in json.loads((ROOT / "docs/contract-mappings.json").read_text())
    ]
    engine = ArbitrageEngine(settings, ContractMatcher(settings.match_threshold, mappings))
    payload = [s.model_dump_json() for s in demo_batch()]
    for _ in range(100):
        engine.scan([MarketSnapshot.model_validate_json(s) for s in payload])
    latencies: list[float] = []
    snapshots_count = checks = 0
    start = perf_counter()
    for _ in range(iterations):
        snapshots = [MarketSnapshot.model_validate_json(s) for s in payload]
        snapshots_count += len(snapshots)
        yeses = [s for s in snapshots if s.outcome == "YES"]
        nos = [s for s in snapshots if s.outcome == "NO"]
        pairs = [
            (y, n)
            for y in yeses
            for n in nos
            if y.key == n.key or (y.venue != n.venue and engine.matcher.candidate(y, n))
        ]
        for y, n in pairs:
            tick = perf_counter_ns()
            engine.evaluate(y, n)
            latencies.append((perf_counter_ns() - tick) / 1e6)
            checks += 1
    elapsed = perf_counter() - start
    series = pd.Series(latencies, name="detection_latency_ms")
    return {
        "measured_at": now().isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "scope": "Single-process CPU microbenchmark; normalization, matching, depth-aware evaluation and sizing; no I/O",
        "iterations": iterations,
        "snapshots": snapshots_count,
        "checks": checks,
        "book_levels_per_side": 4,
        "warmup_batches": 100,
        "elapsed_seconds": round(elapsed, 6),
        "snapshots_per_second": round(snapshots_count / elapsed, 2),
        "checks_per_second": round(checks / elapsed, 2),
        "p50_detection_ms": round(float(np.percentile(series, 50)), 6),
        "p95_detection_ms": round(float(np.percentile(series, 95)), 6),
        "mean_detection_ms": round(float(series.mean()), 6),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/benchmark.json")
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("iterations must be positive")
    results = run(args.iterations)
    args.output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
