import type { CreditSpread } from "../api/types";
import { fmt } from "../lib/format";

export default function CreditSpreadCard({ spread }: { spread: CreditSpread }) {
  const isBullPut = spread.bias === "BULLISH";
  const title = isBullPut ? "Bull-put credit spread" : "Bear-call credit spread";
  const biasBadge = isBullPut ? "badge-green" : "badge-red";

  return (
    <div className="card border-strong p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-fg-muted">
            {title}
          </h2>
          <span className={`badge ${biasBadge}`}>{spread.bias}</span>
        </div>
        <span className="text-xs text-fg-subtle">
          expiry {new Date(spread.expiry).toLocaleDateString("en-IN")}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <Leg
          label={`SHORT ${spread.short_type}`}
          strike={spread.short_strike}
          premium={spread.short_premium}
          tone="amber"
        />
        <Leg
          label={`LONG ${spread.short_type}`}
          strike={spread.long_strike}
          premium={spread.long_premium}
          tone="muted"
        />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
        <Box label="Net credit" value={fmt.num(spread.net_credit)} tone="green" />
        <Box label="Max profit (expiry)" value={fmt.num(spread.max_profit)} tone="green" />
        <Box label="Max loss" value={fmt.num(spread.max_loss)} tone="red" />
        <Box label="Breakeven (spot)" value={fmt.num(spread.breakeven_spot)} />
      </div>

      <div className="mt-3 rounded-md border border-strong bg-elevated p-3">
        <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-[11px] text-fg-subtle">
          <span>
            Time-value projection (spot unchanged)
            <span className="ml-2 num text-fg">dte {spread.days_to_expiry.toFixed(1)}d</span>
            <span className="ml-2 num text-accent-green">theta +{fmt.num(spread.theta_per_day)}/d</span>
          </span>
        </div>
        <div className="grid grid-cols-4 gap-2 text-xs">
          <Projection
            label="Now"
            value={fmt.num(spread.net_credit)}
            sub="cost to close"
          />
          <Projection
            label="+1 day"
            value={fmt.num(spread.projected_value_1d)}
            sub={`P&L +${fmt.num(spread.net_credit - spread.projected_value_1d)}`}
            tone="amber"
          />
          <Projection
            label="+3 days"
            value={fmt.num(spread.projected_value_3d)}
            sub={`P&L +${fmt.num(spread.net_credit - spread.projected_value_3d)}`}
            tone="amber"
          />
          <Projection
            label="At expiry"
            value={fmt.num(spread.projected_value_at_expiry)}
            sub={`P&L +${fmt.num(spread.max_profit)}`}
            tone="green"
          />
        </div>
        <p className="mt-2 text-[10px] text-fg-subtle">
          Assumes spot stays in your winning side and IV is stable.
          Real value at exit depends on the live chain quotes.
        </p>
      </div>

      <p className="mt-3 rounded-md border border-strong bg-elevated px-3 py-2 text-[11px] text-accent-amber">
        {spread.warning}
      </p>

      {spread.reasons.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-[11px] text-fg-muted">
          {spread.reasons.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}
    </div>
  );
}

function Projection({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "green" | "amber" | "muted";
}) {
  const valueCls =
    tone === "green" ? "text-accent-green"
      : tone === "amber" ? "text-accent-amber"
      : "text-fg";
  return (
    <div className="rounded-md border border-border bg-bg-surface px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-fg-subtle">{label}</div>
      <div className={`num text-sm font-semibold ${valueCls}`}>{value}</div>
      {sub && <div className="text-[10px] text-fg-subtle">{sub}</div>}
    </div>
  );
}

function Leg({
  label,
  strike,
  premium,
  tone,
}: {
  label: string;
  strike: number;
  premium: number;
  tone: "amber" | "muted";
}) {
  const labelCls = tone === "amber" ? "text-accent-amber" : "text-fg-muted";
  return (
    <div className="rounded-md border border-strong bg-elevated px-3 py-2">
      <div className={`text-[10px] uppercase tracking-wide ${labelCls}`}>{label}</div>
      <div className="num text-sm font-semibold text-fg">{fmt.num(strike, 0)}</div>
      <div className="text-[10px] text-fg-subtle">premium {fmt.num(premium)}</div>
    </div>
  );
}

function Box({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
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
    </div>
  );
}
