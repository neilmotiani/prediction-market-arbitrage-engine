export type Level = { price: string; size: string };
export type Snapshot = {
  venue: string;
  market_id: string;
  title: string;
  outcome: "YES" | "NO";
  timestamp: string;
  best_bid: string | null;
  best_ask: string | null;
  bids: Level[];
  asks: Level[];
  liquidity: string;
  fee_schedule?: {
    formula: string;
    rate: string;
    source: string;
    verified_at: string;
  } | null;
};
export type Estimate = {
  fees: string;
  network_cost: string;
  latency_reserve: string;
  total_cost: string;
  fill: {
    average_price: string | null;
    filled_size: string;
    notional: string;
    slippage: string;
    levels: Level[];
  };
};
export type Opportunity = {
  id: string;
  market: string;
  market_keys: string[];
  venue: string;
  strategy_type: string;
  yes_price: string | null;
  no_price: string | null;
  gross_edge: string;
  net_edge: string | null;
  estimated_fees: string;
  estimated_slippage: string;
  execution_costs: string;
  available_size: string;
  requested_size: string;
  expected_profit: string | null;
  timestamp: string;
  execution_score: number;
  status: "executable" | "theoretical" | "rejected";
  rejection_reason: string | null;
  estimates: Estimate[];
  snapshots: Snapshot[];
};
export type Market = {
  id: string;
  title: string;
  venue: string;
  snapshots: Snapshot[];
};
export type Trade = {
  id: string;
  timestamp: string;
  market: string;
  market_keys: string[];
  venue: string;
  quantity: string;
  total_cost: string;
  expected_pnl: string;
  realized_pnl: string | null;
  status: string;
  strategy_type: string;
};
export type Metrics = {
  mode: string;
  auto_paper_trade: boolean;
  auto_paper_fills: number;
  fee_verified_books: number;
  books_monitored: number;
  markets_monitored: number;
  opportunities_detected: number;
  executable_opportunities: number;
  simulated_pnl: string;
  expected_open_pnl: string;
  free_capital: string;
  market_updates_per_second: number;
  opportunities_checked_per_second: number;
  data_latency_ms: number;
  detection_latency_ms: number;
  api_errors: number;
  snapshots_processed: number;
  checks_total: number;
  rejected_opportunities: number;
  last_update: string | null;
  connections: Record<
    string,
    { state: string; error?: string; last_update?: string }
  >;
};
