import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { AlertTriangle, FlaskConical, Loader2, Play, RefreshCcw, TrendingUp, Zap } from "lucide-react";
import { methodAnalysisApi } from "@/api/client";
import type {
  AllMethodStatus,
  MethodRunResult,
  MethodSignalCard as MethodSignalCardType,
  MethodType,
  MethodTrainStatus,
  TrainMethodType,
} from "@/api/types";
import { MethodSignalCard } from "@/components/MethodSignalCard";
import { fmt, symbolDisplay } from "@/lib/format";

// ─── Column config ────────────────────────────────────────────────────────────

interface MethodConfig {
  id: MethodType;
  label: string;
  description: string;
  tagline: string;
  trainable: boolean;
  trainId?: TrainMethodType;
  estimatedTrainTime?: string;
}

const METHODS: MethodConfig[] = [
  {
    id: "rule_based",
    label: "Rule-Based",
    description: "Hand-rolled thresholds on RSI, MACD, EMA stack, ADX, volume and candlestick patterns.",
    tagline: "Deterministic · No training needed",
    trainable: false,
  },
  {
    id: "rf",
    label: "Random Forest",
    description: "Bagging ensemble — sklearn RandomForestClassifier on the same features and labels as GBM.",
    tagline: "RandomForest · ~6 min training",
    trainable: true,
    trainId: "rf",
    estimatedTrainTime: "≈ 6 min",
  },
  {
    id: "gbm",
    label: "GBM",
    description: "Gradient boosting — sklearn GradientBoostingClassifier (boosted trees, different bias/variance than RF).",
    tagline: "GradBoost · ~5 min training",
    trainable: true,
    trainId: "gbm",
    estimatedTrainTime: "≈ 5 min",
  },
  {
    id: "lstm",
    label: "LSTM Neural Net",
    description: "PyTorch LSTM reads 20-day sequences of RSI, MACD, volume, ATR and EMA distance.",
    tagline: "PyTorch · Sequence model · 30–90 min training",
    trainable: true,
    trainId: "lstm",
    estimatedTrainTime: "30–90 min",
  },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function statusBadge(status: MethodTrainStatus["status"]) {
  const map: Record<string, string> = {
    idle: "bg-bg-elevated text-fg-muted",
    training: "bg-accent-amber/15 text-accent-amber",
    ready: "bg-accent-green/15 text-accent-green",
    error: "bg-accent-red/15 text-accent-red",
  };
  const label: Record<string, string> = {
    idle: "Not trained",
    training: "Training…",
    ready: "Ready",
    error: "Error",
  };
  return (
    <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium uppercase tracking-wide ${map[status] ?? map.idle}`}>
      {label[status] ?? status}
    </span>
  );
}

function httpErrorDetail(err: unknown): string {
  const ax = err as {
    response?: { data?: { detail?: unknown } };
    message?: string;
  };
  const d = ax?.response?.data?.detail;
  if (typeof d === "string") return `(${d})`;
  if (typeof ax?.message === "string") return `(${ax.message})`;
  return "";
}

function TrainProgressBar({ progress, message }: { progress: number; message: string }) {
  const pct = Math.round(progress * 100);
  return (
    <div className="mt-2">
      <div className="flex justify-between text-[11px] text-fg-muted mb-1">
        <span className="truncate">{message || "Working…"}</span>
        <span className="num shrink-0 ml-2">{pct}%</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-bg-elevated overflow-hidden">
        <div
          className="h-full rounded-full bg-accent-amber transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ─── Per-column component ─────────────────────────────────────────────────────

function MethodColumn({
  config,
  trainStatus,
  onTrain,
  isTraining,
  liveRanks,
}: {
  config: MethodConfig;
  trainStatus: MethodTrainStatus;
  onTrain: () => void;
  isTraining: boolean;
  liveRanks: Map<string, number>;
}) {
  const queryClient = useQueryClient();
  const [result, setResult] = useState<MethodRunResult | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const runMut = useMutation({
    mutationFn: () => methodAnalysisApi.run(config.id),
    onSuccess: (data) => {
      setResult(data);
      setRunError(null);
      // Touch the status query so model-ready state refreshes after a run.
      queryClient.invalidateQueries({ queryKey: ["method-status"] });
    },
    onError: (err: unknown) => {
      const msg =
        err instanceof Error
          ? err.message
          : (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Unknown error";
      setRunError(msg);
    },
  });

  const isReady = trainStatus.status === "ready";
  const canRun = !config.trainable || isReady;
  const isRunning = runMut.isPending;

  const liveOverlap =
    result && liveRanks.size > 0
      ? {
          matched: result.signals.filter((s) => liveRanks.has(s.symbol)),
          denom: result.signals.length,
        }
      : null;

  return (
    <div className="flex flex-col gap-4 min-w-0">
      {/* Column header */}
      <div className="rounded-xl border border-border bg-bg-elevated p-4">
        <div className="flex items-center gap-2 mb-1">
          <FlaskConical className="size-4 text-accent-violet shrink-0" />
          <h2 className="font-semibold text-base">{config.label}</h2>
        </div>
        <p className="text-[13px] text-fg-muted leading-relaxed">{config.description}</p>
        <p className="mt-1 text-[11px] text-fg-subtle">{config.tagline}</p>

        {/* Training controls */}
        {config.trainable && (
          <div className="mt-3 pt-3 border-t border-border">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[12px] text-fg-muted">Model status</span>
              {statusBadge(trainStatus.status)}
            </div>

            {trainStatus.status === "training" && (
              <TrainProgressBar
                progress={trainStatus.progress}
                message={trainStatus.message}
              />
            )}

            {trainStatus.status === "ready" && trainStatus.metric_value != null && (
              <div className="mt-2 text-[12px] text-fg-muted">
                {trainStatus.metric_label}:{" "}
                <span className="text-accent-green font-semibold num">
                  {trainStatus.metric_value.toFixed(3)}
                </span>
              </div>
            )}

            {trainStatus.status === "error" && trainStatus.error && (
              <div className="mt-2 flex items-start gap-1.5 text-[12px] text-accent-red">
                <AlertTriangle className="size-3.5 mt-0.5 shrink-0" />
                <span className="line-clamp-2">{trainStatus.error}</span>
              </div>
            )}

            <button
              className="btn btn-primary mt-3 w-full text-sm"
              onClick={onTrain}
              disabled={isTraining || trainStatus.status === "training"}
            >
              {trainStatus.status === "training" ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  Training… {config.estimatedTrainTime}
                </>
              ) : (
                <>
                  <Zap className="size-4" />
                  {trainStatus.status === "ready" ? "Re-Train" : "Train Model"}
                  {config.estimatedTrainTime && (
                    <span className="text-[11px] opacity-70 ml-1">({config.estimatedTrainTime})</span>
                  )}
                </>
              )}
            </button>
          </div>
        )}

        {!config.trainable && (
          <div className="mt-3 pt-3 border-t border-border flex items-center gap-2">
            <span className="text-[12px] text-fg-muted">Model status</span>
            {statusBadge("ready")}
          </div>
        )}

        {/* Run Analysis button */}
        <button
          className="btn mt-3 w-full text-sm"
          onClick={() => runMut.mutate()}
          disabled={!canRun || isRunning}
          title={!canRun ? "Train the model first" : "Run analysis on all 50 Nifty stocks"}
        >
          {isRunning ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              Running…
            </>
          ) : result ? (
            <>
              <RefreshCcw className="size-4" />
              Re-run Analysis
            </>
          ) : (
            <>
              <Play className="size-4" />
              Start Analysis
            </>
          )}
        </button>
      </div>

      {/* Results */}
      {runError && (
        <div className="flex items-start gap-2 rounded-lg border border-accent-red/30 bg-accent-red/5 p-3 text-[13px] text-accent-red">
          <AlertTriangle className="size-4 mt-0.5 shrink-0" />
          {runError}
        </div>
      )}

      {isRunning && (
        <div className="flex items-center gap-2 text-fg-muted text-sm py-4 justify-center">
          <Loader2 className="size-4 animate-spin" />
          Scoring all 50 Nifty stocks…
        </div>
      )}

      {result && !isRunning && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between text-[11px] text-fg-subtle">
            <span>{result.signals.length} signals · sorted by confidence</span>
            <span className="num">
              {new Date(result.ran_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
            </span>
          </div>
          {liveOverlap && (
            <div className="rounded-md border border-accent-cyan/25 bg-accent-cyan/5 px-2 py-1.5 text-[11px] text-fg-muted">
              <span className="text-accent-cyan font-medium">Live overlap</span>
              {" · "}
              <span className="num font-semibold text-fg">
                {liveOverlap.matched.length}/{liveOverlap.denom}
              </span>
              {" "}
              symbols also in today&apos;s Upstox/yfinance top-mover list (not an accuracy measure — different
              data: live intraday vs EOD indicators).
            </div>
          )}
          {result.signals.map((card: MethodSignalCardType) => (
            <MethodSignalCard
              key={card.symbol}
              card={card}
              liveMoverRank={liveRanks.get(card.symbol) ?? null}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function MethodAnalysis() {
  const queryClient = useQueryClient();

  // Poll every 3s while this page is open. The previous design only polled when
  // status was already "training", so after clicking Train the cache stayed
  // idle (no refetch) and the UI looked broken.
  const { data: statusData } = useQuery({
    queryKey: ["method-status"],
    queryFn: () => methodAnalysisApi.status(),
    refetchInterval: 3000,
  });

  const trainMut = useMutation({
    mutationFn: (method: TrainMethodType) => methodAnalysisApi.train(method),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["method-status"] });
      void queryClient.refetchQueries({ queryKey: ["method-status"] });
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: ["method-status"] });
    },
  });

  const { data: liveMoversOut, isLoading: liveLoading, refetch: refetchLive, isFetching: liveFetching } =
    useQuery({
      queryKey: ["method-live-movers", 15],
      queryFn: () => methodAnalysisApi.liveMovers(15),
      staleTime: 60_000,
    });

  const liveRanks = useMemo(() => {
    const m = new Map<string, number>();
    liveMoversOut?.movers.forEach((r) => m.set(r.symbol, r.rank));
    return m;
  }, [liveMoversOut]);

  const getTrainStatus = (method: MethodType): MethodTrainStatus => {
    const fallback: MethodTrainStatus = {
      status: "idle",
      progress: 0,
      message: "",
      metric_label: "",
      metric_value: null,
      error: null,
      updated_at: null,
    };
    if (!statusData) return fallback;
    return statusData[method as keyof AllMethodStatus] ?? fallback;
  };

  return (
    <div className="max-w-[1400px] mx-auto px-4 py-6 space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Method Analysis</h1>
        <p className="text-fg-muted text-sm mt-1">
          Compare Rule-Based, Random Forest, gradient boosting (GBM), and LSTM side-by-side on Nifty 50.
          Train each ML model, then click <strong>Start Analysis</strong> to compare outputs and live-mover overlap.
        </p>
      </div>

      {/* Disclaimer */}
      <div className="flex items-start gap-2 rounded-lg border border-accent-amber/30 bg-accent-amber/5 p-3 text-[12px] text-accent-amber">
        <AlertTriangle className="size-4 mt-0.5 shrink-0" />
        <span>
          Research and decision-support only. Not financial advice.
          ML models are trained on historical data and do not guarantee future performance.
        </span>
      </div>

      {/* Live top movers (Upstox-first) — compare overlap with each method column */}
      <div className="rounded-xl border border-border bg-bg-elevated p-4">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
          <div className="flex items-center gap-2">
            <TrendingUp className="size-5 text-accent-cyan shrink-0" />
            <div>
              <h2 className="font-semibold text-sm">Today&apos;s Nifty 50 top movers (live)</h2>
              <p className="text-[12px] text-fg-muted mt-0.5">
                Same scoring as Live Analysis ({fmt.num(liveMoversOut?.movers.length ?? 0, 0)} shown). Quotes
                from{" "}
                <span className="text-fg">{liveMoversOut?.source === "upstox" ? "Upstox" : "yfinance (delayed)"}</span>. Method
                outputs use cached EOHLCV indicators — overlap counts are descriptive only.
              </p>
            </div>
          </div>
          <button
            type="button"
            className="btn text-sm shrink-0"
            onClick={() => void refetchLive()}
            disabled={liveFetching || liveLoading}
          >
            {liveFetching ? <Loader2 className="size-4 animate-spin" /> : <RefreshCcw className="size-4" />}
            Refresh movers
          </button>
        </div>
        {liveLoading && (
          <div className="flex items-center gap-2 text-fg-muted text-sm py-4">
            <Loader2 className="size-4 animate-spin" />
            Loading live movers…
          </div>
        )}
        {!liveLoading && liveMoversOut && liveMoversOut.movers.length === 0 && (
          <p className="text-sm text-accent-amber">No movers returned — ensure stock data refresh has run and market feed is available.</p>
        )}
        {!liveLoading && liveMoversOut && liveMoversOut.movers.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="text-fg-subtle border-b border-border">
                  <th className="py-1.5 pr-3 font-medium">#</th>
                  <th className="py-1.5 pr-3 font-medium">Symbol</th>
                  <th className="py-1.5 pr-3 font-medium num">%</th>
                  <th className="py-1.5 pr-3 font-medium num">LTP</th>
                  <th className="py-1.5 font-medium num hidden sm:table-cell">Score</th>
                </tr>
              </thead>
              <tbody>
                {liveMoversOut.movers.map((m) => (
                  <tr key={m.symbol} className="border-b border-border/60 last:border-0">
                    <td className="py-1 pr-3 num text-fg-muted">{m.rank}</td>
                    <td className="py-1 pr-3">{symbolDisplay(m.symbol)}</td>
                    <td className="py-1 pr-3 num">{fmt.pct(m.pct_change, 2)}</td>
                    <td className="py-1 pr-3 num">{fmt.inr(m.last_price)}</td>
                    <td className="py-1 num hidden sm:table-cell">{fmt.num(m.score, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {liveMoversOut?.disclaimer && (
          <p className="mt-3 text-[11px] text-fg-subtle">{liveMoversOut.disclaimer}</p>
        )}
      </div>

      {trainMut.isError && (
        <div className="flex items-start gap-2 rounded-lg border border-accent-red/30 bg-accent-red/5 p-3 text-[13px] text-accent-red">
          <AlertTriangle className="size-4 mt-0.5 shrink-0" />
          <span>
            Could not start training. Check that the backend is running and try again.{" "}
            {httpErrorDetail(trainMut.error)}
          </span>
        </div>
      )}

      {/* 3-column grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-6 items-start">
        {METHODS.map((cfg) => (
          <MethodColumn
            key={cfg.id}
            config={cfg}
            trainStatus={getTrainStatus(cfg.id)}
            onTrain={() => cfg.trainId && trainMut.mutate(cfg.trainId)}
            isTraining={trainMut.isPending}
            liveRanks={liveRanks}
          />
        ))}
      </div>
    </div>
  );
}
