import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, liveVerificationApi } from "@/api/client";
import {
  CATEGORY_DESCRIPTIONS,
  CATEGORY_LABELS,
  CATEGORY_TONE,
} from "@/api/types";
import { StockCard } from "@/components/StockCard";
import { Badge } from "@/components/Badge";
import { LiveVerificationBanner } from "@/components/LiveVerificationBanner";
import { DailyBriefingPanel } from "@/components/agents/DailyBriefingPanel";
import { Loader2, RefreshCw, Sparkles, TrendingUp } from "lucide-react";

const PRICE_REFRESH_INTERVAL = 60_000;
const LIVE_SUMMARY_REFRESH_INTERVAL = 90_000;

export function Dashboard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["categories"],
    queryFn: () => api.categories(3),
  });

  const symbols = useMemo(() => {
    if (!data) return [];
    return [...new Set(data.flatMap((c) => c.top.map((r) => r.symbol)))];
  }, [data]);

  const {
    data: priceMap,
    dataUpdatedAt,
    isFetching: isPriceFetching,
  } = useQuery({
    queryKey: ["dashboard-prices", symbols],
    queryFn: () => api.getPrices(symbols),
    enabled: symbols.length > 0,
    refetchInterval: PRICE_REFRESH_INTERVAL,
    refetchIntervalInBackground: true,
  });

  const { data: liveSummary } = useQuery({
    queryKey: ["live-verification-summary"],
    queryFn: () => liveVerificationApi.summary(),
    refetchInterval: LIVE_SUMMARY_REFRESH_INTERVAL,
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

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh] text-fg-muted gap-2">
        <Loader2 className="size-5 animate-spin" />
        Loading dashboard…
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="card p-6 text-fg-muted">
        Backend unreachable. Start the API and click Refresh in the header to seed data.
      </div>
    );
  }

  const totalSignals = data.reduce((acc, c) => acc + c.count, 0);
  const isEmpty = totalSignals === 0;

  return (
    <div className="space-y-6">
      <section className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Sparkles className="size-6 text-accent-violet" />
            Today's Screener
          </h1>
          <p className="text-fg-muted text-sm mt-1">
            Rule-based scoring across the Nifty 50 universe, updated daily after
            market hours.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Badge tone="violet">
            <TrendingUp className="size-3" />
            <span>{totalSignals} signals across {data.length} buckets</span>
          </Badge>
          {symbols.length > 0 && (
            <span className="flex items-center gap-1.5 text-xs text-fg-muted">
              <RefreshCw
                className={`size-3 ${isPriceFetching ? "animate-spin" : ""}`}
              />
              Price refresh in {countdown}s
            </span>
          )}
          <Link to="/screener" className="btn btn-primary">
            Open full screener
          </Link>
        </div>
      </section>

      <DailyBriefingPanel compact />

      <LiveVerificationBanner summary={liveSummary} />


      {isEmpty && (
        <div className="card p-6 text-fg-muted">
          No signals yet. Click <strong>Refresh</strong> in the top right to fetch
          data and populate the dashboard. The first run takes about 30–90 seconds.
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {data.map((cat) => (
          <div key={cat.category} className="card p-4 flex flex-col gap-3">
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="font-semibold">
                    {CATEGORY_LABELS[cat.category] ?? cat.category}
                  </h2>
                  <Badge tone={CATEGORY_TONE[cat.category] ?? "muted"}>
                    {cat.count}
                  </Badge>
                </div>
                <p className="text-xs text-fg-muted mt-0.5">
                  {CATEGORY_DESCRIPTIONS[cat.category] ?? ""}
                </p>
              </div>
              <Link
                to={`/screener?category=${cat.category}`}
                className="text-xs text-accent-blue hover:underline shrink-0"
              >
                See all →
              </Link>
            </div>
            <div className="grid gap-2">
              {cat.top.length === 0 ? (
                <div className="text-xs text-fg-subtle py-2">
                  No matching stocks today.
                </div>
              ) : (
                cat.top.map((row) => (
                  <StockCard
                    key={row.symbol}
                    row={row}
                    livePrice={priceMap?.[row.symbol]}
                  />
                ))
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
