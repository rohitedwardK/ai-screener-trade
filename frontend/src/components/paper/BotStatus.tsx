import { Badge } from "@/components/Badge";
import { fmt } from "@/lib/format";
import type { PaperStatus } from "@/api/types";
import { BOT_STATUS_TONE } from "@/api/types";
import { Activity, AlertTriangle, Layers, Pause, Play, Radio } from "lucide-react";

const STATUS_LABEL: Record<string, string> = {
  ACTIVE: "Active",
  PAUSED: "Paused",
  DAILY_LIMIT_REACHED: "Daily limit reached",
  DAILY_LOSS_LIMIT_HIT: "Daily loss limit hit",
  MAX_OPEN_POSITIONS_REACHED: "Max positions reached",
  NO_QUALITY_SETUP: "No quality setup",
  ERROR: "Error",
};

export function BotStatus({ status }: { status: PaperStatus | undefined }) {
  if (!status) {
    return (
      <div className="card p-4 text-fg-muted text-sm">Loading bot status…</div>
    );
  }

  const isActive = status.bot_status === "ACTIVE";
  const tone = BOT_STATUS_TONE[status.bot_status] ?? "muted";

  const liveTone: "green" | "amber" | "muted" = !status.live_trading_enabled
    ? "muted"
    : status.is_market_open
      ? "green"
      : "amber";
  const liveLabel = !status.live_trading_enabled
    ? "Live: OFF"
    : status.is_market_open
      ? "Live: ON"
      : "Live: ON (market closed)";
  const lastTickLabel = status.last_live_tick_at
    ? new Date(status.last_live_tick_at).toLocaleTimeString()
    : "never";

  return (
    <div className="card p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h2 className="font-semibold flex items-center gap-2">
          <Activity className="size-4 text-accent-blue" />
          Bot Status
        </h2>
        <div className="flex items-center gap-2">
          <Badge tone={liveTone}>
            <Radio className="size-3" />
            {liveLabel}
          </Badge>
          <Badge tone={tone}>
            {isActive ? <Play className="size-3" /> : <Pause className="size-3" />}
            {STATUS_LABEL[status.bot_status] ?? status.bot_status}
          </Badge>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div className="flex items-center justify-between">
          <span className="text-fg-muted text-xs">Trades today</span>
          <span className="num">
            {status.trades_taken_today} / {status.trades_taken_today + status.remaining_trades_today}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-fg-muted text-xs flex items-center gap-1">
            <Layers className="size-3" /> Open positions
          </span>
          <span className="num">{status.open_positions}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-fg-muted text-xs">Remaining slots</span>
          <span className="num">{status.remaining_trades_today}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-fg-muted text-xs">Daily-loss cap</span>
          <span className="num">{fmt.num(status.daily_loss_limit_percent, 1)}%</span>
        </div>
        {status.live_trading_enabled && (
          <div className="flex items-center justify-between col-span-2">
            <span className="text-fg-muted text-xs">Last live update</span>
            <span className="num">{lastTickLabel}</span>
          </div>
        )}
      </div>
      {!isActive && (
        <div className="flex items-start gap-2 rounded-md border border-accent-amber/30 bg-accent-amber/5 px-3 py-2 text-xs text-accent-amber">
          <AlertTriangle className="size-3.5 mt-0.5 shrink-0" />
          <span>
            Bot is not taking new entries. Reason:{" "}
            <strong>{STATUS_LABEL[status.bot_status] ?? status.bot_status}</strong>.
          </span>
        </div>
      )}
      <p className="text-[11px] text-fg-subtle border-t border-border pt-2">
        {status.disclaimer}
      </p>
    </div>
  );
}
