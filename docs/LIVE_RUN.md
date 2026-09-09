# Live feed observation — September 9, 2026

The Docker live workspace ran against public Polymarket data with automatic paper execution enabled. [Machine-readable evidence](live-run.json) was captured at 23:08:05 UTC using `scripts/live_report.py`.

| Observation | Result |
| --- | ---: |
| Runtime at capture | 512.6 seconds |
| Markets / outcome books | 12 / 24 |
| Books with verified fee metadata | 24 |
| Snapshots processed | 3,432 |
| Arbitrage checks | 1,716 |
| Positive gross-edge observations, cumulative | 1 |
| Rejected checks, cumulative | 1,716 |
| Paper trades | 0 |
| Simulated realized P&L | $0 |
| Additional snapshots in 10-second verification window | 48 |
| Dashboard HTTP / application WebSocket | 200 / received |

Every book was venue-sourced; no synthetic quote or profitable scenario was injected. The recorded decision rows include fees, negative net edges, and stale-quote rejections. No opportunity passed every execution constraint during this observation, so the paper ledger remained empty. This is an operational observation, not a backtest or evidence of trading profitability.

The automated fixture tests separately verify that qualifying live-format books produce persistent paper fills and that final resolution evidence settles those positions. Their synthetic prices are not included in these live results.

Repeat with `make live`, then `uv run python scripts/live_report.py`. Markets and counts change with time. The JSON report is overwritten by a new observation; this document describes the dated run above.
