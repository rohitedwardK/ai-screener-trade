import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, liveVerificationApi, qualityApi } from "@/api/client";
import { fmt, symbolDisplay } from "@/lib/format";
import { CATEGORY_LABELS, LIVE_STATUS_LABEL, LIVE_STATUS_TONE } from "@/api/types";
import type {
  LiveVerificationStatus,
  LiveVerificationSummary,
} from "@/api/types";
import { ScreenerTable } from "@/components/ScreenerTable";
import { LiveVerificationBanner } from "@/components/LiveVerificationBanner";
import { BrainCircuit, Loader2, RefreshCw } from "lucide-react";

const PRICE_REFRESH_INTERVAL = 60_000;
const LIVE_SUMMARY_REFRESH_INTERVAL = 90_000;

const CATEGORIES = Object.keys(CATEGORY_LABELS);
const LIVE_STATUSES: LiveVerificationStatus[] = [
  "STRENGTHENED",
  "CONFIRMED",
  "WEAKENING",
  "INVALIDATED",
];
const SECTORS = [
  "All",
  "IT",
  "Financial Services",
  "FMCG",
  "Energy",
  "Auto",
  "Pharma",
  "Metals & Mining",
  "Power",
  "Consumer Durables",
  "Construction",
  "Cement",
  "Telecom",
  "Healthcare",
  "Services",
];

