"use client";
import Link from "next/link";
import {
  Activity,
  ArrowDownUp,
  ArrowRight,
  BookOpen,
  LayoutDashboard,
  Wallet,
  ShieldCheck,
} from "lucide-react";
import { API } from "@/lib/api";
import type { Metrics } from "@/lib/types";
export function Sidebar({
  view,
  setView,
  metrics,
}: {
  view: string;
  setView: (view: string) => void;
  metrics: Metrics | null;
}) {
  return (
    <aside className="sidebar">
      <Link href="/" className="brand" aria-label="Arbitrage engine home">
        <div className="brand-symbol">
          <ArrowDownUp size={24} />
        </div>
        <div>
          ARBITRAGE<span>RESEARCH ENGINE</span>
        </div>
      </Link>
      <div className="workspace-label">
        WORKSPACE <span>01</span>
      </div>
      <nav>
        {[
          ["overview", "Overview", LayoutDashboard],
          ["trades", "Paper portfolio", Wallet],
          ["system", "System health", Activity],
        ].map(([id, label, Icon]) => {
          const NavIcon = Icon as typeof Activity;
          return (
            <button
              key={id as string}
              aria-label={label as string}
              aria-current={view === id ? "page" : undefined}
              className={view === id ? "nav-item active" : "nav-item"}
              onClick={() => setView(id as string)}
            >
              <NavIcon size={18} />
              {label as string}
              {id === "overview" && (
                <span className="nav-count">
                  {metrics?.executable_opportunities ?? 0}
                </span>
              )}
            </button>
          );
        })}
      </nav>
      <div className="sidebar-note">
        <ShieldCheck size={18} />
        <strong>Paper execution only</strong>
        <p>Research capital. Simulated fills. No real-money orders.</p>
        <span className="tiny-label">EXECUTION PROVIDER</span>
        <code>PaperExecutionProvider</code>
      </div>
      <a
        className="docs-link"
        href={`${API}/docs`}
        target="_blank"
        rel="noreferrer"
      >
        <BookOpen size={16} /> API reference <ArrowRight size={14} />
      </a>
      <div className="sidebar-footer">
        <span className="status-dot" /> ENGINE v0.1.0
      </div>
    </aside>
  );
}
