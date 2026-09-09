# Read-only live data

`MODE=mock` works offline. `MODE=live` starts only explicitly configured venue feeds; an empty configuration reports a healthy API with `feed_ready=false`. It never silently substitutes synthetic observations.

## Polymarket

Discover binary markets using the [Gamma markets API](https://docs.polymarket.com/market-data/discover-markets). Inspect `outcomes`, `conditionId`, and `clobTokenIds`; confirm that the tokens truly represent exhaustive YES/NO outcomes for the same condition. Multi-outcome and negative-risk conversions are outside this model.

```dotenv
MODE=live
POLYMARKET_TOKEN_PAIRS=[{"market_id":"<conditionId>","title":"<question>","yes_token":"<Yes token id>","no_token":"<No token id>","resolution_key":"<reviewed settlement definition>"}]
POLYMARKET_WEBSOCKET=true
```

The connector fetches public CLOB `/book?token_id=...` data, validates returned condition/token identities, and preserves venue timestamps. A public market WebSocket subscribes to configured assets and sends the documented application heartbeat. Book/price events trigger throttled **full REST refreshes**; it does not pretend to safely reconstruct depth from an unsequenced delta stream. Periodic refreshes continue on an otherwise idle connected socket. Set `POLYMARKET_WEBSOCKET=false` for explicit REST polling if a network blocks WebSockets.

[Official real-time protocol](https://docs.polymarket.com/market-data/realtime-data) · [Official price/book concepts](https://docs.polymarket.com/market-data/prices-order-books).

## Kalshi

```dotenv
MODE=live
KALSHI_TICKERS=["<active market ticker>"]
KALSHI_RESOLUTION_KEYS={"<active market ticker>":"<reviewed settlement definition>"}
```

The adapter attempts unauthenticated GET market metadata and order books at `https://external-api.kalshi.com/trade-api/v2`. Current `orderbook_fp.yes_dollars/no_dollars` fixed-point strings and legacy integer-cent books are supported. YES ask = 1 − NO bid, and vice versa, with the opposite bid's size preserved. The API supplies bid books, not independent ask arrays. [Official order-book reference](https://docs.kalshi.com/api-reference/market/get-market-orderbook).

Kalshi snapshots use receipt time because the supported response lacks an authoritative book timestamp. This bounds local age, not upstream quote age. Availability or authentication requirements can change; 401/403/429 responses appear as connector errors with backoff. The project does not implement authenticated Kalshi WebSockets or trading credentials.

## Cross-venue review

Configure the same resolution key on truly equivalent contracts, then post a mapping with a named reviewer, evidence, and explicit same-payout / same-resolution / same-outcome attestations. The API requires both monitored contracts and matching configured keys. JSON mappings in `docs/contract-mappings.json` are synthetic fixtures only and never approve real contracts.

## Fee safety and verification

Live data always sets `fee_verified=false`. Therefore a live gross discrepancy remains theoretical with `unverified_live_fee_schedule`, even if an illustrative net calculation is positive. Adopting live fees requires a market-specific verified fee provider and tests, not merely switching an environment flag. No real-money provider exists.

Run `uv run python scripts/live_smoke.py` for optional public discovery, REST parsing, and Polymarket WebSocket/refresh verification. This is excluded from offline CI. The local implementation run successfully retrieved both venues' public books and a Polymarket WebSocket-triggered refresh; that observation is not a guarantee of future access.
