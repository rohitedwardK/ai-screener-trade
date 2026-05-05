import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Candle } from "@/api/types";
import { useMemo } from "react";

function ema(values: number[], length: number): (number | null)[] {
  const k = 2 / (length + 1);
  const out: (number | null)[] = [];
  let prev: number | null = null;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (i < length - 1) {
      out.push(null);
      continue;
    }
    if (prev == null) {
      const seed =
        values.slice(i - length + 1, i + 1).reduce((a, b) => a + b, 0) / length;
      prev = seed;
    } else {
      prev = v * k + prev * (1 - k);
    }
    out.push(prev);
  }
  return out;
}

export function PriceChart({ candles }: { candles: Candle[] }) {
  const data = useMemo(() => {
    const closes = candles.map((c) => c.close);
    const e20 = ema(closes, 20);
    const e50 = ema(closes, 50);
    const e200 = ema(closes, 200);
    return candles.map((c, i) => ({
      date: c.date,
      close: c.close,
      ema20: e20[i],
      ema50: e50[i],
      ema200: e200[i],
    }));
  }, [candles]);

  if (!candles.length) {
    return (
      <div className="card flex h-72 items-center justify-center text-fg-muted">
        No price history available.
      </div>
    );
  }

  return (
    <div className="card p-3">
      <div className="text-sm font-medium mb-2">Price + EMA overlays</div>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 5, right: 16, bottom: 5, left: 0 }}>
            <CartesianGrid stroke="#232a36" strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tick={{ fill: "#8b94a7", fontSize: 11 }}
              axisLine={{ stroke: "#232a36" }}
              tickLine={false}
              minTickGap={50}
            />
            <YAxis
              domain={["auto", "auto"]}
              tick={{ fill: "#8b94a7", fontSize: 11 }}
              axisLine={{ stroke: "#232a36" }}
              tickLine={false}
              width={56}
            />
            <Tooltip
              contentStyle={{
                background: "#11161f",
                border: "1px solid #232a36",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: "#e6e9ef" }}
            />
            <Legend wrapperStyle={{ fontSize: 11, color: "#8b94a7" }} />
            <Line
              type="monotone"
              dataKey="close"
              stroke="#e6e9ef"
              strokeWidth={1.5}
              dot={false}
              name="Close"
            />
            <Line
              type="monotone"
              dataKey="ema20"
              stroke="#10b981"
              strokeWidth={1}
              dot={false}
              name="EMA20"
            />
            <Line
              type="monotone"
              dataKey="ema50"
              stroke="#3b82f6"
              strokeWidth={1}
              dot={false}
              name="EMA50"
            />
            <Line
              type="monotone"
              dataKey="ema200"
              stroke="#f59e0b"
              strokeWidth={1}
              dot={false}
              name="EMA200"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
