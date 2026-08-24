import type { SwingSetup } from "../api/types";
import { STATUS_TONE } from "../api/types";
import PlanRow from "./PlanRow";

const TONE_BADGE: Record<string, string> = {
  green: "badge-green",
  red: "badge-red",
  amber: "badge-amber",
  muted: "badge-muted",
};

export default function SwingCard({ setup }: { setup: SwingSetup }) {
  const tone = STATUS_TONE[setup.status] ?? "muted";
  const badgeCls = TONE_BADGE[tone];
  const created = new Date(setup.created_at).toLocaleString("en-IN", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
  return (
    <div className="card p-4">
      <div className="mb-3 flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-fg">{setup.category}</span>
            <span className={`badge ${setup.direction === "LONG" ? "badge-green" : "badge-red"}`}>
              {setup.direction}
            </span>
            <span className={`badge ${badgeCls}`}>{setup.status}</span>
            <span className="badge badge-blue">{setup.days_to_expiry}D</span>
          </div>
          <p className="mt-1 text-xs text-fg-subtle">
            swing - 2-3 day hold | created {created}
          </p>
        </div>
        <span className="text-xs text-fg-muted">score {setup.score.toFixed(0)}</span>
      </div>
      <PlanRow
        label="spot plan"
        spot={{
          entry: setup.spot_entry,
          stop: setup.spot_stop,
          t1: setup.spot_t1,
          t2: setup.spot_t2,
          invalidation: setup.spot_invalidation,
        }}
        option={
          setup.option_strike != null
            ? {
                strike: setup.option_strike,
                type: setup.option_type,
                expiry: setup.option_expiry,
                premium_entry: setup.option_premium_entry,
                premium_stop: setup.option_premium_stop,
                premium_t1: setup.option_premium_t1,
                premium_t2: setup.option_premium_t2,
              }
            : null
        }
      />
      {setup.reasons.length > 0 && (
        <ul className="mt-3 list-disc pl-5 text-xs text-fg-muted">
          {setup.reasons.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}
      {setup.note && (
        <p className="mt-2 text-xs italic text-fg-subtle">{setup.note}</p>
      )}
    </div>
  );
}
