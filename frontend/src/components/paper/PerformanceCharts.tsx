import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PaperPerformance } from "@/api/types";
import { fmt } from "@/lib/format";

const TOOLTIP_STYLE = {
  background: "#11161f",
  border: "1px solid #232a36",
  borderRadius: 8,
  fontSize: 12,
};

const TOOLTIP_LABEL_STYLE = { color: "#e6e9ef" };
const AXIS_TICK = { fill: "#8b94a7", fontSize: 11 };
const AXIS_LINE = { stroke: "#232a36" };

export function EquityCurveChart({ data }: { data: PaperPerformance["equity_curve"] }) {
  if (data.length === 0) {
    return (
      <div className="card p-6 text-fg-muted text-sm">
        No equity history yet. The curve will populate after the first simulated day.
      </div>
    );
  }
  return (
    <div className="card p-3">
      <div className="text-sm font-medium mb-2">Equity curve</div>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data}
            margin={{ top: 5, right: 16, bottom: 5, left: 0 }}
          >
            <CartesianGrid stroke="#232a36" strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tick={AXIS_TICK}
              axisLine={AXIS_LINE}
              tickLine={false}
              minTickGap={50}
            />
            <YAxis
              domain={["auto", "auto"]}
              tick={AXIS_TICK}
              axisLine={AXIS_LINE}
              tickLine={false}
              width={64}
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelStyle={TOOLTIP_LABEL_STYLE}
              formatter={(v: number) => [`₹${fmt.inr(v, 0)}`, "Equity"]}
            />
            <Line
              type="monotone"
              dataKey="equity"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function DailyPnlChart({ data }: { data: PaperPerformance["equity_curve"] }) {
  if (data.length === 0) {
    return null;
  }
  return (
    <div className="card p-3">
      <div className="text-sm font-medium mb-2">Daily P&L</div>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            margin={{ top: 5, right: 16, bottom: 5, left: 0 }}
          >
            <CartesianGrid stroke="#232a36" strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tick={AXIS_TICK}
              axisLine={AXIS_LINE}
              tickLine={false}
              minTickGap={50}
            />
            <YAxis
              tick={AXIS_TICK}
              axisLine={AXIS_LINE}
              tickLine={false}
              width={64}
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelStyle={TOOLTIP_LABEL_STYLE}
              formatter={(v: number) => [`₹${fmt.inr(v, 0)}`, "P&L"]}
            />
            <Bar dataKey="daily_pnl" radius={[3, 3, 0, 0]}>
              {data.map((d, i) => (
                <Cell
                  key={i}
                  fill={d.daily_pnl >= 0 ? "#10b981" : "#ef4444"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function WinLossChart({
  wins,
  losses,
}: {
  wins: number;
  losses: number;
}) {
  const data = [
    { name: "Wins", value: wins, fill: "#10b981" },
    { name: "Losses", value: losses, fill: "#ef4444" },
  ];
  if (wins + losses === 0) {
    return (
      <div className="card p-3 flex flex-col items-center justify-center min-h-[16rem] text-fg-muted text-sm">
        No closed trades yet
      </div>
    );
  }
  return (
    <div className="card p-3">
      <div className="text-sm font-medium mb-2">Win / loss distribution</div>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              innerRadius={50}
              outerRadius={80}
              paddingAngle={2}
              labelLine={false}
              label={({ name, value }) => `${name}: ${value}`}
            >
              {data.map((d, i) => (
                <Cell key={i} fill={d.fill} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelStyle={TOOLTIP_LABEL_STYLE}
            />
            <Legend
              wrapperStyle={{ fontSize: 11, color: "#8b94a7" }}
              iconType="circle"
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function SetupPerformanceChart({
  bySetup,
}: {
  bySetup: PaperPerformance["by_setup"];
}) {
  const data = useMemo(
    () =>
      Object.entries(bySetup).map(([setup, m]) => ({
        setup,
        total_pnl: m.total_pnl,
        win_rate: m.win_rate,
        trades: m.trades,
      })),
    [bySetup]
  );

  if (data.length === 0) {
    return (
      <div className="card p-3 flex flex-col items-center justify-center min-h-[16rem] text-fg-muted text-sm">
        No closed trades yet
      </div>
    );
  }

  return (
    <div className="card p-3">
      <div className="text-sm font-medium mb-2">Performance by setup</div>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            margin={{ top: 5, right: 16, bottom: 5, left: 0 }}
          >
            <CartesianGrid stroke="#232a36" strokeDasharray="3 3" />
            <XAxis
              dataKey="setup"
              tick={AXIS_TICK}
              axisLine={AXIS_LINE}
              tickLine={false}
            />
            <YAxis
              tick={AXIS_TICK}
              axisLine={AXIS_LINE}
              tickLine={false}
              width={64}
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelStyle={TOOLTIP_LABEL_STYLE}
              formatter={(v: number, name: string) =>
                name === "total_pnl"
                  ? [`₹${fmt.inr(v, 0)}`, "Total P&L"]
                  : [v, name]
              }
            />
            <Bar dataKey="total_pnl" radius={[3, 3, 0, 0]}>
              {data.map((d, i) => (
                <Cell
                  key={i}
                  fill={d.total_pnl >= 0 ? "#10b981" : "#ef4444"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function PerformanceCharts({
  performance,
}: {
  performance: PaperPerformance | undefined;
}) {
  if (!performance) {
    return null;
  }
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <EquityCurveChart data={performance.equity_curve} />
      <DailyPnlChart data={performance.equity_curve} />
      <WinLossChart
        wins={performance.winning_trades}
        losses={performance.losing_trades}
      />
      <SetupPerformanceChart bySetup={performance.by_setup} />
    </div>
  );
}
