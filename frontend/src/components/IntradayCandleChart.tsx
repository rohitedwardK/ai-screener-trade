import {
  CartesianGrid,
  ComposedChart,
  Customized,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { IntradayCandle } from "@/api/types";
import { fmt } from "@/lib/format";
import { analyseChartPattern, type ChartPatternAnalysis } from "@/lib/chartPatterns";

interface CandleDatum {
  label: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

type CandleLayerProps = {
  xAxisMap?: Record<string, { scale: (v: string) => number; bandwidth?: () => number }>;
  yAxisMap?: Record<string, { scale: (v: number) => number }>;
  data: CandleDatum[];
};

type PatternLayerProps = {
  xAxisMap?: Record<string, { scale: (v: string) => number; bandwidth?: () => number }>;
  yAxisMap?: Record<string, { scale: (v: number) => number }>;
  analysis: ChartPatternAnalysis;
};

function CandleLayer({ xAxisMap, yAxisMap, data }: CandleLayerProps) {
  if (!xAxisMap || !yAxisMap || !data.length) return null;
  const xKey = Object.keys(xAxisMap)[0];
  const yKey = Object.keys(yAxisMap)[0];
  const xScale = xAxisMap[xKey].scale;
  const yScale = yAxisMap[yKey].scale;
  const bandwidth = xAxisMap[xKey].bandwidth?.() ?? 10;
  const w = Math.max(bandwidth * 0.55, 3);

  return (
    <g>
      {data.map((d) => {
        const x = xScale(d.label) + bandwidth / 2;
        const color = d.close >= d.open ? "#10b981" : "#ef4444";
        const yHigh = yScale(d.high);
        const yLow = yScale(d.low);
        const yOpen = yScale(d.open);
        const yClose = yScale(d.close);
        const bodyTop = Math.min(yOpen, yClose);
        const bodyBottom = Math.max(yOpen, yClose);
        return (
          <g key={d.label}>
            <line x1={x} x2={x} y1={yHigh} y2={yLow} stroke={color} strokeWidth={1.5} />
            <rect
              x={x - w / 2}
              y={bodyTop}
              width={w}
              height={Math.max(bodyBottom - bodyTop, 1)}
              fill={color}
            />
          </g>
        );
      })}
    </g>
  );
}

function PatternLayer({ xAxisMap, yAxisMap, analysis }: PatternLayerProps) {
  if (!xAxisMap || !yAxisMap) return null;
  const xKey = Object.keys(xAxisMap)[0];
  const yKey = Object.keys(yAxisMap)[0];
  const xScale = xAxisMap[xKey].scale;
  const yScale = yAxisMap[yKey].scale;
  const bandwidth = xAxisMap[xKey].bandwidth?.() ?? 10;

  const renderLine = (
    line: NonNullable<ChartPatternAnalysis["supportLine"]>,
    color: string,
    label: string,
  ) => {
    const x1 = xScale(line.startKey) + bandwidth / 2;
    const x2 = xScale(line.endKey) + bandwidth / 2;
    if (![x1, x2].every(Number.isFinite)) return null;
    return (
      <g key={label}>
        <line
          x1={x1}
          x2={x2}
          y1={yScale(line.startValue)}
          y2={yScale(line.endValue)}
          stroke={color}
          strokeWidth={2}
          strokeDasharray="5 4"
        />
        <text x={x2 + 4} y={yScale(line.endValue) - 4} fill={color} fontSize={10}>
          {label}
        </text>
      </g>
    );
  };

  return (
    <g>
      {analysis.supportLine && renderLine(analysis.supportLine, "#10b981", "trend support")}
      {analysis.resistanceLine && renderLine(analysis.resistanceLine, "#ef4444", "trend resistance")}
    </g>
  );
}

export function IntradayCandleChart({
  candles,
  support,
  resistance,
  vwap,
}: {
  candles: IntradayCandle[];
  support?: number | null;
  resistance?: number | null;
  vwap?: number | null;
}) {
  const data: CandleDatum[] = candles.map((c) => ({
    label: new Date(c.ts).toLocaleString("en-IN", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }),
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
    volume: c.volume,
  }));

  const patternAnalysis = analyseChartPattern(
    data.map((d) => ({
      key: d.label,
      high: d.high,
      low: d.low,
      close: d.close,
    })),
  );

  if (!candles.length) {
    return (
      <div className="flex h-72 items-center justify-center text-sm text-fg-subtle">
        No intraday bars available for this symbol.
      </div>
    );
  }

  const lows = candles.map((c) => c.low);
  const highs = candles.map((c) => c.high);
  const yMin = Math.min(...lows, support ?? Infinity);
  const yMax = Math.max(...highs, resistance ?? -Infinity, vwap ?? -Infinity);
  const pad = Math.max((yMax - yMin) * 0.04, 0.5);

  return (
    <div className="w-full">
      <div className="h-80 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 12, left: -4, bottom: 4 }}>
          <CartesianGrid stroke="#232a36" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: "#8b94a7", fontSize: 10 }}
            axisLine={{ stroke: "#232a36" }}
            tickLine={false}
            interval="preserveStartEnd"
            minTickGap={28}
          />
          <YAxis
            domain={[yMin - pad, yMax + pad]}
            tick={{ fill: "#8b94a7", fontSize: 10 }}
            axisLine={{ stroke: "#232a36" }}
            tickLine={false}
            width={56}
            tickFormatter={(v) => fmt.num(v, 0)}
          />
          <Tooltip
            contentStyle={{
              background: "#11161f",
              border: "1px solid #232a36",
              borderRadius: 8,
              fontSize: 12,
            }}
            labelStyle={{ color: "#e6e9ef" }}
            formatter={(v: number) => fmt.num(v)}
          />
          <Line type="monotone" dataKey="close" stroke="transparent" dot={false} isAnimationActive={false} />
          <Customized
            component={(props: {
              xAxisMap?: CandleLayerProps["xAxisMap"];
              yAxisMap?: CandleLayerProps["yAxisMap"];
            }) => (
              <CandleLayer xAxisMap={props.xAxisMap} yAxisMap={props.yAxisMap} data={data} />
            )}
          />
          <Customized
            component={(props: {
              xAxisMap?: PatternLayerProps["xAxisMap"];
              yAxisMap?: PatternLayerProps["yAxisMap"];
            }) => (
              <PatternLayer
                xAxisMap={props.xAxisMap}
                yAxisMap={props.yAxisMap}
                analysis={patternAnalysis}
              />
            )}
          />
          {vwap != null && (
            <ReferenceLine
              y={vwap}
              stroke="#8b5cf6"
              strokeDasharray="4 4"
              label={{ value: `VWAP ${fmt.num(vwap)}`, position: "right", fill: "#8b5cf6", fontSize: 10 }}
            />
          )}
          {support != null && (
            <ReferenceLine
              y={support}
              stroke="#10b981"
              strokeDasharray="2 2"
              label={{ value: `S ${fmt.num(support)}`, position: "right", fill: "#10b981", fontSize: 10 }}
            />
          )}
          {resistance != null && (
            <ReferenceLine
              y={resistance}
              stroke="#ef4444"
              strokeDasharray="2 2"
              label={{ value: `R ${fmt.num(resistance)}`, position: "right", fill: "#ef4444", fontSize: 10 }}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
      </div>
      <div className="mt-3 rounded-md border border-border bg-bg-elevated p-3 text-xs">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="font-medium text-fg">{patternAnalysis.label}</div>
          <div
            className={
              patternAnalysis.bias === "LONG"
                ? "text-accent-green"
                : patternAnalysis.bias === "SHORT"
                  ? "text-accent-red"
                  : "text-accent-amber"
            }
          >
            {patternAnalysis.bias}
          </div>
        </div>
        <p className="mt-1 text-fg-muted">{patternAnalysis.explanation}</p>
        <p className="mt-1 text-fg-muted">Next: {patternAnalysis.nextAction}</p>
      </div>
    </div>
  );
}
