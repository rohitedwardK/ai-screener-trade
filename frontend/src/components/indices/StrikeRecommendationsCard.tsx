import { Badge } from "@/components/Badge";
import { fmt } from "@/lib/format";
import {
  STRIKE_STATUS_LABEL,
  STRIKE_STATUS_TONE,
  type ContractRecommendation,
} from "@/api/types";

const STRATEGY_LABEL: Record<string, string> = {
  SINGLE_LEG: "Single-leg buy",
  DEBIT_SPREAD: "Debit spread",
};

export function StrikeRecommendationsCard({
  recommendations,
  signalLabel,
  expiryLabel,
}: {
  recommendations: ContractRecommendation[];
  signalLabel?: string;
  expiryLabel?: string | null;
}) {
  if (recommendations.length === 0) {
    return null;
  }

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-semibold tracking-tight">
            Weekly-Expiry Strike Picks
          </h2>
          <p className="text-xs text-fg-muted">
            {signalLabel
              ? `Plans for ${signalLabel}`
              : "Auto-derived from the latest signal + option chain."}
            {expiryLabel ? ` Expiry ${expiryLabel}.` : ""} Premium points only;
            order-ready entries.
          </p>
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {recommendations.map((rec) => (
          <RecommendationPanel key={rec.id} rec={rec} />
        ))}
      </div>
    </div>
  );
}

function RecommendationPanel({ rec }: { rec: ContractRecommendation }) {
  const statusTone = STRIKE_STATUS_TONE[rec.status] ?? "muted";
  const statusLabel = STRIKE_STATUS_LABEL[rec.status] ?? rec.status;
  const strategyLabel = STRATEGY_LABEL[rec.strategy] ?? rec.strategy;

  if (rec.rejection_reason) {
    return (
      <div className="rounded border border-strong bg-bg-elevated/40 p-3 space-y-2">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <span className="font-semibold text-sm">{strategyLabel}</span>
          <Badge tone="amber">Rejected</Badge>
        </div>
        <p className="text-xs text-fg-muted">{rec.rejection_reason}</p>
      </div>
    );
  }

  const pnlPct = computePnlPct(rec);

  return (
    <div className="rounded border border-strong bg-bg-elevated/40 p-3 space-y-2">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-sm">{strategyLabel}</span>
          <Badge tone={rec.direction === "LONG" ? "green" : "red"}>
            {rec.direction === "LONG" ? "CE" : "PE"}
          </Badge>
        </div>
        <Badge tone={statusTone}>{statusLabel}</Badge>
      </div>

      <ul className="text-xs text-fg-muted space-y-0.5">
        {rec.legs.map((leg, idx) => (
          <li key={`${rec.id}-${idx}`} className="num">
            {leg.side} {leg.option_type} {fmt.num(leg.strike, 0)} @{" "}
            {fmt.num(leg.premium, 2)}
            {leg.iv != null && ` · IV ${fmt.num(leg.iv, 1)}`}
          </li>
        ))}
      </ul>

      <div className="grid grid-cols-3 gap-2 text-xs pt-1 border-t border-border">
        <PremiumKV label="Entry" value={rec.entry_premium} />
        <PremiumKV
          label="Stop"
          value={rec.sl_premium}
          tone="text-accent-red"
        />
        <PremiumKV
          label="Target 1"
          value={rec.t1_premium}
          tone="text-accent-green"
        />
        <PremiumKV label="Net debit" value={rec.net_debit} />
        <PremiumKV
          label="Max profit"
          value={rec.max_profit}
          tone="text-accent-green"
        />
        <PremiumKV
          label="Target 2"
          value={rec.t2_premium}
          tone="text-accent-green"
        />
      </div>

      {(rec.last_premium != null || rec.breakeven != null) && (
        <div className="grid grid-cols-3 gap-2 text-xs pt-1 border-t border-border">
          <PremiumKV
            label="Live premium"
            value={rec.last_premium}
            tone={pnlTone(pnlPct)}
          />
          <PremiumKV
            label="P&L"
            value={pnlPct == null ? null : pnlPct}
            suffix="%"
            tone={pnlTone(pnlPct)}
          />
          <PremiumKV
            label="Breakeven (spot)"
            value={rec.breakeven}
            digits={0}
          />
        </div>
      )}

      {rec.notes.length > 0 && (
        <ul className="text-[11px] text-fg-subtle list-disc ml-4 space-y-0.5">
          {rec.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PremiumKV({
  label,
  value,
  tone,
  digits = 2,
  suffix = "",
}: {
  label: string;
  value: number | null | undefined;
  tone?: string;
  digits?: number;
  suffix?: string;
}) {
  return (
    <div>
      <div className="text-fg-subtle">{label}</div>
      <div className={`num ${tone ?? ""}`}>
        {value == null ? "—" : `${fmt.num(value, digits)}${suffix}`}
      </div>
    </div>
  );
}

function computePnlPct(rec: ContractRecommendation): number | null {
  if (rec.last_premium == null || rec.entry_premium <= 0) return null;
  return ((rec.last_premium - rec.entry_premium) / rec.entry_premium) * 100;
}

function pnlTone(pnl: number | null): string {
  if (pnl == null) return "";
  if (pnl > 0) return "text-accent-green";
  if (pnl < 0) return "text-accent-red";
  return "";
}
