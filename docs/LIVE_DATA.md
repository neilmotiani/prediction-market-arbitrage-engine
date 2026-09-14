# Real market data, simulated trades

## Start the live workspace

```bash
make live
```

Open http://localhost:3000. The banner reads **LIVE MARKET DATA · Automatic paper trading active**. No wallet, account credentials, or funds are required. The only execution implementation is `PaperExecutionProvider`.

This command builds and starts Docker services in the background using `docker-compose.live.yml`. It creates a separate `postgres-live-data` volume and `arbitrage_live` database. Your mock `postgres-data` volume is preserved. Database mode markers reject accidental mixing of mock and live ledgers.

```bash
make live-stop                  # stop without deleting data
make live                       # resume the live workspace
# Switch back to your preserved mock workspace:
docker compose up --build -d
```

The two workspaces use the same local ports and run one at a time. Containers restart after process failures and Docker restarts. Your computer must remain awake with Docker running and internet access; this is a local service, not a cloud deployment. Do not use `down -v` if you want to preserve research history.

## Discovery and ingestion

The live preset targets 60 ordinary binary Polymarket contracts from five pages of 100 markets ranked by reported 24-hour volume. Every five minutes it refreshes that universe, with at most two contracts per event. It requires explicit active/open/order-book-enabled status, distinct YES/NO tokens, and excludes negative-risk markets and contracts past their scheduled end. Each candidate is checked against the CLOB condition ID, token identities, order acceptance, and minimum order size. This is a sampled universe, not coverage of the entire venue.

Discovered tokens subscribe to public WebSocket market events. Changed markets coalesce into paired `/books` REST refreshes, no faster than `LIVE_REFRESH_INTERVAL` (default 0.5 seconds), with bounded requests. Full-universe refreshes continue approximately every three seconds plus request/processing time. A failed pair is omitted without discarding other valid pairs; complete feed failure triggers backoff. Positive gross pairs receive a second complete read. Venue timestamps are preserved, and older updates cannot overwrite newer books. A fresh HTTP response does **not** reset an old quote's timestamp. Stale or asynchronous legs remain blocked. Old universe entries expire from the in-memory monitor after ten minutes without updates; raw historical books and scan records have 24-hour retention.

The configured-token adapter also supports WebSocket-triggered full REST refreshes. REST polling remains active while the discovery socket reconnects. The system does not reconstruct authoritative depth from unsequenced deltas. The dashboard receives updates over the application's separate WebSocket. Connection diagnostics show both transports.

## Market-specific costs

Discovery reads Gamma's `feesEnabled` and `feeSchedule`. Only an explicit fee-free flag or a recognized rate/exponent/taker-only schedule qualifies as verified metadata. Missing or unsupported schedules block execution. Fee metadata older than twice the discovery interval also blocks execution. The legacy CLOB `base_fee` field is **not** interpreted as a universal basis-point charge.

For Polymarket buys, the model accounts for fees collected in shares by walking net deliverable depth and reserving the cash required to buy enough gross shares for equal net YES/NO quantities. See [the execution model](EXECUTION_MODEL.md). Network and latency reserves remain configurable conservative research assumptions.

Sources: [market metadata](https://docs.polymarket.com/market-data/market-details), [fee formula](https://docs.polymarket.com/trading/fees), [fee collection in shares](https://help.polymarket.com/en/articles/13364471-maker-rebates-program).

## Automatic paper execution and settlement

After each scan, executable pairs are ranked by expected dollar profit and revalidated under the execution lock against current books, available cash, and market exposure. Defaults are $10,000 research capital, $100 maximum per pair, $500 per market, and a $0.005 minimum net edge per paired share. The live preset enables automatic simulation; `AUTO_PAPER_TRADE=false` retains manual execution when configured outside the preset.

The live preset uses `SIZING_POLICY=profit`: requested size is a maximum, not a mandatory full order. The engine selects the fully fillable integer quantity with the highest modeled dollar profit that passes all sizing constraints. The default request caps this search at 100 shares. It does not lower fees or risk thresholds to obtain a trade. The dashboard execution funnel explains which checks are failing; [the profitability investigation](PROFITABILITY_REVIEW.md) documents the rationale and measured results.

Book fingerprints use normalized ask prices and quantities, not receipt times. An identical previously consumed book cannot be reused, even after a restart. A 60-second per-market cooldown additionally limits repeated fills on changing books. These are conservative liquidity safeguards, not a market-impact model. Paired execution remains an atomic simulation; no live orders are submitted.

Open positions reserve capital. A separate one-minute poll settles supported Polymarket positions only when Gamma reports a resolved, closed condition and CLOB reports the same closed condition with exactly one winning YES/NO token. It stores resolution evidence with each settlement. Proposed, ambiguous, cancelled/nonbinary, or unsupported resolutions remain pending. The API's mock resolution action is disabled in live mode. Simulated realized P&L is not account earnings.

No trades is a valid result: there must be positive edge **after** fees, depth, slippage, freshness, liquidity, and capital checks. Do not expect the deliberately profitable synthetic demo to predict live trading frequency or returns.

## Optional manually configured feeds

For a custom deployment, set `MODE=live` and a separate `DATABASE_URL`. Enable `LIVE_AUTO_DISCOVER=true`, or explicitly configure `POLYMARKET_TOKEN_PAIRS` / `KALSHI_TICKERS` as shown in `.env.example`. An empty configuration with discovery disabled reports `feed_ready=false`; it never substitutes mock data.

Explicit Polymarket pairs and Kalshi tickers remain read-only research feeds with unverified fees and therefore cannot execute paper trades. Kalshi supports current fixed-point and legacy cent order books, reconstructing asks from opposite outcome bids. Kalshi receipt timestamps do not establish upstream quote freshness. Authenticated venue sockets and real execution are absent.

Live cross-venue execution requires independent review of settlement definitions and a supported fee provider for each leg. The bundled mappings apply only to synthetic fixtures and never approve discovered live contracts.

## Reproduce a live observation

```bash
uv run python scripts/live_report.py
```

This verifies real snapshot provenance, increasing ingestion counters, a WebSocket message, and dashboard HTTP availability, then writes `docs/live-run.json`. It does not inject opportunities or force a trade. See [the recorded observation](LIVE_RUN.md). HTTP/build checks do not substitute for browser interaction testing.
