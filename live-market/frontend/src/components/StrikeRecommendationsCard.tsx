import type { StrikeCandidate, StrikeRecommendations } from "../api/types";
import { fmt } from "../lib/format";

const MONEYNESS_TONE: Record<string, string> = {
  OTM: "badge-blue",
  ATM: "badge-amber",
  ITM: "badge-violet",
};

const HOLD_PRESETS: { label: string; value: number | "auto" }[] = [
  { label: "Auto", value: "auto" },
  { label: "Intraday", value: 0 },
  { label: "Overnight", value: 1 },
  { label: "Swing 3d", value: 3 },
];

export default function StrikeRecommendationsCard({
  data,
  direction,
  onDirectionChange,
  holdDays,
  onHoldDaysChange,
}: {
  data: StrikeRecommendations;
  direction: "LONG" | "SHORT" | "AUTO";
  onDirectionChange: (d: "LONG" | "SHORT" | "AUTO") => void;
  holdDays: number | "auto";
  onHoldDaysChange: (h: number | "auto") => void;
}) {
  // Effective hold-days surfaced on any candidate (they should all agree).
  const effectiveHold = data.candidates.length > 0 ? data.candidates[0].hold_days : null;
  const dte = data.candidates.length > 0 ? data.candidates[0].days_to_expiry : null;

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-fg-muted">
            Strike recommendations
          </h2>
          {dte != null && (
            <span className="text-xs text-fg-subtle">
              expiry in <span className="num text-fg">{dte.toFixed(1)}</span> d
              {effectiveHold != null && effectiveHold > 0 && (
                <>
                  {" "}| hold modeled <span className="num text-fg">{effectiveHold.toFixed(1)}</span> d
                </>
              )}
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1 text-xs">
          {(["AUTO", "LONG", "SHORT"] as const).map((opt) => (
            <button
              key={opt}
              onClick={() => onDirectionChange(opt)}
              className={`chip ${direction === opt ? "chip-active" : ""}`}
            >
              {opt}
            </button>
          ))}
          <span className="mx-1 text-fg-subtle">|</span>
          {HOLD_PRESETS.map((p) => (
            <button
              key={String(p.value)}
              onClick={() => onHoldDaysChange(p.value)}
              className={`chip ${holdDays === p.value ? "chip-active" : ""}`}
              title={p.value === "auto" ? "default: min(dte, 3)" : `theta over ${p.value} day(s)`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {data.note && (
        <p className="mb-3 rounded-md border border-strong bg-elevated px-3 py-2 text-xs text-fg-muted">
          {data.note}
        </p>
      )}

      {data.candidates.length === 0 ? (
        <p className="text-xs text-fg-subtle">
          No single-leg recommendations - chain unavailable or bias is neutral.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {data.candidates.map((c) => (
            <CandidateCard key={`${c.moneyness}-${c.strike}`} c={c} />
          ))}
        </div>
      )}
    </section>
  );
}

function CandidateCard({ c }: { c: StrikeCandidate }) {
  const dirTone = c.type === "CE" ? "badge-green" : "badge-red";
  const hasTheta = c.hold_days > 0 && c.theta_drag_total > 0.01;
  return (
    <div className="card p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`badge ${MONEYNESS_TONE[c.moneyness]}`}>{c.moneyness}</span>
          <span className={`badge ${dirTone}`}>{c.type}</span>
          <span className="num text-sm font-semibold text-fg">{fmt.num(c.strike, 0)}</span>
        </div>
        <span className="text-[10px] text-fg-subtle">~delta {c.delta_assumed.toFixed(2)}</span>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <Row label="Entry" value={fmt.num(c.premium_entry)} tone="strong" />
        <Row label="Stop" value={fmt.num(c.premium_stop)} tone="red" />
        <Row label="T1" value={fmt.num(c.premium_t1)} tone="green" />
        <Row label="T2" value={fmt.num(c.premium_t2)} tone="green" />
        <Row label="Breakeven (spot)" value={fmt.num(c.breakeven_spot)} />
        <Row
          label="Max loss / unit"
          value={fmt.num(c.max_loss_per_unit)}
          tone="red"
        />
      </div>

      {hasTheta && (
        <div className="mt-2 rounded-md border border-strong bg-elevated px-2 py-1.5 text-[11px]">
          <div className="flex justify-between text-fg-subtle">
            <span>Theta drag</span>
            <span className="num text-accent-amber">
              -{fmt.num(c.theta_per_day)} / day x {c.hold_days.toFixed(1)}d
              = -{fmt.num(c.theta_drag_total)}
            </span>
          </div>
          <p className="mt-0.5 text-fg-subtle">
            Targets above already net of theta. Exit earlier = closer to raw delta projection.
          </p>
        </div>
      )}

      {c.reasons.length > 0 && (
        <ul className="mt-2 list-disc pl-4 text-[11px] text-fg-muted">
          {c.reasons.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}
    </div>
  );
}

function Row({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "green" | "red" | "strong";
}) {
  const valueCls =
    tone === "green" ? "text-accent-green"
      : tone === "red" ? "text-accent-red"
      : tone === "strong" ? "text-fg font-semibold"
      : "text-fg-muted";
  return (
    <div className="flex justify-between">
      <span className="text-fg-subtle">{label}</span>
      <span className={`num ${valueCls}`}>{value}</span>
    </div>
  );
}
