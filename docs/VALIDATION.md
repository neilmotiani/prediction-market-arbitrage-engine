# Validation record

Local environment: macOS 15.4.1 arm64, Python 3.12.11, Node 22.19, Docker via OrbStack. Container builds use Python 3.12 and Node 22. Date: 2026-09-09.

## Verified

- 44 passing tests: quant, order-book, cost, matching, risk, adapter, API/WebSocket, persistence, paper settlement, concurrent execution, stale reads, and commit-failure rollback.
- Backend statement coverage: 90% overall; arbitrage 97%, order book 96%, cost model and sizing 100%. Two upstream TestClient deprecation warnings are present.
- Ruff lint/format, ESLint, TypeScript, Prettier, and Next.js production compilation.
- `docker compose up --build -d --wait --wait-timeout 180`: PostgreSQL, backend, and frontend started successfully.
- PostgreSQL retained the initial smoke-test trade through the final backend container replacement; both smoke-test settlements were present in SQL.
- `scripts/smoke.py` against the final rebuilt Compose stack: six markets, all three classifications, successful paired paper fill, mock settlement, persisted history, dashboard HTTP 200 and expected HTML shell.
- `scripts/live_smoke.py`: Polymarket returned two normalized books with 328 levels during the run; its public WebSocket plus full-book refresh succeeded. Kalshi returned two normalized books.
- Actual CPU benchmark: see `benchmark.json` for counts, timing, environment, and methodology.

## Browser verification still required

Visual rendering, client hydration, chart behavior, keyboard interactions, responsive layout, and click-through flows have **not yet been verified in a browser**. HTTP and build checks do not substitute for these checks.

Open http://localhost:3000 and verify:

1. Cards and eight checks populate from the mock API; executable rows change as feed windows close.
2. Status filters and market search update rows.
3. Open a market's details; Tab stays in the drawer and Escape closes it.
4. Switch chart market and YES/NO depth; verify axes and historical observations.
5. Simulate a paired trade; inspect two persisted orders via `/trades`.
6. Resolve YES in Paper portfolio; realized P&L and free capital update.
7. Stop/restart the backend; verify visible error, reconnect, and persisted trades.
8. Check narrow/mobile layout and 200% zoom, then add a verified dashboard capture to the README.

## Reproducible scenario evidence

`make demo-report` captures all eight scan decisions, executes both eligible pairs, supplies mock resolutions, rejects a duplicate, and reloads the persisted ledger in an isolated SQLite database. See [DEMO_RESULTS.md](DEMO_RESULTS.md) and [demo-run.json](demo-run.json) for the recorded run. This is synthetic functional validation, not a historical backtest.
