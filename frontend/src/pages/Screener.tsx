import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import { CATEGORY_LABELS } from "@/api/types";
import { ScreenerTable } from "@/components/ScreenerTable";
import { Loader2, RefreshCw } from "lucide-react";

const PRICE_REFRESH_INTERVAL = 60_000;

const CATEGORIES = Object.keys(CATEGORY_LABELS);
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
  const [params, setParams] = useSearchParams();
  const category = params.get("category") ?? "";
  const sector = params.get("sector") ?? "All";
  const minScore = Number(params.get("min_score") ?? "0");

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
    }),
    [category, sector, minScore]
  );

  const { data, isLoading, isError } = useQuery({
    queryKey: ["screener", queryParams],
    queryFn: () => api.listScreener(queryParams),
  });

  const symbols = useMemo(() => {
    if (!data) return [] as string[];
    return [...new Set(data.map((r) => r.symbol))];
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

      <div className="card p-3 flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
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
