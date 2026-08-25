import { Badge } from "@/components/Badge";
import { fmt, symbolDisplay } from "@/lib/format";
import { CLOSE_REASON_LABEL, MONITOR_STATUS_TONE } from "@/lib/tradingAgent";
import type { TradeMonitorVerdict, TradingAgentTick } from "@/lib/tradingAgent";
import { Activity, Bot, ShieldAlert } from "lucide-react";

const STATUS_LABEL: Record<TradeMonitorVerdict["status"], string> = {
  WATCHING: "Watching",
  NEAR_STOP: "Near stop",
  NEAR_TARGET: "Near target",
  THESIS_WEAK: "Thesis weak",
  EXIT_NOW: "Exit now",
};

export function TradingAgentPanel({
  tick,
  autoCloseEnabled,
  onToggleAutoClose,
  isFetching,
}: {
  tick: TradingAgentTick | null;
  autoCloseEnabled: boolean;
  onToggleAutoClose: (enabled: boolean) => void;
  isFetching: boolean;
}) {
  const verdicts = tick?.verdicts ?? [];
  const exitNow = verdicts.filter((v) => v.status === "EXIT_NOW" && !tick?.autoClosed.some((c) => c.tradeId === v.tradeId));
  const warnings = verdicts.filter(
    (v) => v.status === "NEAR_STOP" || v.status === "THESIS_WEAK" || v.status === "NEAR_TARGET",
  );

  return (
    <section className="card p-4 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-accent-violet/10 p-2 text-accent-violet">
            <Bot className="size-5" />
          </div>
          <div>
            <h2 className="text-sm font-semibold">Trading Agent</h2>
            <p className="text-xs text-fg-muted mt-0.5 max-w-xl">
              Monitors open paper trades against screener entry, stop, targets, and
              invalidation. Uses live prices plus screener verification status —
              auto-closes simulated positions when a level is breached (no real orders).
            </p>
          </div>
        </div>
        <label className="flex items-center gap-2 text-xs text-fg-muted cursor-pointer select-none">
          <input
            type="checkbox"
            checked={autoCloseEnabled}
            onChange={(e) => onToggleAutoClose(e.target.checked)}
            className="rounded border-border"
          />
          Auto-close on breach
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-[11px] text-fg-subtle">
        <span className="inline-flex items-center gap-1">
          <Activity className={`size-3 ${isFetching ? "animate-pulse text-accent-blue" : ""}`} />
          {tick
            ? `Last check ${new Date(tick.checkedAt).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}`
            : "Waiting for first check"}
        </span>
        <span>{verdicts.length} open position{verdicts.length === 1 ? "" : "s"} tracked</span>
      </div>

      {tick && tick.autoClosed.length > 0 && (
        <div className="rounded-md border border-accent-amber/30 bg-accent-amber/10 px-3 py-2 text-xs text-fg">
          <span className="font-medium text-accent-amber">Auto-closed this cycle: </span>
          {tick.autoClosed.map((c, i) => (
            <span key={c.tradeId}>
              {i > 0 ? " · " : ""}
              {symbolDisplay(c.symbol)} @ {fmt.inr(c.price)} ({CLOSE_REASON_LABEL[c.reason]})
            </span>
          ))}
        </div>
      )}

      {exitNow.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-medium text-accent-red">
            <ShieldAlert className="size-3.5" />
            Exit recommended
          </div>
          <ul className="space-y-1.5">
            {exitNow.map((v) => (
              <VerdictRow key={v.tradeId} verdict={v} />
            ))}
          </ul>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-medium text-accent-amber">Alerts</div>
          <ul className="space-y-1.5">
            {warnings.map((v) => (
              <VerdictRow key={v.tradeId} verdict={v} />
            ))}
          </ul>
        </div>
      )}

      {verdicts.length > 0 && exitNow.length === 0 && warnings.length === 0 && (
        <p className="text-xs text-fg-muted">
          All open positions are within plan. Monitoring continues every minute against
          live price and screener data.
        </p>
      )}

      <p className="text-[10px] text-fg-subtle border-t border-border pt-2">
        Research and decision-support only. Not financial advice.
      </p>
    </section>
  );
}

function VerdictRow({ verdict }: { verdict: TradeMonitorVerdict }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-bg-elevated px-3 py-2 text-xs">
      <div className="flex items-center gap-2 min-w-0">
        <span className="font-medium">{symbolDisplay(verdict.symbol)}</span>
        <Badge tone={MONITOR_STATUS_TONE[verdict.status]}>
          {STATUS_LABEL[verdict.status]}
        </Badge>
        {verdict.screenerLiveStatus && (
          <span className="text-fg-subtle">live {verdict.screenerLiveStatus.toLowerCase()}</span>
        )}
      </div>
      <span className="text-fg-muted text-right">{verdict.message}</span>
    </li>
  );
}
