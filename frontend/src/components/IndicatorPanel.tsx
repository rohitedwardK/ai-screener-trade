import type { Snapshot } from "@/api/types";
import { fmt } from "@/lib/format";

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "green" | "red" | "amber" | "muted";
}) {
  const toneClass =
    tone === "green"
      ? "text-accent-green"
      : tone === "red"
      ? "text-accent-red"
      : tone === "amber"
      ? "text-accent-amber"
      : "text-fg";
  return (
    <div className="card p-3">
      <div className="text-xs uppercase tracking-wide text-fg-muted">{label}</div>
      <div className={`mt-1 text-lg font-semibold num ${toneClass}`}>{value}</div>
      {hint && <div className="text-[11px] text-fg-subtle mt-0.5">{hint}</div>}
    </div>
  );
}

export function IndicatorPanel({ snapshot }: { snapshot: Snapshot }) {
  const ind = snapshot.indicators_json ?? {};
  const rsi = ind["rsi14"];
  const adx = ind["adx"];
  const macdH = ind["macd_hist"];
  const atrPct = ind["atr_pct"];
  const ret20 = ind["return_20d"];
  const pctHigh = ind["pct_from_52w_high"];
  const volRatio = ind["vol_ratio"];

  const rsiTone =
    rsi == null
      ? "muted"
      : rsi >= 70
      ? "amber"
      : rsi <= 30
      ? "amber"
      : rsi >= 55
      ? "green"
      : rsi <= 45
      ? "red"
      : "muted";

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <Stat
        label="RSI(14)"
        value={fmt.num(rsi, 1)}
        hint="Momentum 0–100"
        tone={rsiTone as any}
      />
      <Stat
        label="ADX(14)"
        value={fmt.num(adx, 1)}
        hint={adx != null && adx >= 25 ? "Trending" : "Weak/range"}
        tone={adx != null && adx >= 25 ? "green" : "muted"}
      />
      <Stat
        label="MACD Hist"
        value={fmt.num(macdH, 2)}
        hint={macdH != null ? (macdH >= 0 ? "Bullish" : "Bearish") : ""}
        tone={macdH != null ? (macdH >= 0 ? "green" : "red") : "muted"}
      />
      <Stat
        label="ATR %"
        value={fmt.pctRaw(atrPct)}
        hint="Daily range / price"
        tone={atrPct != null && atrPct >= 4.5 ? "amber" : "muted"}
      />
      <Stat
        label="20-day Return"
        value={fmt.pct(ret20)}
        tone={ret20 != null ? (ret20 >= 0 ? "green" : "red") : "muted"}
      />
      <Stat
        label="From 52w High"
        value={fmt.pct(pctHigh)}
        tone={pctHigh != null && pctHigh >= -5 ? "green" : "muted"}
      />
      <Stat
        label="Volume Ratio"
        value={`${fmt.num(volRatio, 2)}x`}
        hint="vs 20-day average"
        tone={volRatio != null && volRatio >= 1.5 ? "green" : "muted"}
      />
      <Stat
        label="Regime"
        value={snapshot.regime.replace(/_/g, " ")}
        tone={
          snapshot.regime.includes("UPTREND")
            ? "green"
            : snapshot.regime.includes("DOWNTREND")
            ? "red"
            : snapshot.regime === "VOLATILE"
            ? "amber"
            : "muted"
        }
      />
    </div>
  );
}
