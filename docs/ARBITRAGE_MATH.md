# Arbitrage mathematics

## One-dollar complements

For q paired shares with matching settlement rules, YES + NO pays q dollars. The top-of-book theoretical edge is `1 - a_yes - a_no`. A positive number only proves an inequality between displayed quotes.

If a leg fills levels `(p_i, q_i)`, its notional is `sum(p_i*q_i)` and its VWAP is notional / filled quantity. The pair must fill the **same** q on both sides. Gross edge minus combined VWAP slippage, per-share fees, and per-share execution reserves equals net edge. Buying at the ask already includes the bid/ask spread relative to mid; an additional spread deduction would double count it.

```
S(q) = VWAP_yes(q) - ask_yes + VWAP_no(q) - ask_no
F(q) = (fees_yes(q) + fees_no(q)) / q
X(q) = (network_yes + network_no + latency_yes + latency_no) / q
net_edge(q) = gross_edge - S(q) - F(q) - X(q)
expected_profit(q) = q * net_edge(q)
```

Execution score is a freshness/readiness heuristic, not a calibrated probability. No Kelly allocation is used.

## Cross-venue pair

A YES at $0.43 and B NO at $0.52 give $0.05 gross edge. Under the demo assumptions for 100 shares:

- Purchase notional = $95.
- A notional fee at 20 bps = $0.086.
- B quadratic research fee = ceil-to-cent(0.07 × 100 × 0.52 × 0.48) = $1.75.
- A network reserve = $0.02.
- Latency reserves = $0.20 total.
- Total modeled outlay = $97.056; expected profit = $2.944; net edge = $0.02944/share.

There must be a reviewed mapping between A and B with the same outcome definition, payout, and resolution rules. A similarity threshold is only candidate discovery. If venue A resolves NO and B resolves YES, both purchased legs lose; settlement explicitly permits this test case rather than assuming a payout of $1.

## Rejections and units

No asks or partial fills mean no executable net/profit estimate. A positive gross edge blocked by fees, liquidity, capital, slippage, stale/future data, leg skew, unverified live fees, or mapping validation is classified theoretical. A nonpositive gross edge is rejected. Statuses expose machine-readable semicolon-separated reason codes.

Prices, fees, and profit are Decimal USD; sizes are Decimal shares at book level, with integer paired sizing. `estimated_fees`, `estimated_slippage`, `execution_costs`, and `net_edge` are USD per paired share. `expected_profit` and leg `total_cost` are USD totals. A UI value of 5% denotes $0.05 per $1 paired payout, not annualized return or return on invested capital.
