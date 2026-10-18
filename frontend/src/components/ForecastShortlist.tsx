import { useQueries, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, ChartNoAxesCombined, Loader2, RefreshCw } from "lucide-react";
import { api } from "@/api/client";
import type { DailyForecast } from "@/api/types";
import { fmt, symbolDisplay } from "@/lib/format";

const CANDIDATE_CATEGORIES = new Set(["MOMENTUM_LEADER", "FRESH_BREAKOUT", "INTRADAY_WATCH_TOMORROW"]);

export function ForecastShortlist() {
  const [includeWeaker, setIncludeWeaker] = useState(false);
  const candidatesQuery = useQuery({
    queryKey: ["forecast-candidates"],
    queryFn: () => api.listScreener({ limit: 500 }),
    staleTime: 300_000,
  });
  const candidates = useMemo(() => {
    const ranked = (candidatesQuery.data ?? []).filter((row) => CANDIDATE_CATEGORIES.has(row.category))
      .sort((a, b) => b.score - a.score || (b.adx ?? 0) - (a.adx ?? 0) || a.symbol.localeCompare(b.symbol));
    return ranked.filter((row, i) => ranked.findIndex((other) => other.symbol === row.symbol) === i).slice(0, 10);
  }, [candidatesQuery.data]);
  const forecasts = useQueries({ queries: candidates.map((row) => ({
    queryKey: ["daily-forecast", row.symbol],
    queryFn: () => api.getDailyForecast(row.symbol),
    staleTime: 300_000,
    retry: false,
  })) });
  const loading = candidatesQuery.isPending || forecasts.some((query) => query.isPending);
  const refreshing = candidatesQuery.isFetching || forecasts.some((query) => query.isFetching);
  const scored = forecasts.flatMap((query, index) => {
    const result = query.data;
    if (!result || result.probability_up == null || !result.metrics || !result.as_of) return [];
    const age = Date.now() - Date.parse(`${result.as_of}T15:30:00+05:30`);
    if (!Number.isFinite(age) || age < 0 || age > 7 * 86_400_000) return [];
    return [{ candidate: candidates[index], result, supported: result.probability_up > 0.5 && result.metrics.test.brier < result.metrics.test_baseline_brier }];
  });
  const supportedCount = scored.filter((row) => row.supported).length;
  const ranked = scored.filter((row) => includeWeaker || row.supported)
    .sort((a, b) => Number(b.supported) - Number(a.supported) || b.result.probability_up! - a.result.probability_up! || a.candidate.symbol.localeCompare(b.candidate.symbol)).slice(0, 5);
  const unavailable = candidates.length - scored.length;

  async function refresh() {
    await candidatesQuery.refetch();
    await Promise.allSettled(forecasts.map((query) => query.refetch()));
  }

  return <section className="card p-4 space-y-4" aria-labelledby="forecast-shortlist-title">
    <header className="flex items-start justify-between gap-3">
      <div>
        <h2 id="forecast-shortlist-title" className="font-semibold flex items-center gap-2"><ChartNoAxesCombined className="size-5 text-accent-cyan" />Forecast shortlist</h2>
        <p className="text-xs text-fg-muted mt-1">Next trading day's upward close | Daily probability model</p>
      </div>
      <button type="button" className="btn shrink-0" title="Refresh forecast shortlist" aria-label="Refresh forecast shortlist" disabled={refreshing} onClick={() => void refresh()}>
        <RefreshCw className={`size-4 ${refreshing ? "animate-spin" : ""}`} />
      </button>
    </header>
    <div className="flex flex-wrap justify-between items-center gap-2 text-xs">
      <p className="text-fg-muted">Top {fmt.int(candidates.length)} momentum / breakout candidates{!loading && ` | ${fmt.int(supportedCount)} upward forecasts beat baseline test error`}</p>
      <label className="flex items-center gap-2"><input type="checkbox" checked={includeWeaker} onChange={(event) => setIncludeWeaker(event.target.checked)} />Include weaker results</label>
    </div>
    {loading ? <div role="status" className="min-h-32 flex items-center justify-center gap-2 text-sm text-fg-muted"><Loader2 className="size-4 animate-spin" />Comparing daily forecasts...</div>
      : candidatesQuery.isError ? <p role="alert" className="text-sm text-accent-amber">Could not load candidates. Refresh to retry.</p>
      : candidates.length === 0 ? <p className="text-sm text-fg-muted">No momentum or breakout candidates in the latest screener run.</p>
      : ranked.length === 0 ? <p className="text-sm text-fg-muted">{scored.length ? "No upward forecasts beat baseline test error in this shortlist." : "No recent forecasts are available for these candidates."}</p>
      : <ol className="divide-y divide-border">
        {ranked.map(({ candidate, result, supported }, index) => <li key={candidate.symbol} className="py-3 first:pt-0 last:pb-0">
          <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-2">
            <div className="min-w-0">
              <Link to={`/stock/${encodeURIComponent(candidate.symbol)}#daily-forecast`} className="inline-flex items-center gap-2 font-semibold text-sm text-accent-cyan hover:underline">
                <span className="num text-xs text-fg-subtle">{fmt.int(index + 1)}</span>{symbolDisplay(candidate.symbol)}<ArrowUpRight className="size-3.5 shrink-0" />
              </Link>
              <p className="text-xs text-fg-muted mt-1 break-words">{candidate.name ?? candidate.sector}</p>
            </div>
            <div className="text-right"><p className="num text-xl font-semibold">{fmt.pctRaw(result.probability_up! * 100)}</p><p className="text-xs text-fg-muted">chance of rising</p></div>
            <div className="col-span-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
              <span className="text-fg-muted">Historical baseline <span className="num text-fg">{result.baseline_probability == null ? "Unavailable" : fmt.pctRaw(result.baseline_probability * 100)}</span></span>
              <span className="text-fg-muted">5-day change <span className="num text-fg">{result.latest_features.return_5d == null ? "Unavailable" : fmt.pct(result.latest_features.return_5d * 100)}</span></span>
              <span className={supported ? "text-accent-green" : "text-accent-amber"} title={testSummary(result)}>{supported ? "Lower test error" : "Weak / no upward edge"}</span>
              <span className="text-fg-subtle">As of {result.as_of}</span>
            </div>
          </div>
        </li>)}
      </ol>}
    {!loading && unavailable > 0 && <p className="text-xs text-accent-amber">{fmt.int(unavailable)} candidates omitted: unavailable, incomplete or older than seven days.</p>}
    <footer className="border-t border-border pt-3 space-y-1 text-xs text-fg-subtle">
      <p>Lower test error first, then upward probability. Probabilities are not expected returns; this shortlist is not a profitability test.</p>
      <p>Research and decision-support only. Not financial advice.</p>
    </footer>
  </section>;
}

function testSummary(result: DailyForecast) {
  return result.metrics ? `Held-out probability error (Brier; lower is better): ${fmt.num(result.metrics.test.brier, 4)} vs baseline ${fmt.num(result.metrics.test_baseline_brier, 4)} over ${fmt.int(result.metrics.test_samples)} days.` : "No test results";
}
