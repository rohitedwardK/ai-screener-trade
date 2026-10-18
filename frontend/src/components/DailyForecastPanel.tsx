import { useQuery } from "@tanstack/react-query";
import { Loader2, RefreshCcw, TrendingUp } from "lucide-react";
import { CartesianGrid, ComposedChart, Customized, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/api/client";
import type { Candle } from "@/api/types";
import { fmt } from "@/lib/format";

type ChartRow = Candle & { ma20: number | null };
type CandleLayerProps = {
  data: ChartRow[];
  xAxisMap?: Record<string, { scale: (value: string) => number }>;
  yAxisMap?: Record<string, { scale: (value: number) => number }>;
};

function CandleLayer({ data, xAxisMap, yAxisMap }: CandleLayerProps) {
  if (!xAxisMap || !yAxisMap) return null;
  const x = Object.values(xAxisMap)[0].scale;
  const y = Object.values(yAxisMap)[0].scale;
  const width = data.length > 1 ? Math.max(2, Math.min(10, Math.abs(x(data[1].date) - x(data[0].date)) * 0.6)) : 6;
  return <g>{data.map((c) => <g key={c.date} className={c.close >= c.open ? "text-accent-green" : "text-accent-red"}>
    <line x1={x(c.date)} x2={x(c.date)} y1={y(c.high)} y2={y(c.low)} stroke="currentColor" />
    <rect x={x(c.date) - width / 2} y={Math.min(y(c.open), y(c.close))} width={width} height={Math.max(1, Math.abs(y(c.open) - y(c.close)))} fill="currentColor" />
  </g>)}</g>;
}

const FEATURES = [
  ["daily_return", "Latest daily change"],
  ["return_5d", "5-day change"],
  ["close_vs_ma20", "Above / below 20-day average"],
  ["volatility_20d", "20-day daily volatility"],
  ["relative_volume", "Volume vs 20-day average"],
] as const;

function dateLabel(value: string) {
  return new Date(`${value.slice(0, 10)}T12:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function DailyForecastPanel({ symbol, candles, historyLoading }: { symbol: string; candles: Candle[]; historyLoading: boolean }) {
  const forecast = useQuery({
    queryKey: ["daily-forecast", symbol],
    queryFn: () => api.getDailyForecast(symbol),
    enabled: !!symbol,
    staleTime: 300_000,
    retry: false,
  });
  const result = forecast.data;
  const probability = result?.probability_up;
  const metrics = result?.metrics;
  const aligned = candles.filter((c) => !result?.as_of || c.date.slice(0, 10) <= result.as_of);
  const rows: ChartRow[] = aligned.map((c, i) => ({ ...c, ma20: i < 19 ? null : aligned.slice(i - 19, i + 1).reduce((sum, day) => sum + day.close, 0) / 20 })).slice(-30);
  const latest = rows.at(-1);
  const prices = rows.flatMap((c) => [c.low, c.high, ...(c.ma20 == null ? [] : [c.ma20])]);
  const low = Math.min(...prices);
  const high = Math.max(...prices);
  const padding = Math.max((high - low) * 0.12, high * 0.002);
  const beatBaseline = metrics && metrics.test.brier < metrics.test_baseline_brier;

  return <section id="daily-forecast" aria-labelledby="daily-forecast-title" className="border-y border-border py-5 space-y-4 min-w-0">
    <header className="flex items-start justify-between gap-3">
      <div>
        <h2 id="daily-forecast-title" className="text-lg font-semibold flex items-center gap-2"><TrendingUp className="size-5 text-accent-cyan" />Daily forecast</h2>
        <p className="text-xs text-fg-muted mt-1">Next trading day's close{result?.as_of ? ` | Based on ${result.as_of}` : ""}</p>
      </div>
      <button type="button" className="btn shrink-0" title="Refresh daily forecast" aria-label="Refresh daily forecast" disabled={forecast.isFetching} onClick={() => void forecast.refetch()}>
        <RefreshCcw className={`size-4 ${forecast.isFetching ? "animate-spin" : ""}`} />
      </button>
    </header>
    {forecast.isLoading && <p role="status" className="flex items-center gap-2 text-sm text-fg-muted"><Loader2 className="size-4 animate-spin" />Evaluating historical daily data...</p>}
    {forecast.isError && <p role="alert" className="text-sm text-accent-amber">Forecast unavailable. Check that this stock has cached daily history, then retry using the refresh button.</p>}
    {result && probability == null && <p className="text-sm text-accent-amber">Forecast not available. {result.notes.join(" ")}</p>}
    <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,2fr)_minmax(240px,1fr)] gap-6">
      <div className="min-w-0">
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs mb-2">
          <span className="text-fg-muted">Last 30 trading sessions</span>
          <span className="text-accent-amber">20-day average: {fmt.inr(latest?.ma20)}</span>
          <span className="text-accent-cyan">Close: {fmt.inr(latest?.close)}</span>
        </div>
        {historyLoading ? <div className="h-60 grid place-items-center text-sm text-fg-muted">Loading candles...</div> : !rows.length ? <div className="h-60 grid place-items-center text-sm text-fg-muted">No daily candles available.</div> : <div className="h-60 w-full" role="img" aria-label="Daily candlestick chart with 20-day moving average and latest closing price">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 15, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} className="text-border" stroke="currentColor" strokeDasharray="3 3" />
              <XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={45} tick={{ fontSize: 10, fill: "currentColor" }} className="text-fg-muted" padding={{ left: 8, right: 8 }} />
              <YAxis domain={[low - padding, high + padding]} tickFormatter={(v: number) => fmt.num(v, 0)} width={55} tick={{ fontSize: 10, fill: "currentColor" }} className="text-fg-muted" />
              <Tooltip content={({ active, payload }) => {
                const c = payload?.[0]?.payload as ChartRow | undefined;
                return active && c ? <div className="rounded border border-border bg-bg-surface p-2 text-xs shadow-lg">
                  <p className="font-medium mb-1">{c.date.slice(0, 10)}</p>
                  <p>Open {fmt.inr(c.open)} | High {fmt.inr(c.high)}</p>
                  <p>Low {fmt.inr(c.low)} | Close {fmt.inr(c.close)}</p>
                  <p className="text-accent-amber">20-day average {fmt.inr(c.ma20)}</p>
                </div> : null;
              }} />
              <Line dataKey="close" stroke="transparent" dot={false} activeDot={false} isAnimationActive={false} />
              <Customized component={<CandleLayer data={rows} />} />
              <Line dataKey="ma20" className="text-accent-amber" stroke="currentColor" strokeWidth={2} dot={false} isAnimationActive={false} name="20-day average" />
              {latest && <ReferenceLine y={latest.close} className="text-accent-cyan" stroke="currentColor" strokeDasharray="4 4" />}
            </ComposedChart>
          </ResponsiveContainer>
        </div>}
      </div>
      <div className="min-w-0 space-y-3">
        {probability != null && <>
          <p className="text-sm text-fg-muted">Chance of closing higher</p>
          <p className="text-3xl font-semibold num text-accent-cyan">{fmt.pctRaw(probability * 100)}</p>
          <p className="text-sm">{Math.abs(probability - 0.5) < 0.05 ? "Roughly even chances" : probability > 0.5 ? "Model leans toward a higher close" : "Model leans toward a lower or unchanged close"}</p>
          <div className="h-2 bg-bg-elevated overflow-hidden rounded" role="meter" aria-label="Probability of an upward close" aria-valuemin={0} aria-valuemax={100} aria-valuenow={probability * 100}><div className="h-full bg-accent-cyan" style={{ width: `${probability * 100}%` }} /></div>
          <p className="text-xs text-fg-muted">Lower or unchanged: {fmt.pctRaw((1 - probability) * 100)}<br />Historical baseline: {result?.baseline_probability == null ? "Unavailable" : fmt.pctRaw(result.baseline_probability * 100)}</p>
          <p className="text-xs text-fg-muted">Direction probability only. No future price or candle is predicted.</p>
        </>}
        {metrics && <div className="border-t border-border pt-3 space-y-1">
          <p className={`text-sm font-medium ${beatBaseline ? "text-accent-green" : "text-accent-amber"}`}>{beatBaseline ? "Lower test error than baseline" : "No improvement over baseline"}</p>
          <p className="text-xs text-fg-muted">On {fmt.int(metrics.test_samples)} held-out days. This does not establish profitability.</p>
        </div>}
      </div>
    </div>
    {result && probability != null && <dl className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-4 border-t border-border pt-4">
      {FEATURES.map(([key, label]) => <div key={key}><dt className="text-xs text-fg-muted">{label}</dt><dd className="num text-sm font-medium mt-1">{result.latest_features[key] == null ? "Unavailable" : key === "relative_volume" ? `${fmt.num(result.latest_features[key])}x` : key === "volatility_20d" ? fmt.pctRaw(result.latest_features[key] * 100) : fmt.pct(result.latest_features[key] * 100)}</dd></div>)}
    </dl>}
    {metrics && <details className="border-t border-border pt-3 text-sm">
      <summary className="cursor-pointer text-fg-muted">Historical evaluation</summary>
      <div className="mt-3 space-y-3">
        <p className="text-xs text-fg-muted">Earlier data trained the model; later data tested it. Training: {fmt.int(metrics.train_samples)} days. Validation: {fmt.int(metrics.validation_samples)} days. Final test: {fmt.int(metrics.test_samples)} days.</p>
        <p className="text-xs">Probability error (Brier; lower is better): model <span className="num">{fmt.num(metrics.test.brier, 4)}</span>, historical baseline <span className="num">{fmt.num(metrics.test_baseline_brier, 4)}</span>.</p>
        <div className="overflow-x-auto"><table className="w-full text-left text-xs"><caption className="text-left text-fg-muted mb-2">Predicted probability vs actual upward closes in the final test</caption><thead><tr className="border-b border-border"><th className="py-2">Predicted</th><th>Actually rose</th><th>Days</th></tr></thead><tbody>{metrics.calibration_bins.map((b, i) => <tr key={i} className="border-b border-border"><td className="py-2 num">{fmt.pctRaw(b.mean_probability * 100)}</td><td className="num">{fmt.pctRaw(b.observed_frequency * 100)}</td><td className="num">{fmt.int(b.count)}</td></tr>)}</tbody></table></div>
      </div>
    </details>}
    <p className="text-xs text-fg-subtle">Research and decision-support only. Not financial advice.</p>
  </section>;
}
