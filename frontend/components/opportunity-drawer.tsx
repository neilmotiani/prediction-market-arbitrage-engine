"use client";
import * as Dialog from "@radix-ui/react-dialog";
import { X, ArrowRight, ShieldCheck } from "lucide-react";
import type { Opportunity } from "@/lib/types";
import { money, pct, time } from "@/lib/api";
export function OpportunityDrawer({
  op,
  close,
  execute,
  busy,
}: {
  op: Opportunity | null;
  close: () => void;
  execute: (op: Opportunity) => void;
  busy: boolean;
}) {
  return (
    <Dialog.Root
      open={!!op}
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="drawer-overlay" />
        <Dialog.Content className="drawer">
          {op && (
            <>
              <div className="eyebrow">
                EXECUTION ANALYSIS{" "}
                <span className={`badge ${op.status}`}>{op.status}</span>
              </div>
              <Dialog.Close
                className="icon-button drawer-close"
                aria-label="Close opportunity details"
              >
                <X size={20} />
              </Dialog.Close>
              <Dialog.Title className="drawer-title">{op.market}</Dialog.Title>
              <Dialog.Description className="muted">
                {op.venue} · Captured {time(op.timestamp)}. Execution rechecks
                current books.
              </Dialog.Description>
              <div className="leg-grid">
                {op.snapshots.map((s, i) => (
                  <div className="leg" key={s.outcome}>
                    <span className="eyebrow">BUY {s.outcome}</span>
                    <strong>
                      {s.best_ask === null
                        ? "—"
                        : `${(Number(s.best_ask) * 100).toFixed(2)}¢`}
                    </strong>
                    <span>{s.venue}</span>
                    <small>
                      Walked average:{" "}
                      {op.estimates[i]?.fill.average_price
                        ? `${(Number(op.estimates[i].fill.average_price) * 100).toFixed(3)}¢`
                        : "—"}
                    </small>
                  </div>
                ))}
              </div>
              <h3>
                Edge waterfall <small>per paired share</small>
              </h3>
              <div className="waterfall">
                {[
                  ["Theoretical edge", pct(op.gross_edge)],
                  ["Trading fees", `− ${pct(op.estimated_fees)}`],
                  ["Book slippage", `− ${pct(op.estimated_slippage)}`],
                  ["Network + latency reserve", `− ${pct(op.execution_costs)}`],
                  ["Net executable edge", pct(op.net_edge)],
                ].map(([k, v]) => (
                  <div key={k}>
                    <span>{k}</span>
                    <strong>{v}</strong>
                  </div>
                ))}
              </div>
              <div className="detail-stats">
                <div>
                  <span>Paired depth / size</span>
                  <strong>
                    {Number(op.available_size).toLocaleString()} shares
                  </strong>
                </div>
                <div>
                  <span>Expected profit</span>
                  <strong
                    className={Number(op.expected_profit) > 0 ? "positive" : ""}
                  >
                    {money(op.expected_profit)}
                  </strong>
                </div>
                <div>
                  <span>Execution readiness</span>
                  <strong>{(op.execution_score * 100).toFixed(0)} / 100</strong>
                </div>
              </div>
              {op.rejection_reason ? (
                <div className="rejection">
                  <strong>Execution blocked</strong>
                  {op.rejection_reason.split("; ").map((r) => (
                    <p key={r}>{r.replaceAll("_", " ")}</p>
                  ))}{" "}
                </div>
              ) : (
                <div className="execution-note">
                  <ShieldCheck size={18} />
                  <span>
                    Passes the configured depth, cost, freshness, mapping, and
                    capital checks. Readiness is a heuristic, not a success
                    probability.
                  </span>
                </div>
              )}
              <p className="muted small">
                Both legs fill atomically in this paper model. Real venues
                cannot guarantee simultaneous fills or identical settlement.
              </p>
              <button
                className="primary full"
                disabled={op.status !== "executable" || busy}
                onClick={() => execute(op)}
              >
                {busy ? "Revalidating…" : "Simulate paired trade"}
                <ArrowRight size={16} />
              </button>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
