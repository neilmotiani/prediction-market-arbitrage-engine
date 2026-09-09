# Development and API guide

### Native development

Install Python 3.12, uv, and Node.js 22:

```bash
make install
make backend    # terminal 1; defaults to local SQLite when no .env exists
make frontend   # terminal 2
```

If a copied `.env` contains the Compose-oriented PostgreSQL URL, use `DATABASE_URL=sqlite+aiosqlite:///./research.db make backend`. `make dev` starts the full Docker stack. Run one backend worker: its feed, mutation lock, and exposure ledger are process-owned.

## Demo workflow

1. Open the dashboard and watch the three-second synthetic feed. Six venue markets produce eight checks per batch.
2. Inspect the Ethereum executable pair and its depth-adjusted cost waterfall. Its profitable window closes periodically.
3. Inspect Bitcoin's theoretical edge: fees remove it. Inspect GDP: the requested paired size exceeds depth.
4. Inspect the CPI cross-venue pair. A deliberately approved **synthetic** mapping connects the contracts.
5. Click **Run paper simulation**, or execute a specific opportunity from its drawer. Two filled paper orders are recorded.
6. Open **Paper portfolio** and choose **Resolve YES**. This supplies synthetic YES resolutions to all legs, releasing capital and recording realized simulation P&L.
7. Use **System health** to inspect feed status, scan latency, throughput, and errors.

```bash
make mock-data  # prints the five scenario families through the real quant engine
```

| Fixture | Scenario |
| --- | --- |
| Fed rate | No arbitrage |
| Bitcoin | Theoretical edge eliminated by fees |
| Ethereum | Executable complement, with depth slippage and closing windows |
| GDP | Insufficient depth and minimum liquidity failure |
| CPI / CPI-K | Cross-venue discrepancy, explicit synthetic equivalence mapping |

Paper positions do not auto-settle, and scans do not automatically accumulate trades. Simulation is an explicit action to make the capital and settlement workflow inspectable.

## API examples

```bash
curl http://localhost:8000/markets
curl 'http://localhost:8000/markets/polymarket:eth-edge'
curl 'http://localhost:8000/opportunities?min_edge=0.01'
curl 'http://localhost:8000/opportunities?history=true&limit=50'
curl http://localhost:8000/trades
curl http://localhost:8000/metrics
curl -X POST http://localhost:8000/simulation/run \
  -H 'Content-Type: application/json' -d '{}'
curl -X POST http://localhost:8000/contract-mappings \
  -H 'Content-Type: application/json' \
  -d '{"left_key":"polymarket:inflation","right_key":"kalshi:inflation-k","resolution_key":"demo:inflation","approved_by":"researcher","evidence":"Identical synthetic CPI fixtures with a one-dollar payout.","same_payout":true,"same_resolution":true,"same_outcome_definition":true}'
```

`POST /simulation/run` accepts `{"opportunity_id":"<current-id>"}` for a chosen pair. For settlement use `{"action":"settle","trade_id":"<id>","resolutions":{"polymarket:eth-edge":"YES"}}`; cross-venue trades require every venue-qualified market key. Unknown IDs, repeat execution, and failed revalidation return HTTP 409. A drawer may reference a prior scan; the stored audit record is recovered and current books are revalidated before filling. Invalid mappings return 422. A successful mapping records the reviewer's attestation; software cannot prove legal settlement equivalence.

WebSocket: `ws://localhost:8000/ws/opportunities`. Messages are `opportunities`, `trade`, or `heartbeat`, with current metrics. Slow consumers retain only recent updates. This is not a durable event replay API.

## Configuration and live data

All settings are listed in [.env.example](../.env.example); see [live-data setup](LIVE_DATA.md). Defaults include $100 per opportunity, $500 per venue contract, $10,000 paper capital, 0.5% minimum net edge, $20 ask liquidity per leg, 2% maximum combined slippage, and a 15-second quote age limit.

Live adapters deliberately report `unverified_live_fee_schedule`, so live candidates cannot become executable under unverified fee assumptions. No API keys, wallets, order-signing code, or real trading routes exist. Live data is not required for any mock demonstration or CI test.

See [recorded demo results](DEMO_RESULTS.md) for a reproducible run without a server.
