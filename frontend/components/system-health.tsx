"use client";
import { Radio } from "lucide-react";
import { time } from "@/lib/api";
import type { Metrics } from "@/lib/types";
export function SystemHealth({
  metrics,
  connected,
}: {
  metrics: Metrics | null;
  connected: boolean;
}) {
  return (
    <section className="panel system-panel">
      <div className="panel-heading">
        <h2>Connection diagnostics</h2>
        <span className="subtle-badge">
          {connected ? "WEBSOCKET CONNECTED" : "HTTP FALLBACK"}
        </span>
      </div>
      <div className="system-grid">
        {Object.entries(metrics?.connections || {}).map(([name, c]) => (
          <div className="connection-card" key={name}>
            <Radio size={22} />
            <h3>{name}</h3>
            <span className={c.state === "connected" ? "positive" : "negative"}>
              {c.state}
            </span>
            <p>
              {c.last_update
                ? `Last batch ${time(c.last_update)}`
                : "Waiting for first batch"}
            </p>
            {c.error && <code>{c.error}</code>}
            {c.diagnostics && (
              <>
                <p>
                  Feed:{" "}
                  {String(c.diagnostics.transport ?? "—").replaceAll("_", " ")}
                </p>
                <p>
                  {c.diagnostics.selected_markets ?? "—"} markets across{" "}
                  {c.diagnostics.selected_events ?? "—"} events
                </p>
                <p>
                  {c.diagnostics.discovery_rows ?? "—"} discovery rows ·{" "}
                  {c.diagnostics.ws_events ?? 0} venue events
                </p>
                <p>
                  {c.diagnostics.book_errors ?? 0} book errors ·{" "}
                  {c.diagnostics.ws_reconnects ?? 0} socket reconnects
                </p>
              </>
            )}
          </div>
        ))}
        {!Object.keys(metrics?.connections || {}).length && (
          <p className="muted">
            No configured feeds. In live mode, provide explicit token pairs or
            market tickers.
          </p>
        )}
      </div>
      <div className="system-grid">
        {[
          ["Snapshots processed", metrics?.snapshots_processed],
          ["Automatic paper fills (session)", metrics?.auto_paper_fills],
          [
            "Books with fee metadata",
            `${metrics?.fee_verified_books ?? 0}/${metrics?.books_monitored ?? 0}`,
          ],
          ["Arbitrage checks", metrics?.checks_total],
          ["Rejected checks", metrics?.rejected_opportunities],
          ["Positive net checks (session)", metrics?.positive_net_checks_total],
          ["Sizing policy", metrics?.sizing_policy],
          ["Data age on receipt", `${metrics?.data_latency_ms ?? "—"} ms`],
          ["Last scan latency", `${metrics?.detection_latency_ms ?? "—"} ms`],
          ["Connector / ingestion errors", metrics?.api_errors],
        ].map(([label, value]) => (
          <div className="diagnostic" key={label as string}>
            <span>{label}</span>
            <strong>{value ?? "—"}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}
