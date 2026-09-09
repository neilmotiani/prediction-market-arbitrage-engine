"use client";
import { useState } from "react";
import {
  ArrowDownUp,
  ArrowRight,
  CircleDot,
  Radio,
  Search,
} from "lucide-react";
import { money, pct, time } from "@/lib/api";
import type { Opportunity, Metrics } from "@/lib/types";
export function OpportunityTable({
  ops,
  metrics,
  loaded,
  setSelected,
}: {
  ops: Opportunity[];
  metrics: Metrics | null;
  loaded: boolean;
  setSelected: (op: Opportunity) => void;
}) {
  const [filter, setFilter] = useState("all"),
    [search, setSearch] = useState("");
  const filtered = ops
    .filter(
      (o) =>
        (filter === "all" || o.status === filter) &&
        o.market.toLowerCase().includes(search.toLowerCase()),
    )
    .sort((a, b) => Number(b.net_edge ?? -10) - Number(a.net_edge ?? -10));
  return (
    <section className="panel opportunities">
      <div className="panel-heading">
        <div>
          <h2>
            <span className="heading-dot" /> Opportunity monitor{" "}
            <span className="count">{ops.length}</span>
          </h2>
          <p>Paired-share edges · $1 combined payout · costs included</p>
        </div>
        <label className="search">
          <Search size={15} />
          <input
            aria-label="Search markets"
            placeholder="Search markets…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
      </div>
      <div className="table-toolbar">
        <div className="filter-tabs" aria-label="Filter opportunity status">
          {["all", "executable", "theoretical", "rejected"].map((f) => (
            <button
              key={f}
              aria-pressed={filter === f}
              className={filter === f ? "selected" : ""}
              onClick={() => setFilter(f)}
            >
              {f === "all" ? "All checks" : f[0].toUpperCase() + f.slice(1)}
              <span>
                {f === "all"
                  ? ops.length
                  : ops.filter((o) => o.status === f).length}
              </span>
            </button>
          ))}
        </div>
        <span className="small muted">
          <Radio size={13} />{" "}
          {metrics?.last_update
            ? `Updated ${time(metrics.last_update)}`
            : "Connecting…"}
        </span>
      </div>
      <div className="table-scroll">
        <table className="op-table">
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Strategy</th>
              <th>Venue(s)</th>
              <th>Market</th>
              <th>Gross edge</th>
              <th>Net edge ↓</th>
              <th>Avail. size</th>
              <th>Exp. profit</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((o) => (
              <tr key={o.id}>
                <td className="mono muted">{time(o.timestamp)}</td>
                <td>
                  <span className="strategy">
                    <ArrowDownUp size={12} />
                    {o.strategy_type === "complement"
                      ? "Single market"
                      : "Cross venue"}
                  </span>
                </td>
                <td>
                  <div className="venue-list">
                    {o.venue.split(" / ").map((v) => (
                      <span key={v}>
                        <i className={v === "kalshi" ? "venue-k" : "venue-p"} />
                        {v === "kalshi" ? "Kalshi" : "Polymarket"}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="market-cell">
                  <button
                    className="market-button"
                    onClick={() => setSelected(o)}
                  >
                    {o.market}
                    <ArrowRight size={13} />
                  </button>
                </td>
                <td
                  className={`mono ${Number(o.gross_edge) > 0 ? "positive" : "muted"}`}
                >
                  {pct(o.gross_edge)}
                </td>
                <td
                  className={`mono strong ${o.net_edge !== null && Number(o.net_edge) > 0 ? "positive" : o.net_edge !== null ? "negative" : "muted"}`}
                >
                  {pct(o.net_edge)}
                </td>
                <td className="mono">
                  {Number(o.available_size).toLocaleString()}
                </td>
                <td
                  className={`mono ${Number(o.expected_profit) > 0 ? "positive" : "muted"}`}
                >
                  {money(o.expected_profit)}
                </td>
                <td>
                  <button
                    className={`badge ${o.status}`}
                    onClick={() => setSelected(o)}
                  >
                    {o.status === "executable" && (
                      <span className="status-dot" />
                    )}
                    {o.status}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!filtered.length && (
          <div className="empty">
            {loaded
              ? "No opportunities match this filter."
              : "Connecting to the market research engine…"}
          </div>
        )}
      </div>
      <div className="table-footer">
        <span>
          <CircleDot size={12} /> Executable = passes simulation constraints;
          fills and settlement remain uncertain.
        </span>
        <span>
          {filtered.length} of {ops.length} checks
        </span>
      </div>
    </section>
  );
}
