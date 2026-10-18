import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Loader2, Microscope } from "lucide-react";
import { useState } from "react";
import { api } from "@/api/client";
import { CATEGORY_TONE } from "@/api/types";
import { Badge } from "@/components/Badge";
import { IntradayCandleChart } from "@/components/IntradayCandleChart";
import { fmt, regimeTone, scoreTone } from "@/lib/format";

const SCALP_LABELS: Record<string, string> = {
  RANGE_BOUNCE_LONG: "Range bounce (long)",
  RANGE_BOUNCE_SHORT: "Range bounce (short)",
  FALSE_BREAKOUT_LONG: "False breakout (long)",
  FALSE_BREAKOUT_SHORT: "False breakout (short)",
  VWAP_RECLAIM_LONG: "VWAP reclaim (long)",
  VWAP_RECLAIM_SHORT: "VWAP reclaim (short)",
  MOMENTUM_BREAKOUT_LONG: "Momentum breakout (long)",
  MOMENTUM_BREAKDOWN_SHORT: "Momentum breakdown (short)",
  EMA_PULLBACK_LONG: "EMA pullback (long)",
  EMA_PULLBACK_SHORT: "EMA pullback (short)",
};

function formatPx(n: number | null | undefined, currency: "INR" | "USD"): string {
  if (currency === "USD") {
    const formatted = fmt.num(n);
    return formatted === "—" ? formatted : `$${formatted}`;
  }
  return fmt.inr(n);
}

export function IntradayAnalysisPanel({
  symbol,
  signalId,
  currency = "INR",
}: {
  symbol: string;
  signalId?: number;
  currency?: "INR" | "USD";
}) {
  const [open, setOpen] = useState(false);

  const analysis = useQuery({
    queryKey: ["intraday-analysis", symbol, signalId ?? "none"],
    queryFn: () => api.getIntradayAnalysis(symbol, signalId),
    enabled: open,
    staleTime: 60_000,
  });

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h3 className="font-semibold text-sm">15-minute analysis</h3>
          <p className="text-xs text-fg-muted mt-0.5">
            Intraday candlesticks, patterns, and quick scalp ideas.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="btn btn-primary text-xs gap-1.5"
        >
          <Microscope className="size-3.5" />
          {open ? "Hide" : "Analyse 15m"}
          {open ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
        </button>
      </div>

      {open && (
        <div className="mt-4 space-y-4 rounded-lg border border-border bg-bg-elevated/40 p-4">
          {analysis.isLoading && (
            <div className="flex items-center gap-2 text-sm text-fg-muted py-6 justify-center">
              <Loader2 className="size-4 animate-spin" />
              Loading 15-minute chart and scalp patterns…
            </div>
          )}

          {analysis.isError && (
            <div className="text-sm text-accent-red">
              Could not load intraday analysis. Check that the API is running and Upstox
              or Yahoo data is available.
            </div>
          )}

          {analysis.data && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="blue">15m · {analysis.data.source}</Badge>
                <Badge tone={regimeTone(analysis.data.regime)}>
                  {analysis.data.regime.replace(/_/g, " ")}
                </Badge>
                {analysis.data.rsi != null && (
                  <Badge tone="muted">RSI {fmt.num(analysis.data.rsi, 0)}</Badge>
                )}
                {analysis.data.atr != null && (
                  <Badge tone="muted">ATR {fmt.num(analysis.data.atr)}</Badge>
                )}
                {analysis.data.aligned_with_signal != null && (
                  <Badge tone={analysis.data.aligned_with_signal ? "green" : "amber"}>
                    {analysis.data.aligned_with_signal
                      ? "Aligned with top EOD signal"
                      : "Differs from top EOD signal"}
                  </Badge>
                )}
              </div>

              {analysis.data.patterns.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {analysis.data.patterns.map((p) => (
                    <span key={p} className="chip chip-active cursor-default text-[11px]">
                      {p}
                    </span>
                  ))}
                </div>
              )}

              <IntradayCandleChart
                candles={analysis.data.bars}
                support={analysis.data.support}
                resistance={analysis.data.resistance}
                vwap={analysis.data.vwap}
              />

              {analysis.data.scalps.length === 0 ? (
                <p className="text-sm text-fg-muted">
                  No quick scalp setup on the latest 15m bar — range/trend filters did not
                  align. Re-open after the next 15m close.
                </p>
              ) : (
                <div className="grid gap-3">
                  {analysis.data.scalps.slice(0, 4).map((scalp) => (
                    <div
                      key={`${scalp.category}-${scalp.direction}`}
                      className="rounded-lg border border-border bg-bg p-3"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                        <div className="flex flex-wrap gap-1.5">
                          <Badge tone={CATEGORY_TONE[scalp.category] ?? "violet"}>
                            {SCALP_LABELS[scalp.category] ?? scalp.category.replace(/_/g, " ")}
                          </Badge>
                          <Badge tone={scalp.direction === "LONG" ? "green" : "red"}>
                            {scalp.direction}
                          </Badge>
                          <Badge tone="muted">~{scalp.hold_minutes} min hold</Badge>
                        </div>
                        <Badge tone={scoreTone(scalp.score)}>
                          Score {fmt.num(scalp.score, 0)}
                        </Badge>
                      </div>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
                        <div>
                          <div className="text-fg-subtle">Entry</div>
                          <div className="num">{formatPx(scalp.entry, currency)}</div>
                        </div>
                        <div>
                          <div className="text-fg-subtle">Stop</div>
                          <div className="num text-accent-red">
                            {formatPx(scalp.stop_loss, currency)}
                          </div>
                        </div>
                        <div>
                          <div className="text-fg-subtle">Target 1</div>
                          <div className="num text-accent-green">
                            {formatPx(scalp.target_1, currency)}
                          </div>
                        </div>
                        <div>
                          <div className="text-fg-subtle">Target 2</div>
                          <div className="num text-accent-green">
                            {formatPx(scalp.target_2, currency)}
                          </div>
                        </div>
                      </div>
                      <div className="text-[11px] text-fg-muted mt-2">
                        Invalidation {formatPx(scalp.invalidation, currency)}
                      </div>
                      {scalp.reasons.length > 0 && (
                        <ul className="text-xs text-fg-muted mt-2 list-disc ml-4 space-y-0.5">
                          {scalp.reasons.map((r, i) => (
                            <li key={i}>{r}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              )}

              <p className="text-xs text-fg-subtle">{analysis.data.disclaimer}</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
