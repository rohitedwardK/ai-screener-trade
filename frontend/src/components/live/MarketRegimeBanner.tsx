import { TrendingDown, TrendingUp, Minus } from "lucide-react";
import { fmt } from "@/lib/format";
import type { LiveMarketSnapshot } from "@/api/types";

interface Props {
  snapshot: LiveMarketSnapshot | null;
  marketOpen: boolean;
}

const regimeConfig: Record<
  string,
  { label: string; tone: string; Icon: typeof TrendingUp }
> = {
  RISK_ON: {
    label: "Risk On",
    tone: "bg-accent-green/10 text-accent-green border-accent-green/30",
    Icon: TrendingUp,
  },
  RISK_OFF: {
    label: "Risk Off",
    tone: "bg-accent-red/10 text-accent-red border-accent-red/30",
    Icon: TrendingDown,
  },
  NEUTRAL: {
    label: "Neutral",
    tone: "bg-accent-blue/10 text-accent-blue border-accent-blue/30",
    Icon: Minus,
  },
};

export function MarketRegimeBanner({ snapshot, marketOpen }: Props) {
  const regime = snapshot?.regime ?? "NEUTRAL";
  const cfg = regimeConfig[regime] ?? regimeConfig.NEUTRAL;
  const Icon = cfg.Icon;

  return (
    <div className="card p-4 flex items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <div className={`inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium ${cfg.tone}`}>
          <Icon className="size-4" />
          <span>Market Regime · {cfg.label}</span>
        </div>
        <span className={`text-xs ${marketOpen ? "text-accent-green" : "text-fg-muted"}`}>
          {marketOpen ? "NSE session open" : "NSE session closed"}
        </span>
      </div>
      <div className="flex items-center gap-6 text-xs num">
        <Stat label="Nifty" value={fmt.num(snapshot?.nifty_last ?? null, 2)} />
        <Stat label="Z-score" value={fmt.num(snapshot?.nifty_z ?? null, 3)} />
        <Stat label="Slope" value={fmt.num(snapshot?.nifty_slope ?? null, 3)} />
        <Stat
          label="VWAP dev"
          value={
            snapshot?.nifty_vwap_dev == null
              ? "—"
              : fmt.pct((snapshot.nifty_vwap_dev ?? 0) * 100, 2)
          }
        />
        <Stat label="Source" value={String(snapshot?.counters?.source ?? "—")} />
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col items-end">
      <span className="text-fg-subtle uppercase tracking-wider text-[10px]">
        {label}
      </span>
      <span className="text-fg">{value}</span>
    </div>
  );
}
