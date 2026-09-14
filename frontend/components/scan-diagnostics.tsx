"use client";

import { pct } from "@/lib/api";
import type { Metrics } from "@/lib/types";

export function ScanDiagnostics({ metrics }: { metrics: Metrics | null }) {
  const scan = metrics?.scan_diagnostics;
  if (!scan) return null;
  return (
    <section
      className="panel system-panel"
      aria-label="Why trades are or are not qualifying"
    >
      <div className="panel-heading">
        <h2>Execution funnel</h2>
        <span className="subtle-badge">CURRENT BOOKS</span>
      </div>
      <div className="system-grid">
        {[
          ["Complete quotes", scan.quoted_pairs],
          ["Positive before costs", scan.positive_gross],
          ["Positive after costs", scan.positive_net],
          ["Pass all constraints", scan.executable],
        ].map(([label, value]) => (
          <div className="diagnostic" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      <p className="muted">
        {scan.positive_gross === 0
          ? "No quoted pair currently costs less than its $1 payout before costs. Lower fees alone cannot make these quotes profitable."
          : scan.executable === 0
            ? "Positive gross prices exist, but none currently passes every cost, depth, freshness, and portfolio check."
            : "Qualifying estimates still require current-book revalidation before a paper fill."}{" "}
        {scan.cross_venue_pairs === 0 &&
          "No cross-venue pairs are currently being checked."}
      </p>
      <details>
        <summary>Rejection reasons and closest net estimates</summary>
        <div className="system-grid">
          {Object.entries(scan.rejection_reasons).map(([reason, count]) => (
            <div className="diagnostic" key={reason}>
              <span>{reason.replaceAll("_", " ")}</span>
              <strong>{count}</strong>
            </div>
          ))}
        </div>
        <p className="muted">
          A check can have several rejection reasons. Counts are not additive.
        </p>
        {scan.closest_pairs.length > 0 && (
          <>
            <div className="panel-heading">
              <h2>Closest net estimates</h2>
              <span className="subtle-badge">AFTER COSTS</span>
            </div>
            {scan.closest_pairs.map((pair) => (
              <div className="diagnostic" key={pair.market}>
                <span>{pair.market}</span>
                <strong
                  className={
                    Number(pair.net_edge) > 0 ? "positive" : "negative"
                  }
                >
                  {pct(pair.net_edge)}
                </strong>
              </div>
            ))}
          </>
        )}
      </details>
    </section>
  );
}
