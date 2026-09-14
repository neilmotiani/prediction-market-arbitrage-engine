"use client";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowRight,
  ChevronDown,
  FlaskConical,
  Layers3,
  Radio,
  Search,
  ShieldCheck,
  Terminal,
  Wallet,
  X,
} from "lucide-react";
import { Sidebar } from "@/components/sidebar";
import { TradeTable } from "@/components/trade-table";
import { SystemHealth } from "@/components/system-health";
import { ScanDiagnostics } from "@/components/scan-diagnostics";
import { OpportunityTable } from "@/components/opportunity-table";
import { DepthChart, PriceChart } from "@/components/charts";
import { OpportunityDrawer } from "@/components/opportunity-drawer";
import { API, money, request } from "@/lib/api";
import type {
  Market,
  Metrics,
  Opportunity,
  Snapshot,
  Trade,
} from "@/lib/types";

export default function Dashboard() {
  const [ops, setOps] = useState<Opportunity[]>([]),
    [markets, setMarkets] = useState<Market[]>([]),
    [trades, setTrades] = useState<Trade[]>([]),
    [metrics, setMetrics] = useState<Metrics | null>(null);
  const [connected, setConnected] = useState(false),
    [loaded, setLoaded] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [view, setView] = useState("overview"),
    [selected, setSelected] = useState<Opportunity | null>(null),
    [busy, setBusy] = useState(false);
  const [marketKey, setMarketKey] = useState("polymarket:eth-edge"),
    [outcome, setOutcome] = useState("YES"),
    [history, setHistory] = useState<Snapshot[]>([]);
  const refresh = useCallback(async () => {
    try {
      const [o, m, t, h] = await Promise.all([
        request<Opportunity[]>("/opportunities"),
        request<Market[]>("/markets"),
        request<Trade[]>("/trades"),
        request<Metrics>("/metrics"),
      ]);
      setOps(o);
      setMarkets(m);
      setTrades(t);
      setMetrics(h);
      setLoaded(true);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cannot reach research API");
    }
  }, []);
  useEffect(() => {
    let active = true,
      socket: WebSocket | undefined,
      retry: ReturnType<typeof setTimeout>;
    const connect = () => {
      socket = new WebSocket(`${API.replace(/^http/, "ws")}/ws/opportunities`);
      socket.onopen = () => {
        if (active) setConnected(true);
      };
      socket.onmessage = (event) => {
        if (!active) return;
        const msg = JSON.parse(event.data);
        if (msg.metrics) setMetrics(msg.metrics);
        if (msg.type === "opportunities") setOps(msg.data);
        if (msg.type === "trade") void refresh();
      };
      socket.onclose = () => {
        if (active) {
          setConnected(false);
          retry = setTimeout(connect, 3000);
        }
      };
      socket.onerror = () => socket?.close();
    };
    const initial = setTimeout(refresh, 0);
    connect();
    const poll = setInterval(refresh, 3000);
    return () => {
      active = false;
      clearTimeout(initial);
      clearInterval(poll);
      clearTimeout(retry);
      socket?.close();
    };
  }, [refresh]);
  const activeMarket = markets.find((m) => m.id === marketKey) || markets[0];
  const activeKey = activeMarket?.id;
  useEffect(() => {
    if (!activeKey) return;
    let active = true;
    const load = async () => {
      try {
        const r = await request<{ history: Snapshot[] }>(
          `/markets/${encodeURIComponent(activeKey)}`,
        );
        if (active) setHistory(r.history);
      } catch {
        if (active) setHistory([]);
      }
    };
    void load();
    const timer = setInterval(load, 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [activeKey]);
  const execute = async (op?: Opportunity) => {
    setBusy(true);
    setNotice("");
    try {
      const t = await request<Trade>(
        "/simulation/run",
        op ? { opportunity_id: op.id } : {},
      );
      setNotice(
        `Paper fill recorded · ${t.quantity} paired shares · ${money(t.expected_pnl)} expected profit`,
      );
      setSelected(null);
      await refresh();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Simulation failed");
    } finally {
      setBusy(false);
    }
  };
  const settle = async (t: Trade) => {
    setBusy(true);
    try {
      const result = await request<Trade>("/simulation/run", {
        action: "settle",
        trade_id: t.id,
        resolutions: Object.fromEntries(t.market_keys.map((k) => [k, "YES"])),
      });
      setNotice(
        `Mock YES resolution recorded · ${money(result.realized_pnl)} realized P&L`,
      );
      await refresh();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Settlement failed");
    } finally {
      setBusy(false);
    }
  };
  const book = activeMarket?.snapshots.find((s) => s.outcome === outcome);
  const healthy =
    metrics &&
    Object.values(metrics.connections).some((c) => c.state === "connected") &&
    !error;
  return (
    <div className="shell">
      <Sidebar view={view} setView={setView} metrics={metrics} />
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <span>/</span>{" "}
            <strong>
              {view === "overview"
                ? "Market research"
                : view === "trades"
                  ? "Paper portfolio"
                  : "System health"}
            </strong>
          </div>
          <div className="topbar-right">
            <span className="mode-badge">
              <FlaskConical size={13} />
              {metrics?.mode === "live" ? "LIVE DATA" : "MOCK DATA"}
            </span>
            <span
              className={healthy ? "connection positive" : "connection muted"}
            >
              <span className={`status-dot ${healthy ? "" : "off"}`} />
              {healthy ? "Feeds connected" : "Awaiting feed"}
            </span>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">PREDICTION MARKET ARBITRAGE ENGINE</div>
              <h1>
                {view === "overview"
                  ? "Market overview"
                  : view === "trades"
                    ? "Paper portfolio"
                    : "System health"}
                <span className="live-label">
                  {connected ? "STREAMING" : "POLLING"}
                </span>
              </h1>
              <p className="muted">
                {view === "overview"
                  ? "Find the edge. Account for the execution."
                  : view === "trades"
                    ? metrics?.mode === "live"
                      ? "Real market books, simulated fills, and reserved research capital."
                      : "Paired fills, reserved capital, and explicit mock settlement."
                    : "Market data, detection throughput, and connector diagnostics."}
              </p>
            </div>
            <button
              className="primary"
              disabled={busy || !metrics?.executable_opportunities || !healthy}
              onClick={() => execute()}
            >
              <FlaskConical size={16} />
              {busy ? "Simulating…" : "Run paper simulation"}
              <ArrowRight size={15} />
            </button>
          </div>
          {error && (
            <div className="error-banner" role="alert">
              API unavailable: {error}. Check the backend on {API}. Retrying
              automatically.
            </div>
          )}
          {metrics?.mode === "live" && (
            <div className="notice" role="status">
              <Radio size={16} />
              <span>
                LIVE MARKET DATA ·{" "}
                {metrics.auto_paper_trade
                  ? "Automatic paper trading active"
                  : "Manual paper trading"}{" "}
                · {metrics.fee_verified_books}/{metrics.books_monitored} books
                with verified fee metadata. Trades appear only when real quotes
                pass all execution checks.
              </span>
            </div>
          )}
          {notice && (
            <div className="notice" role="status">
              <Terminal size={16} />
              <span>{notice}</span>
              <button
                className="icon-button"
                aria-label="Dismiss notification"
                onClick={() => setNotice("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          <section className="stat-grid" aria-label="Research metrics">
            {[
              {
                label: "Markets monitored",
                value: metrics?.markets_monitored,
                detail: `${new Set(markets.map((m) => m.venue)).size} venues · YES / NO contracts`,
                icon: Layers3,
              },
              {
                label: "Theoretical opportunities",
                value: metrics?.opportunities_detected,
                detail: "Positive gross edge · current scan",
                icon: Search,
              },
              {
                label: "Executable opportunities",
                value: metrics?.executable_opportunities,
                detail: "After depth, costs & risk checks",
                icon: ShieldCheck,
                green: true,
              },
              {
                label: "Simulated realized P&L",
                value: money(metrics?.simulated_pnl),
                detail: `${money(metrics?.expected_open_pnl)} expected on open positions`,
                icon: Wallet,
                green: Number(metrics?.simulated_pnl) >= 0,
              },
            ].map((card) => (
              <div className="stat-card" key={card.label}>
                <div className="stat-label">
                  {card.label}
                  <card.icon size={16} />
                </div>
                <strong className={card.green ? "positive" : ""}>
                  {card.value ?? "—"}
                </strong>
                <span>{card.detail}</span>
              </div>
            ))}
          </section>
          {view === "overview" && (
            <>
              {metrics?.mode === "live" && (
                <ScanDiagnostics metrics={metrics} />
              )}
              <OpportunityTable
                ops={ops}
                metrics={metrics}
                loaded={loaded}
                setSelected={setSelected}
              />
              <div className="analysis-heading">
                <h2>Microstructure analysis</h2>
                <label className="market-select">
                  <select
                    aria-label="Market for charts"
                    value={activeKey || ""}
                    onChange={(e) => setMarketKey(e.target.value)}
                  >
                    {markets.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.title} · {m.venue}
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={14} />
                </label>
              </div>
              <section className="chart-grid">
                <div className="panel chart-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Order-book depth</h2>
                      <p>Cumulative shares at each price level</p>
                    </div>
                    <div className="segmented">
                      {["YES", "NO"].map((o) => (
                        <button
                          key={o}
                          aria-pressed={outcome === o}
                          className={outcome === o ? "selected" : ""}
                          onClick={() => setOutcome(o)}
                        >
                          {o}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="chart-legend">
                    <span>
                      <i className="legend-dot green" />
                      Bids
                    </span>
                    <span>
                      <i className="legend-dot red" />
                      Asks
                    </span>
                    <strong>
                      Spread{" "}
                      {book?.best_ask != null && book.best_bid != null
                        ? `${((Number(book.best_ask) - Number(book.best_bid)) * 100).toFixed(2)}¢`
                        : "—"}
                    </strong>
                  </div>
                  <DepthChart snapshot={book} />
                </div>
                <div className="panel chart-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Price & spread history</h2>
                      <p>YES contract · stored book observations</p>
                    </div>
                    <span className="subtle-badge">LAST 120</span>
                  </div>
                  <div className="chart-legend">
                    <span>
                      <i className="legend-dot blue" />
                      Best ask
                    </span>
                    <span>
                      <i className="legend-dot green" />
                      Best bid
                    </span>
                    <strong>USD cents</strong>
                  </div>
                  <PriceChart
                    history={history.filter(
                      (s) => `${s.venue}:${s.market_id}` === activeKey,
                    )}
                  />
                </div>
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Simulated trade history</h2>
                    <p>
                      Atomic paper fills · fees and execution reserves included
                    </p>
                  </div>
                  <span className="subtle-badge">{trades.length} TRADES</span>
                </div>
                <TradeTable
                  trades={trades}
                  metrics={metrics}
                  busy={busy}
                  settle={settle}
                />
              </section>
            </>
          )}
          {view === "trades" && (
            <>
              <div className="portfolio-summary">
                <div>
                  <span>Available research capital</span>
                  <strong>{money(metrics?.free_capital)}</strong>
                </div>
                <p>
                  {metrics?.mode === "live"
                    ? "Expected P&L is a simulation estimate. Capital stays reserved until a verified venue resolution. No real orders are sent."
                    : "Expected P&L assumes matching $1 settlement. Resolve YES applies a synthetic YES outcome to every venue leg in a trade."}
                </p>
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <h2>Positions & settlement</h2>
                  <span className="subtle-badge">PAPER ONLY</span>
                </div>
                <TradeTable
                  trades={trades}
                  metrics={metrics}
                  busy={busy}
                  settle={settle}
                />
              </section>
            </>
          )}
          {view === "system" && (
            <SystemHealth metrics={metrics} connected={connected} />
          )}
          <footer className="statusbar">
            <span>
              <span className={`status-dot ${healthy ? "" : "off"}`} />
              {healthy ? "ENGINE ONLINE" : "ENGINE WAITING"}
            </span>
            <span>{metrics?.market_updates_per_second ?? "—"} snapshots/s</span>
            <span>
              {metrics?.opportunities_checked_per_second ?? "—"} checks/s
            </span>
            <span>{metrics?.detection_latency_ms ?? "—"} ms detection</span>
            <span className="statusbar-right">
              USD · {metrics?.mode || "mock"} data · paper execution
            </span>
          </footer>
        </main>
      </div>
      <OpportunityDrawer
        op={selected}
        close={() => setSelected(null)}
        execute={execute}
        busy={busy}
      />
    </div>
  );
}
