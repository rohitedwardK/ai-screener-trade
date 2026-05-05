import { ArrowDownRight, ArrowUpRight, MinusCircle } from "lucide-react";
import { fmt, symbolDisplay } from "@/lib/format";
import type { LiveDecision } from "@/api/types";

interface Props {
  decisions: LiveDecision[];
}

export function DecisionsFeed({ decisions }: Props) {
  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <div className="text-sm font-semibold text-fg">Recent Decisions</div>
        <div className="text-xs text-fg-muted">
          MFCS scorer output. Direction, 0-100 confidence, invalidation level.
        </div>
      </div>
      {decisions.length === 0 ? (
        <div className="p-6 text-center text-sm text-fg-muted">
          No decisions emitted yet. The first window completes ~15 minutes after a
          symbol enters the top movers ladder.
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {decisions.map((d) => (
            <DecisionRow key={d.id} decision={d} />
          ))}
        </ul>
      )}
    </div>
  );
}

function DecisionRow({ decision }: { decision: LiveDecision }) {
  const Icon =
    decision.direction === "LONG"
      ? ArrowUpRight
      : decision.direction === "SHORT"
        ? ArrowDownRight
        : MinusCircle;
  const tone =
    decision.direction === "LONG"
      ? "text-accent-green border-accent-green/30 bg-accent-green/10"
      : decision.direction === "SHORT"
        ? "text-accent-red border-accent-red/30 bg-accent-red/10"
        : "text-fg-muted border-border bg-bg-elevated";

  const confidencePct = Math.max(0, Math.min(100, decision.confidence));

  return (
    <li className="px-4 py-3 flex flex-col md:flex-row md:items-center gap-3 hover:bg-bg-elevated/40">
      <div
        className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md border text-xs font-medium ${tone}`}
      >
        <Icon className="size-3.5" />
        <span>{decision.direction}</span>
      </div>

      <div className="flex-1 min-w-[140px]">
        <div className="text-sm font-semibold text-fg">
          {symbolDisplay(decision.symbol)}
        </div>
        <div className="text-[11px] text-fg-muted num">
          {decision.ts ? new Date(decision.ts).toLocaleString("en-IN") : ""}
        </div>
      </div>

      <div className="flex items-center gap-3 flex-1">
        <div className="flex-1 h-1.5 rounded-full bg-bg-elevated overflow-hidden">
          <div
            className={`h-full ${
              decision.direction === "LONG"
                ? "bg-accent-green"
                : decision.direction === "SHORT"
                  ? "bg-accent-red"
                  : "bg-fg-subtle"
            }`}
            style={{ width: `${confidencePct}%` }}
          />
        </div>
        <span className="text-xs text-fg-muted num min-w-[3rem] text-right">
          {fmt.num(confidencePct, 0)}%
        </span>
      </div>

      <div className="flex items-center gap-4 text-xs num">
        <Field label="Long" value={fmt.num(decision.long_raw, 2)} />
        <Field label="Short" value={fmt.num(decision.short_raw, 2)} />
        <Field
          label="Invalidation"
          value={fmt.num(decision.invalidation ?? null, 2)}
        />
      </div>
    </li>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col items-end">
      <span className="text-fg-subtle text-[10px] uppercase tracking-wider">
        {label}
      </span>
      <span className="text-fg">{value}</span>
    </div>
  );
}
