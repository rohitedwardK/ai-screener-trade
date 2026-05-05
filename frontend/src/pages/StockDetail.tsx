import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import { CATEGORY_LABELS, CATEGORY_TONE } from "@/api/types";
import { Badge } from "@/components/Badge";
import { PriceChart } from "@/components/PriceChart";
import { IndicatorPanel } from "@/components/IndicatorPanel";
import { AIExplain } from "@/components/AIExplain";
import { fmt, regimeTone, scoreTone, symbolDisplay } from "@/lib/format";
import { ArrowLeft, Loader2 } from "lucide-react";

const RANGES = ["3m", "6m", "1y", "2y", "5y"];

export function StockDetail() {
  const { symbol = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const range = params.get("range") ?? "1y";

  const detail = useQuery({
    queryKey: ["stock", symbol],
    queryFn: () => api.getStock(symbol),
    enabled: !!symbol,
  });

  const history = useQuery({
    queryKey: ["history", symbol, range],
    queryFn: () => api.getHistory(symbol, range),
    enabled: !!symbol,
  });

  if (detail.isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh] gap-2 text-fg-muted">
        <Loader2 className="size-5 animate-spin" />
        Loading {symbolDisplay(symbol)}…
      </div>
    );
  }

  if (detail.isError || !detail.data) {
    return (
      <div className="card p-6 text-accent-red">
        Could not load {symbol}. The stock might not be in the universe yet — run
        a refresh first.
      </div>
    );
  }

  const { stock, snapshot, signals } = detail.data;
  const topSignal = signals[0];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Link to="/screener" className="btn">
          <ArrowLeft className="size-4" /> Back
        </Link>
      </div>

      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-baseline gap-3 flex-wrap">
            <h1 className="text-3xl font-semibold tracking-tight">
              {symbolDisplay(stock.symbol)}
            </h1>
            <span className="text-fg-muted">{stock.name ?? ""}</span>
            {stock.sector && <Badge tone="muted">{stock.sector}</Badge>}
          </div>
          {snapshot && (
            <div className="mt-2 flex items-center gap-3 flex-wrap">
              <Badge tone={regimeTone(snapshot.regime)}>
                {snapshot.regime.replace(/_/g, " ")}
              </Badge>
              {topSignal && (
                <>
                  <Badge tone={CATEGORY_TONE[topSignal.category] ?? "muted"}>
                    {CATEGORY_LABELS[topSignal.category] ?? topSignal.category}
                  </Badge>
                  <Badge tone={scoreTone(topSignal.score)}>
                    Score {fmt.num(topSignal.score, 0)}
                  </Badge>
                  <Badge tone="muted">
                    Conf {fmt.num(topSignal.confidence * 100, 0)}%
                  </Badge>
                </>
              )}
              <span className="text-xs text-fg-subtle">
                As of {snapshot.as_of_date}
              </span>
            </div>
          )}
        </div>
        {snapshot && (
          <div className="text-right">
            <div className="text-3xl num font-semibold">
              {fmt.inr(snapshot.close)}
            </div>
            {snapshot.indicators_json?.["return_20d"] != null && (
              <div
                className={`num text-sm ${
                  (snapshot.indicators_json["return_20d"] ?? 0) >= 0
                    ? "text-accent-green"
                    : "text-accent-red"
                }`}
              >
                {fmt.pct(snapshot.indicators_json["return_20d"])} (20d)
              </div>
            )}
          </div>
        )}
      </header>

      <div className="flex items-center gap-2 flex-wrap">
        {RANGES.map((r) => (
          <button
            key={r}
            onClick={() => {
              const next = new URLSearchParams(params);
              next.set("range", r);
              setParams(next, { replace: true });
            }}
            className={`chip ${range === r ? "chip-active" : ""}`}
          >
            {r}
          </button>
        ))}
      </div>

      <PriceChart candles={history.data ?? []} />

      {snapshot && <IndicatorPanel snapshot={snapshot} />}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 space-y-4">
          {topSignal ? (
            <div className="card p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-semibold">Top signal</h3>
                <Badge tone={CATEGORY_TONE[topSignal.category] ?? "muted"}>
                  {CATEGORY_LABELS[topSignal.category] ?? topSignal.category}
                </Badge>
              </div>

              {topSignal.entry != null && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <div>
                    <div className="text-[11px] uppercase text-fg-muted">Entry</div>
                    <div className="num font-semibold text-lg">
                      {fmt.inr(topSignal.entry)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase text-fg-muted">
                      Stop loss
                    </div>
                    <div className="num font-semibold text-lg text-accent-red">
                      {fmt.inr(topSignal.stop_loss)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase text-fg-muted">Target 1</div>
                    <div className="num font-semibold text-lg text-accent-green">
                      {fmt.inr(topSignal.target_1)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase text-fg-muted">Target 2</div>
                    <div className="num font-semibold text-lg text-accent-green">
                      {fmt.inr(topSignal.target_2)}
                    </div>
                  </div>
                </div>
              )}

              {topSignal.reasons_json?.length > 0 && (
                <div className="mt-4">
                  <div className="text-xs uppercase tracking-wide text-fg-muted mb-2">
                    Why this signal
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {topSignal.reasons_json.map((r, i) => (
                      <span
                        key={i}
                        className="chip chip-active cursor-default"
                      >
                        {r}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="card p-4 text-fg-muted text-sm">
              No active signal for this stock — it didn't pass any rule thresholds in
              the latest run.
            </div>
          )}

          {signals.length > 1 && (
            <div className="card p-4">
              <h3 className="font-semibold mb-3">Other signals</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {signals.slice(1).map((s) => (
                  <div
                    key={s.id}
                    className="rounded-md border border-border bg-bg-elevated p-2"
                  >
                    <div className="flex items-center justify-between">
                      <Badge tone={CATEGORY_TONE[s.category] ?? "muted"}>
                        {CATEGORY_LABELS[s.category] ?? s.category}
                      </Badge>
                      <Badge tone={scoreTone(s.score)}>
                        {fmt.num(s.score, 0)}
                      </Badge>
                    </div>
                    {s.reasons_json?.length > 0 && (
                      <ul className="text-xs text-fg-muted mt-2 list-disc ml-4">
                        {s.reasons_json.slice(0, 3).map((r, i) => (
                          <li key={i}>{r}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="lg:col-span-1">
          <AIExplain symbol={stock.symbol} />
        </div>
      </div>
    </div>
  );
}
