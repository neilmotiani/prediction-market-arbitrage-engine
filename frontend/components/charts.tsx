"use client";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Snapshot } from "@/lib/types";
import { time } from "@/lib/api";
const grid = "#202c36";
const tooltip = {
  background: "#17232d",
  border: "1px solid #34434f",
  borderRadius: 8,
  color: "#e5eef5",
  fontSize: 13,
};
export function DepthChart({ snapshot }: { snapshot?: Snapshot }) {
  if (!snapshot)
    return (
      <div className="empty chart-empty">
        Waiting for a complete order book.
      </div>
    );
  const asks = [...snapshot.asks]
    .sort((a, b) => Number(a.price) - Number(b.price))
    .map((l, i, levels) => ({
      price: Number(l.price),
      asks: levels.slice(0, i + 1).reduce((sum, x) => sum + Number(x.size), 0),
    }));
  const bids = [...snapshot.bids]
    .sort((a, b) => Number(b.price) - Number(a.price))
    .map((l, i, levels) => ({
      price: Number(l.price),
      bids: levels.slice(0, i + 1).reduce((sum, x) => sum + Number(x.size), 0),
    }));
  const data = [...bids, ...asks].sort((a, b) => a.price - b.price);
  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart
        data={data}
        margin={{ top: 12, right: 12, left: -20, bottom: 0 }}
      >
        <defs>
          <linearGradient id="bid" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#40dca8" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#40dca8" stopOpacity={0.02} />
          </linearGradient>
          <linearGradient id="ask" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#fc8c91" stopOpacity={0.25} />
            <stop offset="100%" stopColor="#fc8c91" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={grid} strokeDasharray="3 4" vertical={false} />
        <XAxis
          dataKey="price"
          type="number"
          domain={["dataMin", "dataMax"]}
          tickFormatter={(v) => `${(v * 100).toFixed(0)}¢`}
          stroke="#7e91a2"
          tickLine={false}
          axisLine={false}
          fontSize={12}
        />
        <YAxis
          stroke="#7e91a2"
          tickLine={false}
          axisLine={false}
          fontSize={12}
        />
        <Tooltip
          contentStyle={tooltip}
          labelFormatter={(v) => `${(Number(v) * 100).toFixed(1)}¢`}
        />
        <Area
          type="stepAfter"
          dataKey="bids"
          name="Cumulative bids"
          stroke="#40dca8"
          fill="url(#bid)"
          strokeWidth={2}
          isAnimationActive={false}
        />
        <Area
          type="stepAfter"
          dataKey="asks"
          name="Cumulative asks"
          stroke="#fc8c91"
          fill="url(#ask)"
          strokeWidth={2}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
export function PriceChart({ history }: { history: Snapshot[] }) {
  const data = history
    .filter((s) => s.outcome === "YES")
    .map((s) => ({
      time: time(s.timestamp),
      bid: s.best_bid === null ? null : Number(s.best_bid) * 100,
      ask: s.best_ask === null ? null : Number(s.best_ask) * 100,
    }));
  if (data.length < 2)
    return (
      <div className="empty chart-empty">
        Collecting price history… new observations arrive every few seconds.
      </div>
    );
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart
        data={data}
        margin={{ top: 12, right: 12, left: -14, bottom: 0 }}
      >
        <CartesianGrid stroke={grid} strokeDasharray="3 4" vertical={false} />
        <XAxis
          dataKey="time"
          minTickGap={50}
          stroke="#7e91a2"
          tickLine={false}
          axisLine={false}
          fontSize={12}
        />
        <YAxis
          domain={["auto", "auto"]}
          tickFormatter={(v) => `${Number(v).toFixed(1)}¢`}
          stroke="#7e91a2"
          tickLine={false}
          axisLine={false}
          fontSize={12}
        />
        <Tooltip contentStyle={tooltip} />
        <Line
          type="monotone"
          dataKey="ask"
          name="YES ask (¢)"
          stroke="#78a9ff"
          dot={false}
          strokeWidth={2}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="bid"
          name="YES bid (¢)"
          stroke="#40dca8"
          dot={false}
          strokeWidth={2}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
