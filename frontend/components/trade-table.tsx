"use client";
import { Check, FlaskConical } from "lucide-react";
import { money, time } from "@/lib/api";
import type { Trade, Metrics } from "@/lib/types";
export function TradeTable({
  trades,
  metrics,
  busy,
  settle,
}: {
  trades: Trade[];
  metrics: Metrics | null;
  busy: boolean;
  settle: (trade: Trade) => void;
}) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Timestamp</th>
            <th>Market / venue</th>
            <th>Quantity</th>
            <th>Capital used</th>
            <th>Expected P&L</th>
            <th>Realized P&L</th>
            <th>Status</th>
            <th>Mock resolution</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr key={t.id}>
              <td className="mono muted">{time(t.timestamp)}</td>
              <td className="market-cell">
                {t.market}
                <small>{t.venue}</small>
              </td>
              <td className="mono">{t.quantity}</td>
              <td className="mono">{money(t.total_cost)}</td>
              <td className="mono positive">{money(t.expected_pnl)}</td>
              <td
                className={`mono ${Number(t.realized_pnl) >= 0 ? "positive" : "negative"}`}
              >
                {money(t.realized_pnl)}
              </td>
              <td>
                <span
                  className={`badge ${t.status === "settled" ? "executable" : "theoretical"}`}
                >
                  {t.status}
                </span>
              </td>
              <td>
                {t.status === "open" && metrics?.mode === "mock" ? (
                  <button
                    className="small-button"
                    disabled={busy}
                    onClick={() => settle(t)}
                  >
                    Resolve YES <Check size={12} />
                  </button>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!trades.length && (
        <div className="empty">
          <FlaskConical size={25} />
          <strong>No paper trades yet</strong>
          <span>
            Inspect an executable opportunity or run a simulation to record
            depth-aware fills.
          </span>
        </div>
      )}
    </div>
  );
}
