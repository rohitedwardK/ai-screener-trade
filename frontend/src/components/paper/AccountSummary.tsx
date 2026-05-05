import { fmt } from "@/lib/format";
import type { PaperPerformance, PaperStatus } from "@/api/types";
import { TrendingUp, TrendingDown, Target, Activity, Coins } from "lucide-react";

function Stat({
  label,
  value,
  hint,
  tone,
  icon: Icon,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "green" | "red" | "amber" | "blue" | "muted";
  icon?: React.ComponentType<{ className?: string }>;
}) {
  const toneClass = {
    green: "text-accent-green",
    red: "text-accent-red",
    amber: "text-accent-amber",
    blue: "text-accent-blue",
    muted: "text-fg",
  }[tone ?? "muted"];
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-1.5 text-xs text-fg-muted">
        {Icon && <Icon className="size-3.5" />}
        {label}
      </div>
      <div className={`num text-lg font-semibold ${toneClass}`}>{value}</div>
      {hint && <div className="text-[11px] text-fg-subtle">{hint}</div>}
    </div>
  );
}

export function AccountSummary({
  status,
  performance,
}: {
  status: PaperStatus | undefined;
  performance: PaperPerformance | undefined;
}) {
  const totalPnl = (status?.realized_pnl_total ?? 0) + (status?.unrealized_pnl_total ?? 0);
  const startCapital = status?.virtual_capital ?? 0;
  const totalReturnPct = startCapital > 0 ? (totalPnl / startCapital) * 100 : 0;

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="font-semibold flex items-center gap-2">
            <Coins className="size-4 text-accent-violet" />
            Paper Account
          </h2>
          <p className="text-xs text-fg-muted mt-0.5">Simulated capital — no real money.</p>
        </div>
        <div className="text-right">
          <div className="text-xs text-fg-muted">Equity</div>
          <div className="num text-2xl font-semibold">
            ₹{fmt.inr(status?.current_equity, 0)}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Stat
          label="Virtual capital"
          value={`₹${fmt.inr(status?.virtual_capital, 0)}`}
          icon={Coins}
        />
        <Stat
          label="Total P&L"
          value={`${totalPnl >= 0 ? "+" : ""}₹${fmt.inr(totalPnl, 0)}`}
          hint={`${totalReturnPct >= 0 ? "+" : ""}${fmt.num(totalReturnPct, 2)}% return`}
          tone={totalPnl >= 0 ? "green" : "red"}
          icon={totalPnl >= 0 ? TrendingUp : TrendingDown}
        />
        <Stat
          label="Realized today"
          value={`${(status?.realized_pnl_today ?? 0) >= 0 ? "+" : ""}₹${fmt.inr(
            status?.realized_pnl_today ?? 0,
            0
          )}`}
          tone={(status?.realized_pnl_today ?? 0) >= 0 ? "green" : "red"}
          icon={Activity}
        />
        <Stat
          label="Unrealized"
          value={`${(status?.unrealized_pnl_total ?? 0) >= 0 ? "+" : ""}₹${fmt.inr(
            status?.unrealized_pnl_total ?? 0,
            0
          )}`}
          tone={(status?.unrealized_pnl_total ?? 0) >= 0 ? "green" : "red"}
          icon={Target}
        />
        <Stat
          label="Win rate"
          value={performance ? `${fmt.num(performance.win_rate, 1)}%` : "—"}
          hint={
            performance
              ? `${performance.winning_trades}W / ${performance.losing_trades}L`
              : undefined
          }
          tone={
            performance && performance.win_rate >= 50
              ? "green"
              : performance
              ? "amber"
              : "muted"
          }
        />
        <Stat
          label="Profit factor"
          value={performance ? fmt.num(performance.profit_factor, 2) : "—"}
          tone={
            performance && performance.profit_factor >= 1.5
              ? "green"
              : performance && performance.profit_factor >= 1.0
              ? "amber"
              : performance
              ? "red"
              : "muted"
          }
        />
        <Stat
          label="Expectancy"
          value={performance ? `₹${fmt.inr(performance.expectancy, 0)}` : "—"}
          hint="per trade"
          tone={performance && performance.expectancy >= 0 ? "green" : "red"}
        />
        <Stat
          label="Max drawdown"
          value={performance ? `${fmt.num(performance.max_drawdown_percent, 2)}%` : "—"}
          tone="amber"
        />
      </div>
    </div>
  );
}
