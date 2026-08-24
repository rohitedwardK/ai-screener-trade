import type { OptionBias } from "../api/types";
import { BIAS_TONE } from "../api/types";
import { fmt } from "../lib/format";

const TONE_BADGE: Record<string, string> = {
  green: "badge-green",
  red: "badge-red",
  muted: "badge-muted",
};

export default function OptionBiasCard({ bias }: { bias: OptionBias }) {
  const tone = BIAS_TONE[bias.bias_label] ?? "muted";
  const badgeCls = TONE_BADGE[tone];

  return (
    <div className="card p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-fg-muted">
            Option chain bias
          </h2>
          <span className={`badge ${badgeCls}`}>{bias.bias_label}</span>
          <span className="text-xs text-fg-subtle">score {bias.bias_score.toFixed(0)}</span>
        </div>
        {bias.expiry && (
          <span className="text-xs text-fg-subtle">
            expiry {new Date(bias.expiry).toLocaleDateString("en-IN")}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Metric
          label="PCR (OI)"
          value={fmt.num(bias.pcr_oi)}
          hint={hintForPCR(bias.pcr_oi)}
        />
        <Metric
          label="Max pain"
          value={fmt.num(bias.max_pain, 0)}
          hint={hintForMaxPain(bias.max_pain, bias.spot)}
        />
        <Metric
          label="ATM IV"
          value={bias.atm_iv != null ? `${bias.atm_iv.toFixed(1)}%` : "-"}
          hint={
            bias.iv_skew != null
              ? `skew ${(bias.iv_skew * 100).toFixed(1)}%`
              : "skew n/a"
          }
        />
        <Metric
          label="Today's OI flow"
          value={bias.flow_direction}
          hint={`CE +${fmt.int(bias.ce_oi_added)} | PE +${fmt.int(bias.pe_oi_added)}`}
          tone={BIAS_TONE[bias.flow_direction] ?? "muted"}
        />
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        <WallsList
          title="Resistance (CE OI walls)"
          walls={bias.resistance_walls}
          accent="red"
        />
        <WallsList
          title="Support (PE OI walls)"
          walls={bias.support_walls}
          accent="green"
        />
      </div>

      {bias.bias_reasons.length > 0 && (
        <ul className="mt-3 list-disc pl-5 text-xs text-fg-muted">
          {bias.bias_reasons.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "green" | "red" | "muted";
}) {
  const valueCls =
    tone === "green" ? "text-accent-green"
      : tone === "red" ? "text-accent-red"
      : "text-fg";
  return (
    <div className="rounded-md border border-strong bg-elevated px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-fg-subtle">{label}</div>
      <div className={`num text-sm font-semibold ${valueCls}`}>{value}</div>
      {hint && <div className="text-[10px] text-fg-subtle">{hint}</div>}
    </div>
  );
}

function WallsList({
  title,
  walls,
  accent,
}: {
  title: string;
  walls: { strike: number; oi: number; side: string }[];
  accent: "green" | "red";
}) {
  const tone = accent === "green" ? "text-accent-green" : "text-accent-red";
  return (
    <div>
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-fg-subtle">
        {title}
      </h3>
      {walls.length === 0 ? (
        <p className="text-xs text-fg-subtle">- none -</p>
      ) : (
        <ul className="space-y-1 text-xs">
          {walls.map((w, i) => (
            <li key={i} className="flex justify-between">
              <span className={`num font-medium ${tone}`}>{fmt.num(w.strike, 0)}</span>
              <span className="text-fg-muted">OI {fmt.int(w.oi)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function hintForPCR(pcr: number | null): string {
  if (pcr == null) return "n/a";
  if (pcr >= 1.3) return "contrarian bullish";
  if (pcr <= 0.7) return "contrarian bearish";
  return "neutral band";
}

function hintForMaxPain(mp: number | null, spot: number | null): string {
  if (mp == null || spot == null || spot <= 0) return "n/a";
  const gap = ((mp - spot) / spot) * 100;
  if (Math.abs(gap) < 0.2) return "~at spot";
  return `${gap >= 0 ? "+" : ""}${gap.toFixed(2)}% vs spot`;
}
