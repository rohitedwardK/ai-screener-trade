import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play, Activity, Info } from "lucide-react";
import { liveApi } from "@/api/client";
import { MarketRegimeBanner } from "@/components/live/MarketRegimeBanner";
import { TopMoversLadder } from "@/components/live/TopMoversLadder";
import { ObservationCard } from "@/components/live/ObservationCard";
import { DecisionsFeed } from "@/components/live/DecisionsFeed";
import { useAppMode } from "@/lib/appMode";

const POLL_MS = 30_000;

export function LiveAnalysis() {
  const qc = useQueryClient();
  const mode = useAppMode((s) => s.mode);

  const { data: dashboard, isLoading } = useQuery({
    queryKey: ["live-dashboard"],
    queryFn: liveApi.getDashboard,
    refetchInterval: POLL_MS,
  });

  const tickMut = useMutation({
    mutationFn: liveApi.tick,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["live-dashboard"] }),
  });

  if (isLoading || !dashboard) {
    return (
      <div className="card p-8 text-center text-fg-muted">
        <Loader2 className="size-5 animate-spin mx-auto mb-2" />
        Loading Live Analysis dashboard…
      </div>
    );
  }

  const { config, market_snapshot, active_observations, recent_decisions, market_open } =
    dashboard;
  const observingSymbols = new Set(
    active_observations
      .filter((o) => o.status === "OBSERVING")
      .map((o) => o.symbol),
  );

  const observingList = active_observations.filter((o) => o.status === "OBSERVING");
  const cooldownList = active_observations.filter((o) => o.status === "COOLDOWN");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-fg flex items-center gap-2">
            <Activity className="size-5 text-accent-green" />
            Live Analysis
          </h1>
          <p className="text-sm text-fg-muted">
            Real-time scan of Nifty 50 every {config.poll_interval_min} min,
            with {config.observation_samples}-sample / 15-min observation
            windows scored by the Multi-Factor Confluence model.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {mode === "HISTORICAL" && (
            <div className="text-xs text-accent-amber inline-flex items-center gap-1.5">
              <Info className="size-3.5" />
              <span>Switch to Live mode in the header to enable the scheduler.</span>
            </div>
          )}
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => tickMut.mutate()}
            disabled={tickMut.isPending}
            title="Manually run one Live Analysis tick"
          >
            {tickMut.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Play className="size-4" />
            )}
            <span>Run tick</span>
          </button>
        </div>
      </div>

      <MarketRegimeBanner snapshot={market_snapshot} marketOpen={market_open} />

      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-12 lg:col-span-7">
          <TopMoversLadder
            movers={market_snapshot?.top_movers ?? []}
            observingSymbols={observingSymbols}
          />
        </div>
        <div className="col-span-12 lg:col-span-5">
          <div className="card p-4 h-full">
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="text-sm font-semibold text-fg">
                  Active Observations
                </div>
                <div className="text-xs text-fg-muted">
                  {observingList.length} open · {cooldownList.length} in cooldown
                </div>
              </div>
              <span className="badge badge-blue">
                {config.observation_samples} samples / window
              </span>
            </div>
            {observingList.length === 0 ? (
              <div className="text-center text-sm text-fg-muted py-8">
                No open windows. The next tick will promote eligible movers.
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {observingList.map((o) => (
                  <ObservationCard
                    key={o.id}
                    observation={o}
                    pollIntervalMin={config.poll_interval_min}
                    observationSamples={config.observation_samples}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <DecisionsFeed decisions={recent_decisions} />

      <div className="text-xs text-fg-muted px-1">
        {dashboard.disclaimer}
      </div>
    </div>
  );
}
