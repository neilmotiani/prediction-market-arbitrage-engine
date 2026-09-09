# Architecture

## Boundaries

`MarketSnapshot` is an immutable Pydantic value with venue-qualified identity, outcome, venue/receipt timestamps, depth, volume, computed best prices and ask liquidity. `OrderBook` combines duplicate prices, sorts sides, and returns explicit partial fills. Financial calculations use `Decimal`; JSON encodes decimals as strings. The browser converts them to numbers for display only.

`VenueConnector.stream()` is an async iterator of snapshot batches. Mock batches synchronize both outcomes. Polymarket uses bounded concurrent public REST requests plus a public WebSocket refresh trigger. Kalshi retrieves public REST books sequentially, marking its timestamp as receipt time. The runtime retries failed connectors with capped exponential backoff and structured error logs; cancellation propagates cleanly. No connector submits orders.

`ContractMatcher` proposes cross-venue candidates using normalized dates, token overlap, and sequence similarity. Numeric mismatches score zero. Executability separately requires a validated mapping and equal resolution keys. Manual overrides can bypass title similarity, never the three explicit equivalence attestations.

`ArbitrageEngine` evaluates same-market and cross-venue YES/NO combinations. `PositionSizer` binary-searches the affordable integer size with the actual cost model. `ExecutionModel` walks depth, computes fee rounding and cost reserves. Complete fills then pass liquidity, slippage, freshness, mapping, and minimum-edge checks. Partial fills remain visible without a false paired P&L.

`PaperExecutionProvider` re-evaluates current books and available capital, commits a paired trade and both simulated orders to PostgreSQL, then updates its in-memory ledger. It reserves both snapshot identities to prevent reuse, including after restore. Full-pair cost counts against every involved market's cap, deliberately conservative for cross-venue pairs. Settlement consumes a mock outcome for **each** venue contract and computes payouts independently.

`ResearchRuntime` owns a single asyncio lock spanning feed mutation and paper execution. This prevents two simultaneous API calls from overspending the same capital or consuming the same snapshots. Database commits precede in-memory trade updates. A crash after commit is recovered by loading persisted trades at startup. A failed commit leaves the paper ledger unchanged.

## Persistence

| Table | Key data |
| --- | --- |
| markets | Venue-qualified ID; title and resolution metadata |
| market_snapshots | UUID, indexed market key + timestamp; normalized depth JSON |
| opportunities | UUID + timestamp; prices, costs, statuses, reason, and input snapshot audit |
| simulated_trades | Trade UUID + timestamp; both filled orders, fingerprints, cost, expected/realized P&L |
| contract_mappings | Stable sorted key pair; reviewer, evidence, equivalence flags, resolution key |
| system_metrics | UUID + timestamp; counters, timing, connections, paper capital |

The six tables share a typed record envelope and JSON payload. Domain/API validation resides in the schemas. PostgreSQL is the Compose persistence layer. SQLite exercises the same SQLAlchemy interfaces in tests and standalone development. A 24-hour time-based retention policy bounds observation tables; trades/mappings never auto-expire. Startup `create_all` bootstraps an empty schema. Add Alembic before changing deployed columns; it does not migrate existing schemas.

## API and dashboard

REST serves markets, recent history, current/historical opportunities, trade history, metrics, mappings, and explicit simulation actions. Current opportunities are re-evaluated on reads, preserving their detection IDs and timestamps while invalidating stale or consumed books. Historical payloads are immutable decision records.

The WebSocket stream sends snapshots and heartbeats through two-slot subscriber queues. When full, the oldest message is discarded. REST polling resynchronizes the dashboard and serves as a reconnect fallback. No promise of at-least-once trade-event delivery is made; the database is authoritative.

The Next.js client renders the current research state, opportunity inspection, Recharts book/history panels, portfolio settlement, and diagnostics. Radix supplies focus management, Escape dismissal, and semantic dialog labels. All errors have visible states. HTML server rendering succeeds without a running backend; data appears after browser API requests connect.

## Deployment constraints

Run **one Uvicorn worker**. An in-memory mutation lock is not safe across multiple workers/replicas. Horizontal scaling needs a separate feed service, durable pub/sub, and transactionally locked portfolio state. No Redis is included because it would not solve that boundary alone.

Containers run as non-root users; PostgreSQL is private to the Compose network and only application loopback ports are published. CORS/WS origins default to localhost:3000. This is an unauthenticated local research tool. Do not expose write endpoints publicly without authentication, authorization, rate limits, and audit controls.

Metrics are counters since process startup, with persisted samples for research. Found/rejected totals count evaluation events, not unique economic opportunities. `data_latency_ms` measures book timestamp age at ingestion; `detection_latency_ms` times a full scan without DB I/O. `/health` checks database liveness and separately reports feed readiness/state.
