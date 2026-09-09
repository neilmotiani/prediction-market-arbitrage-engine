# Execution model

## Book walking

`estimate_fill("buy", quantity)` sorts asks ascending, aggregates duplicate prices, consumes each level to its available size, and returns requested size, filled size, average price, notional, slippage, and the exact levels consumed. Sell estimates consume bids descending. `available_depth("buy", max_price)` sums asks no higher than the limit; for sell the price parameter is the minimum acceptable bid. Inputs reject nonfinite prices and nonpositive sizes.

For 50 shares at $0.45 and 50 at $0.50, a purchase of 80 shares uses 50 at $0.45 plus 30 at $0.50: $37.50 notional, $0.46875 average, $0.01875/share slippage. A request for 120 fills 100 and is explicitly partial.

## Cost policies

- Polymarket-like research fee: `notional * FEE_BPS / 10000`.
- Kalshi-like research fee: `ceil_to_cent(sum(KALSHI_FEE_COEFFICIENT * size * price * (1-price)))`, rounded once per leg. This approximates a common fee shape; market-specific multipliers, fee-free markets, and actual per-fill rounding can differ.
- Network cost: configured fixed USD cost **per Polymarket leg**. It is not asserted to be an actual gas charge on every matched trade.
- Latency reserve: `filled_size * LATENCY_BUFFER_BPS / 10000` per leg.
- Total modeled outlay = notional + fees + network + latency reserve. Slippage is already inside notional.

The two policies above are mock-mode assumptions, not universal venue fees. Automatically discovered live Polymarket books use the verified metadata model below. Other live feeds with unverified fees fail closed. Real execution is absent.

## Risk and sizing

Integer-size binary search evaluates actual leg cost at each trial size. The budget is the minimum of the per-opportunity cap, remaining portfolio cash, and every involved market's remaining cap. Each cross-venue market conservatively receives the full pair's committed cost. Sizes are revalidated under the runtime lock before execution.

After sizing, both books must fill the selected quantity. Minimum ask liquidity is **notional USD per leg**, not open interest or reported volume. Combined VWAP slippage must stay below the configured threshold. Default minimum net edge is $0.005 per paired share.

This is an affordable-size policy, not an exhaustive profit-maximization solver. If the requested size exceeds depth, the engine exposes the available quantity and rejects incomplete pairing; it does not declare a smaller partial hedge executable. Optional Kelly-style sizing was omitted: a research Kelly calculation would require a defensible probability model and would be illustrative, not financial advice.

## Paper ledger and settlement

Orders are immediate fill-or-kill paired simulations. There is no resting queue to cancel; `cancel_order` returns false for an already filled known order. The provider stores two fills, exact consumed levels, expected P&L, total modeled cost, and book fingerprints in one persisted trade record. It reserves whole snapshots conservatively, so multiple candidates cannot reuse their depth during the same update. Fresh synthetic ticks are independent replenishment, not an impact model.

Settlement requires explicit mock resolutions for every venue market in a trade. Payout is computed order by order. Modeled network and latency reserves are treated as spent for conservative simulated realized P&L; there is no actual-money accounting claim. A repeated settlement is rejected. Open positions and settled P&L restore from PostgreSQL after restart.

Real markets introduce adverse selection, competition, partial fills, independently resolving venues, collateral/transfer constraints, and non-atomic legs. These are documented limits, not hidden inside a high confidence score.

## Live Polymarket fee model

Automatically discovered contracts attach a time-stamped Gamma fee schedule and source URL. The supported quadratic fee is `gross_quantity * rate * p * (1-p)`. Buy fees are collected in shares, so a gross book level of `C` shares delivers `C * (1 - rate*(1-p))` net shares. The execution model walks those net capacities. For `q` net shares at one price, cash required is `q*p / (1 - rate*(1-p))`.

The estimate splits that cash into net-share notional `q*p` and the additional fee/gross-up reserve. Reported fill quantities and level quantities are **net deliverable shares** in this live model; the original venue snapshot is stored alongside each order so gross depth remains auditable. The aggregate reserve rounds upward to $0.00001. This is a conservative continuous-share estimate, not an exact reproduction of venue per-match rounding, minimum cash order increments, or queue fills. Mock economics are unchanged.

Live book fingerprints aggregate equal-price asks and normalize decimal representation. Identical consumed depth remains unavailable across restarts, even if receipt timestamps change. A per-market cooldown guards rapid changed-book reuse. Live settlement uses stored final venue evidence; unsupported or ambiguous outcomes do not release capital automatically.