export function Screener() {
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const category = params.get("category") ?? "";
  const sector = params.get("sector") ?? "All";
  const minScore = Number(params.get("min_score") ?? "0");
  const liveStatus = params.get("live_status") ?? "";
  const includeInvalidated = params.get("include_invalidated") === "1";
  const [isReverifying, setIsReverifying] = useState(false);
  const [trainingSource, setTrainingSource] = useState<"archive" | "historical">("historical");
  const quality = useQuery({
    queryKey: ["trade-quality-status"], queryFn: qualityApi.status,
    refetchInterval: query => query.state.data?.status === "training" ? 2000 : 30000,
  });
  const trainQuality = useMutation({
    mutationFn: qualityApi.train,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["trade-quality-status"] }),
  });
  useEffect(() => {
    if (quality.data && quality.data.status !== "training") {
      void queryClient.invalidateQueries({ queryKey: ["screener"] });
    }
  }, [quality.data?.status, quality.data?.model, queryClient]);

  const setParam = (k: string, v: string | null) => {
    const next = new URLSearchParams(params);
    if (v == null || v === "") next.delete(k);
    else next.set(k, v);
    setParams(next, { replace: true });
  };

  const queryParams = useMemo(
    () => ({
      category: category || undefined,
      min_score: minScore || 0,
      sector: sector !== "All" ? sector : undefined,
      limit: 200,
      // Filtering by INVALIDATED implicitly forces include_invalidated on the
      // backend; we still mirror it here so the URL shows consistent state.
      include_invalidated:
        includeInvalidated || liveStatus === "INVALIDATED" ? true : undefined,
      live_status: liveStatus || undefined,
    }),
    [category, sector, minScore, liveStatus, includeInvalidated]
  );

  const { data, isLoading, isError } = useQuery({
    queryKey: ["screener", queryParams],
    queryFn: () => api.listScreener(queryParams),
  });

  const { data: liveSummary } = useQuery<LiveVerificationSummary>({
    queryKey: ["live-verification-summary"],
    queryFn: () => liveVerificationApi.summary(),
    refetchInterval: LIVE_SUMMARY_REFRESH_INTERVAL,
  });

  const handleReverify = async () => {
    if (isReverifying) return;
    setIsReverifying(true);
    try {
      await liveVerificationApi.run(true);
      // Re-fetching the summary immediately would race the background job;
      // the next 90s tick or a manual table refresh will pick the fresh row up.
      await queryClient.invalidateQueries({
        queryKey: ["live-verification-summary"],
      });
    } finally {
      setIsReverifying(false);
    }
  };

  const symbols = useMemo(() => {
    if (!data) return [] as string[];
    return [...new Set(data.map((r) => r.symbol))];
  }, [data]);
  const focusCandidates = useMemo(() => {
    const ranked = (data ?? []).filter((row) => ["MOMENTUM_LEADER", "FRESH_BREAKOUT", "INTRADAY_WATCH_TOMORROW"].includes(row.category))
      .sort((a, b) => b.score - a.score || (b.adx ?? 0) - (a.adx ?? 0));
    return ranked.filter((row, index) => ranked.findIndex((other) => other.symbol === row.symbol) === index).slice(0, 5);
  }, [data]);

  const {
    data: priceMap,
    dataUpdatedAt,
    isFetching: isPriceFetching,
  } = useQuery({
    queryKey: ["screener-prices", symbols],
    queryFn: () => api.getPrices(symbols),
    enabled: symbols.length > 0,
    refetchInterval: PRICE_REFRESH_INTERVAL,
    refetchIntervalInBackground: true,
  });

  const [countdown, setCountdown] = useState(PRICE_REFRESH_INTERVAL / 1000);

  useEffect(() => {
    setCountdown(PRICE_REFRESH_INTERVAL / 1000);
  }, [dataUpdatedAt]);

  useEffect(() => {
    if (symbols.length === 0) return;
    const id = setInterval(() => {
      setCountdown((s) => (s <= 1 ? PRICE_REFRESH_INTERVAL / 1000 : s - 1));
    }, 1000);
    return () => clearInterval(id);
  }, [symbols.length]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 border-b border-border pb-3 text-sm">
        <label className="text-xs text-fg-muted">Quality training source
          <select className="input block mt-1" value={trainingSource} disabled={quality.data?.status === "training"} onChange={(event) => setTrainingSource(event.target.value as "archive" | "historical")}>
            <option value="historical">5-year historical reconstruction</option>
            <option value="archive">Recorded observations</option>
          </select>
        </label>
        <button className="btn" type="button" onClick={() => trainQuality.mutate(trainingSource)}
          disabled={trainQuality.isPending || quality.data?.status === "training"}>
          <BrainCircuit className="size-4" />
          {quality.data?.status === "training" ? "Training quality model" : "Train quality model"}
        </button>
        <span className="text-fg-muted" role="status">{quality.data?.message}</span>
        {quality.data?.model && <span className="num text-xs text-fg-muted">
          {quality.data.model.source === "historical" ? "Reconstructed history" : "Recorded observations"}{" | "}
          {fmt.num(quality.data.model.samples, 0)} samples · Test AUC {fmt.num(quality.data.model.test_auc, 3)}
          {" · "}Brier {fmt.num(quality.data.model.test_brier, 3)} / baseline {fmt.num(quality.data.model.baseline_brier, 3)}
        </span>}
        {(quality.isError || trainQuality.isError) && <span role="alert" className="text-accent-red">Quality service unavailable. Retry training or refresh.</span>}
      </div>
      {quality.data?.data && <section className="border-b border-border pb-4 space-y-2 text-sm">
        <p><span className="font-medium">Daily price coverage: </span>{fmt.int(quality.data.data.coverage.filter((row) => row.five_year_span).length)} / {fmt.int(quality.data.data.coverage.length)} configured stocks span five years.</p>
        <p className="text-xs text-fg-muted">Recorded signal archive: {fmt.int(quality.data.data.archive_observations)} observations across {fmt.int(quality.data.data.archive_dates)} dates. Recorded-observation training needs at least {fmt.int(quality.data.data.required_dates)} mature dates plus five subsequent trading sessions for each outcome.</p>
        <p className="text-xs text-fg-muted">Historical training rebuilds weekly setups from cached daily prices. These are reconstructed observations, not historical live-verification records. Testing uses later dates; today's stock universe introduces survivorship bias.</p>
        {quality.data.model?.limitations && <p className="text-xs text-accent-amber">{quality.data.model.limitations}</p>}
        <details><summary className="cursor-pointer text-xs text-fg-muted">Per-stock data coverage</summary><div className="overflow-x-auto mt-2">
          <table className="w-full text-xs text-left"><thead><tr className="border-b border-border"><th className="py-2">Stock</th><th>Daily rows</th><th>First date</th><th>Last date</th><th>Checks</th></tr></thead><tbody>
            {quality.data.data.coverage.map((row) => <tr key={row.symbol} className="border-b border-border"><td className="py-2"><Link className="text-accent-cyan" to={`/stock/${encodeURIComponent(row.symbol)}#daily-forecast`}>{symbolDisplay(row.symbol)}</Link></td><td className="num">{fmt.int(row.rows)}</td><td>{row.start ?? "Unavailable"}</td><td>{row.end ?? "Unavailable"}</td><td>{row.missing_values || row.duplicate_dates ? "Incomplete / duplicate rows" : row.stale ? "Stale cache" : row.five_year_span ? "Five-year span" : "Short history"}</td></tr>)}
          </tbody></table>
        </div></details>
      </section>}
      {focusCandidates.length > 0 && <section className="border-b border-border pb-4 space-y-2">
        <h2 className="font-semibold text-sm">Momentum research shortlist</h2>
        <div className="divide-y divide-border">
          {focusCandidates.map((row) => <div key={row.symbol} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
            <div><span className="font-medium">{symbolDisplay(row.symbol)}</span><span className="text-xs text-fg-muted ml-2">{CATEGORY_LABELS[row.category]} | Score {fmt.num(row.score, 0)}</span></div>
            <Link className="text-accent-cyan text-xs underline" to={`/stock/${encodeURIComponent(row.symbol)}#daily-forecast`}>View forecast and price history</Link>
          </div>)}
        </div>
      </section>}
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Screener</h1>
          <p className="text-fg-muted text-sm mt-1">
            All matched signals from the latest run. Live prices auto-refresh
            every {PRICE_REFRESH_INTERVAL / 1000}s. Click any column header to
            sort.
          </p>
        </div>
        {symbols.length > 0 && (
          <span className="flex items-center gap-1.5 text-xs text-fg-muted">
            <RefreshCw
              className={`size-3 ${isPriceFetching ? "animate-spin" : ""}`}
            />
            Price refresh in {countdown}s
          </span>
        )}
      </div>

      <LiveVerificationBanner
        summary={liveSummary}
        onRerun={handleReverify}
        rerunDisabled={isReverifying}
      />

      <div className="card p-3 space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-fg-muted">Category</span>
            <button
              onClick={() => setParam("category", null)}
              className={`chip ${!category ? "chip-active" : ""}`}
            >
              All
            </button>
            {CATEGORIES.map((c) => (
              <button
                key={c}
                onClick={() => setParam("category", c)}
                className={`chip ${category === c ? "chip-active" : ""}`}
              >
                {CATEGORY_LABELS[c]}
              </button>
            ))}
          </div>

          <div className="ml-auto flex items-center gap-3">
            <label className="text-xs text-fg-muted flex items-center gap-2">
              Sector
              <select
                className="input"
                value={sector}
                onChange={(e) => setParam("sector", e.target.value)}
              >
                {SECTORS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>

            <label className="text-xs text-fg-muted flex items-center gap-2">
              Min score
              <input
                type="number"
                min={0}
                max={100}
                step={5}
                value={minScore}
                onChange={(e) => setParam("min_score", e.target.value || "0")}
                className="input w-20 num text-right"
              />
            </label>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3 pt-3 border-t border-border">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-fg-muted">Live status</span>
            <button
              onClick={() => setParam("live_status", null)}
              className={`chip ${!liveStatus ? "chip-active" : ""}`}
            >
              Any
            </button>
            {LIVE_STATUSES.map((s) => (
              <button
                key={s}
                onClick={() => setParam("live_status", liveStatus === s ? null : s)}
                className={`chip ${liveStatus === s ? "chip-active" : ""}`}
                title={`Filter to ${LIVE_STATUS_LABEL[s]} signals only · tone: ${LIVE_STATUS_TONE[s]}`}
              >
                {LIVE_STATUS_LABEL[s]}
              </button>
            ))}
          </div>

          <label className="ml-auto text-xs text-fg-muted flex items-center gap-2 select-none">
            <input
              type="checkbox"
              checked={includeInvalidated}
              onChange={(e) =>
                setParam("include_invalidated", e.target.checked ? "1" : null)
              }
              disabled={liveStatus === "INVALIDATED"}
            />
            Show invalidated
            {liveStatus === "INVALIDATED" && (
              <span className="text-fg-subtle">(forced by filter)</span>
            )}
          </label>
        </div>
      </div>

      {isLoading && (
        <div className="card p-12 flex items-center justify-center text-fg-muted">
          <Loader2 className="size-5 animate-spin mr-2" />
          Loading…
        </div>
      )}

      {isError && (
        <div className="card p-6 text-accent-red">Failed to load screener.</div>
      )}

      {data && <ScreenerTable rows={data} livePrices={priceMap} />}
    </div>
  );
}
