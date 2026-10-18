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
import { fmt } from "@/lib/format";

interface ChartDatum {
  date: string;
  close: number;
  ema50: number | null;
  ema200: number | null;
}

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
      prev =
        values.slice(i - length + 1, i + 1).reduce((a, b) => a + b, 0) /
        length;
    } else {
      prev = v * k + prev * (1 - k);
    }
    out.push(prev);
  }
  return out;
}

function formatDateLabel(value: string) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return value;
  return date.toLocaleDateString("en-IN", {
    month: "short",
    year: "2-digit",
  });
}

export function PriceChart({ candles }: { candles: Candle[] }) {
  const data = useMemo<ChartDatum[]>(() => {
    const closes = candles.map((c) => c.close);
    const e50 = ema(closes, 50);
    const e200 = ema(closes, 200);
    return candles.map((c, i) => ({
      date: c.date,
      close: c.close,
      ema50: e50[i],
      ema200: e200[i],
    }));
  }, [candles]);

  const latest = data.at(-1);

  if (!candles.length) {
    return (
      <div className="card flex h-72 items-center justify-center text-fg-muted">
        No price history available.
      </div>
    );
  }

  return (
    <div className="card p-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium">5-year price reference</div>
          <div className="text-xs text-fg-muted">
            Clean daily view for context; use TradingView for drawings and
            intraday chart work.
          </div>
        </div>
        {latest && (
          <div className="text-right">
            <div className="text-xs text-fg-muted">Last daily close</div>
            <div className="num text-lg font-semibold">
              {fmt.num(latest.close, 2)}
            </div>
          </div>
        )}
      </div>
      <div className="h-[360px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data}
            margin={{ top: 5, right: 24, bottom: 5, left: 0 }}
          >
            <CartesianGrid stroke="#232a36" strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tick={{ fill: "#8b94a7", fontSize: 11 }}
              axisLine={{ stroke: "#232a36" }}
              tickFormatter={formatDateLabel}
              tickLine={false}
              minTickGap={48}
            />
            <YAxis
              domain={["auto", "auto"]}
              tick={{ fill: "#8b94a7", fontSize: 11 }}
              axisLine={{ stroke: "#232a36" }}
              tickFormatter={(value) => fmt.num(Number(value), 0)}
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
              formatter={(value, name) => [
                fmt.num(Number(value), 2),
                String(name),
              ]}
              labelFormatter={formatDateLabel}
              labelStyle={{ color: "#e6e9ef" }}
            />
            <Legend wrapperStyle={{ fontSize: 11, color: "#8b94a7" }} />
            <Line
              type="monotone"
              dataKey="close"
              stroke="#e6e9ef"
              strokeWidth={1.8}
              dot={false}
              name="Close"
            />
            <Line
              type="monotone"
              dataKey="ema50"
              stroke="#38bdf8"
              strokeWidth={1.2}
              dot={false}
              name="EMA50"
            />
            <Line
              type="monotone"
              dataKey="ema200"
              stroke="#f59e0b"
              strokeWidth={1.2}
              dot={false}
              name="EMA200"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
