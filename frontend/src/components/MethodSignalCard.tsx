import type { MethodSignalCard as MethodSignalCardType } from "@/api/types";
import { Badge } from "./Badge";
import { fmt, regimeTone, symbolDisplay } from "@/lib/format";

const DIRECTION_TONE = {
  LONG: "green",
  SHORT: "red",
  NEUTRAL: "amber",
} as const;

function confidenceTone(c: number): "green" | "amber" | "red" {
  if (c >= 0.65) return "green";
  if (c >= 0.45) return "amber";
  return "red";
}

function confidenceBarColor(c: number): string {
  if (c >= 0.65) return "bg-accent-green";
  if (c >= 0.45) return "bg-accent-amber";
  return "bg-accent-red";
}

export function MethodSignalCard({
  card,
  liveMoverRank,
}: {
  card: MethodSignalCardType;
  /** When set, this symbol is in today's live top-movers list (same k as the panel). */
  liveMoverRank?: number | null;
}) {
  const confPct = Math.round(card.confidence * 100);
  const tone = confidenceTone(card.confidence);

  return (
    <div className="card p-3 flex flex-col gap-2">
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-semibold tracking-tight truncate">
            {symbolDisplay(card.symbol)}
          </div>
          {card.name && (
            <div className="text-[11px] text-fg-muted truncate">{card.name}</div>
          )}
        </div>
        <div className="text-right shrink-0">
          <div className="num text-sm">{fmt.inr(card.close)}</div>
        </div>
      </div>

      {/* Confidence bar */}
      <div>
        <div className="flex justify-between text-[11px] mb-1">
          <span className="text-fg-muted uppercase tracking-wide">Confidence</span>
          <span className={`num font-semibold text-accent-${tone}`}>{confPct}%</span>
        </div>
        <div className="h-1.5 w-full rounded-full bg-bg-elevated overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${confidenceBarColor(card.confidence)}`}
            style={{ width: `${confPct}%` }}
          />
        </div>
      </div>

      {/* Badges row */}
      <div className="flex flex-wrap gap-1.5">
        <Badge tone={DIRECTION_TONE[card.direction]}>{card.direction}</Badge>
        <Badge tone={regimeTone(card.regime)}>
          {card.regime.replace(/_/g, " ")}
        </Badge>
        {liveMoverRank != null && (
          <Badge tone="blue">Live #{liveMoverRank}</Badge>
        )}
        {card.category && (
          <Badge tone="muted" className="truncate max-w-[120px]">
            {card.category.replace(/_/g, " ")}
          </Badge>
        )}
      </div>

      {/* Top factors */}
      {card.top_factors.length > 0 ? (
        <div className="flex flex-wrap gap-1 pt-1 border-t border-border">
          {card.top_factors.map((f, i) => (
            <span
              key={i}
              className="inline-block rounded px-1.5 py-0.5 bg-bg-elevated text-[11px] text-fg-muted"
            >
              {f}
            </span>
          ))}
        </div>
      ) : (
        <div className="pt-1 border-t border-border text-[11px] text-fg-subtle italic">
          No interpretable factors (sequence model)
        </div>
      )}
    </div>
  );
}
