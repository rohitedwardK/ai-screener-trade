import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { IntradayBar } from "../api/types";
import { fmt } from "../lib/format";

interface Props {
  bars: IntradayBar[];
  vwap: number | null;
  support: number | null;
  resistance: number | null;
}

export default function IntradayChart({ bars, vwap, support, resistance }: Props) {
  if (!bars.length) {
    return (
      <div className="flex h-72 items-center justify-center text-sm text-fg-subtle">
        No intraday bars yet (waiting for the next 1-min tick).
      </div>
    );
  }
  const data = bars.map((b) => ({
    ts: new Date(b.ts).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }),
    close: b.close,
    high: b.high,
    low: b.low,
  }));

  const lows = bars.map((b) => b.low);
  const highs = bars.map((b) => b.high);
  const yMin = Math.min(...lows, support ?? Infinity);
  const yMax = Math.max(...highs, resistance ?? -Infinity);
  const pad = Math.max((yMax - yMin) * 0.05, 1);

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 10, right: 12, left: -8, bottom: 4 }}>
          <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="ts"
            tick={{ fill: "#64748b", fontSize: 11 }}
            axisLine={{ stroke: "#cbd5e1" }}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[yMin - pad, yMax + pad]}
            tick={{ fill: "#64748b", fontSize: 11 }}
            axisLine={{ stroke: "#cbd5e1" }}
            tickFormatter={(v) => fmt.num(v, 0)}
          />
          <Tooltip
            contentStyle={{
              background: "white",
              border: "1px solid #e2e8f0",
              borderRadius: 8,
              fontSize: 12,
            }}
            formatter={(v: number) => fmt.num(v)}
          />
          <Line
            type="monotone"
            dataKey="close"
            stroke="#2563eb"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
          {vwap != null && (
            <ReferenceLine
              y={vwap}
              stroke="#7c3aed"
              strokeDasharray="4 4"
              label={{ value: `VWAP ${fmt.num(vwap)}`, position: "right", fill: "#7c3aed", fontSize: 11 }}
            />
          )}
          {support != null && (
            <ReferenceLine
              y={support}
              stroke="#059669"
              strokeDasharray="2 2"
              label={{ value: `S ${fmt.num(support)}`, position: "right", fill: "#059669", fontSize: 11 }}
            />
          )}
          {resistance != null && (
            <ReferenceLine
              y={resistance}
              stroke="#dc2626"
              strokeDasharray="2 2"
              label={{ value: `R ${fmt.num(resistance)}`, position: "right", fill: "#dc2626", fontSize: 11 }}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
