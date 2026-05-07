import { Link } from "react-router-dom";
import { Badge } from "./Badge";
import { fmt, regimeTone, scoreTone, symbolDisplay } from "@/lib/format";
import type { ScreenerRow } from "@/api/types";
import {
  CATEGORY_TONE,
  LIVE_STATUS_LABEL,
  LIVE_STATUS_TONE,
} from "@/api/types";

export function StockCard({
  row,
  livePrice,
}: {
  row: ScreenerRow;
  livePrice?: number;
}) {
  const price = livePrice ?? row.live?.live_close ?? row.close;
  const liveTooltip = row.live
    ? `Live ${LIVE_STATUS_LABEL[row.live.status]} · close ${fmt.inr(row.live.live_close)}` +
      (row.live.live_rsi != null ? ` · RSI ${fmt.num(row.live.live_rsi, 0)}` : "")
    : undefined;
  return (
    <Link
      to={`/stock/${row.symbol}`}
      className="card p-3 hover:border-border-strong transition group flex flex-col gap-2"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-medium tracking-tight truncate">
            {symbolDisplay(row.symbol)}
          </div>
          <div className="text-xs text-fg-muted truncate">
            {row.name ?? row.symbol}
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="num text-base">{fmt.inr(price)}</div>
          {row.atr_pct != null && (
            <div className="text-[11px] text-fg-subtle num">
              ATR {fmt.pctRaw(row.atr_pct)}
            </div>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Badge tone={regimeTone(row.regime)}>{row.regime.replace(/_/g, " ")}</Badge>
        <Badge tone={CATEGORY_TONE[row.category] ?? "muted"}>
          {row.category.replace(/_/g, " ")}
        </Badge>
        <Badge tone={scoreTone(row.score)}>Score {fmt.num(row.score, 0)}</Badge>
        {row.live && (
          <span title={liveTooltip}>
            <Badge tone={LIVE_STATUS_TONE[row.live.status]}>
              Live · {LIVE_STATUS_LABEL[row.live.status]}
            </Badge>
          </span>
        )}
      </div>
      {row.entry != null && (
        <div className="grid grid-cols-3 gap-2 pt-1 border-t border-border text-[11px]">
          <div>
            <div className="text-fg-subtle">Entry</div>
            <div className="num">{fmt.inr(row.entry)}</div>
          </div>
          <div>
            <div className="text-fg-subtle">Stop</div>
            <div className="num text-accent-red">{fmt.inr(row.stop_loss)}</div>
          </div>
          <div>
            <div className="text-fg-subtle">Target</div>
            <div className="num text-accent-green">{fmt.inr(row.target_1)}</div>
          </div>
        </div>
      )}
    </Link>
  );
}
