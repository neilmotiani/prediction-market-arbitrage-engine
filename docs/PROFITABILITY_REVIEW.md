# Profitability investigation — September 14, 2026

The absence of paper profits was primarily an absence of positive gross prices in the monitored books. It was not evidence that a fee threshold was incorrectly hiding thousands of profitable trades. The investigation also identified fixable coverage, refresh, and sizing limitations.

## Evidence from the running system before changes

A read-only PostgreSQL aggregation returned 6,256 retained checks between 15:03:24 and 18:18:58 UTC on September 14. None had positive gross edge; none was executable. Among fully quoted pairs, the best gross edge was −0.001 per paired share and the best modeled net edge was approximately −0.003404. There were no persisted paper trades.

The simultaneous API observation showed 12 monitored markets, one venue, 80,638 checks in the current process, zero positive gross observations, and 36 connector/ingestion errors. These process counters cover a different window from retained database rows and must not be added together.

| Retained rejection combination | Checks |
| --- | ---: |
| No gross edge; net edge below threshold | 4,754 |
| Missing asks | 587 |
| Stale data; missing asks | 506 |
| Stale data; no gross edge; net edge below threshold | 372 |
| Asynchronous legs; no gross edge; net edge below threshold | 18 |
| No gross edge; net edge below threshold; slippage limit | 11 |
| Asynchronous legs; missing asks | 4 |
| Stale data; asynchronous legs; no gross edge; net edge below threshold | 3 |
| Stale data; asynchronous legs; missing asks | 1 |

All 5,158 checks with both asks failed the gross-price test. Removing fees or the minimum net-edge threshold cannot turn a pair already costing more than its $1 payout into a profitable purchase. Staleness was a secondary issue in this window, not the explanation for a hidden positive edge.

## Market structure and research

Polymarket's exchange supports complementary, mint, and merge matching paths. Complementary sell orders can be matched through merging tokens into collateral. A publicly visible YES+NO discount is therefore subject to enforcement within the venue as well as competition from other traders. This is a reason to expect short-lived or absent simple complement opportunities, not a proof that all such opportunities are impossible. [Official exchange design](https://github.com/Polymarket/ctf-exchange-v2/blob/main/README.md).

A 2026 study of 173 NBA games and more than 75 million book snapshots reported only seven executable single-market episodes, with median duration 3.6 seconds. Its combinatorial opportunities were more frequent but often constrained to small quantities. Those results apply to that study's sample; they do not predict returns in this project's universe. They support investigating refresh speed and small executable sizes. [Cheng, Yang and Zou, *Arbitrage Analysis in Polymarket NBA Markets*](https://arxiv.org/abs/2605.00864).

Research on negative-risk markets distinguishes a terminal payoff identity from transformations actually available before settlement. This matters when considering a future multi-outcome strategy: a basket that sums to $1 at settlement is not automatically convertible to $1 immediately. [Gebele, Mutzel and Matthes, *Executable Arbitrage and Market Efficiency in Prediction Markets*](https://arxiv.org/abs/2608.00666).

## Implementation findings and changes

1. **The live preset was a single-venue complement scanner.** Kalshi tickers were empty and no approved live cross-venue pairs were active. The cross-venue engine exists, but synthetic mappings do not provide live coverage. The dashboard now states the number of cross-venue pairs actually checked.
2. **The universe was small and concentrated.** Discovery took 12 ordinary binary contracts from one popularity page. The new preset reads five pages, targets 60 markets, limits exposure to two contracts per event, and excludes markets past their scheduled end. It retains identity, binary-outcome, negative-risk, and fee validation.
3. **Discovery bypassed the venue WebSocket.** The old branch always polled, regardless of the WebSocket setting. Discovered tokens now subscribe to public events. Events coalesce into a bounded set of markets needing refresh; full books are fetched in batches. REST remains active during socket outages, and the entire universe refreshes periodically. No unsequenced depth deltas are treated as authoritative books.
4. **Sizing maximized affordability, not profit.** A 100-share request could walk past a profitable first level or fail depth even when 10–15 shares were executable. `SIZING_POLICY=profit` searches fully fillable integer quantities up to the requested cap, maximizing modeled dollar profit while retaining fee, capital, minimum order, minimum edge, liquidity, and slippage checks. Fixed costs and fee rounding remain in every size evaluation. The deterministic mock preset keeps its original requested-size policy for reproducibility.
5. **Transient or older books could confuse monitoring.** Positive gross pairs now receive another complete REST read before entering the engine. Older snapshots cannot overwrite newer state. Partial refreshes trigger only affected pair checks and preserve other displayed decisions.
6. **The dashboard did not explain zero trades.** It now shows quoted pairs → positive gross → positive net → executable, rejection reasons, closest net estimates, actual venue transport, discovery coverage, and book errors. A connected dashboard socket is not presented as proof of a connected venue socket.

Protocol references: [official market pagination](https://docs.polymarket.com/api-reference/markets/list-markets), [market WebSocket messages](https://docs.polymarket.com/api-reference/wss/market), and the public `/books` request/response schema in [Polymarket's OpenAPI specification](https://docs.polymarket.com/api-spec/clob-openapi.yaml). The timestamp field is documented as the book snapshot timestamp; freshness limits were retained rather than reinterpreting every HTTP receipt as a new quote.

## Verification after changes

The one-minute read-only comparison in [research-scan.json](research-scan.json) observed:

| Measurement | Result |
| --- | ---: |
| Discovery rows inspected | 500 |
| Eligible ordinary binary candidates | 128 |
| Markets / events monitored | 60 / 45 |
| Venue WebSocket events received | 5,269 |
| Complete book refresh batches | 70 |
| Outcome snapshots / pair checks | 3,380 / 1,690 |
| Book errors | 0 |
| Positive gross checks | 0 |
| Executable checks, requested / profit sizing | 0 / 0 |

The broader scan worked but did not find a profitable live pair in this interval. The report uses identical risk assumptions for both sizing policies and uncommitted paper capital to isolate sizing behavior. Counts are observations, not unique arbitrage episodes or a backtest.

Separately, automated regression tests demonstrate that the new policy recovers a 10-share, $1 expected-profit pair from a book where the old 100-share request fails. Other tests cover shallow paired depth, fixed costs, minimum order size, slippage, exhaustive feasible-profit comparisons, pagination, event concentration, batch identity, positive-quote rechecks, WebSocket coalescing, incremental scans, and out-of-order rejection. Test prices are synthetic and are not included in live results.

To repeat the public comparison without placing even paper orders:

```bash
uv run python scripts/research_scan.py --seconds 60 --markets 60
```

## Limits that remain

These changes correct missed-size behavior and improve observation coverage; they do not establish a profitable strategy. The live preset still monitors ordinary binary complements on Polymarket. Independently reviewed cross-venue mappings with verified costs on both venues, or formally validated multi-outcome/related-market payoff constraints, would constitute additional strategies. Increasing the number of single-venue checks is not a substitute for implementing and validating those strategies. Queue competition, actual independent leg fills, and market impact are not reproduced by atomic paper execution.
