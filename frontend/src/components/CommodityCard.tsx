import { useNavigate } from "react-router-dom";
import { Badge } from "./Badge";
import { TradeActionCell } from "./ScreenerTable";
import { fmt, regimeTone, scoreTone } from "@/lib/format";
import type { CommodityItem } from "@/api/types";
import { CATEGORY_LABELS, CATEGORY_TONE } from "@/api/types";
import { screenerPaperDirection } from "@/lib/paperTrades";

function formatPx(n: number | null | undefined, currency: string): string {
  if (currency === "USD") {
    const formatted = fmt.num(n);
    return formatted === "—" ? formatted : `$${formatted}`;
  }
  return fmt.inr(n);
}

function formatExpiry(iso: string | null): string {
  if (!iso) return "—";
  return iso.slice(0, 10);
}

export function CommodityCard({ item }: { item: CommodityItem }) {
  const navigate = useNavigate();
  const price = item.live_price ?? item.close;
  const detailPath = `/stock/${encodeURIComponent(item.symbol)}`;

  const isInteractiveTarget = (target: EventTarget | null) =>
    target instanceof HTMLElement &&
    target.closest("button, a, input, select, textarea") !== null;

  return (
    <div
      className="card p-4 flex flex-col gap-3 cursor-pointer hover:border-border-strong transition"
      role="link"
      tabIndex={0}
      onClick={(event) => {
        if (!isInteractiveTarget(event.target)) navigate(detailPath);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" && !isInteractiveTarget(event.target)) {
          navigate(detailPath);
        }
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-semibold tracking-tight">{item.name}</div>
          <div className="text-xs text-fg-muted mt-0.5">
            {item.contract_label ?? `${item.venue} · ${item.symbol}`} · {item.unit}
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="num text-lg">{formatPx(price, item.currency)}</div>
          {item.atr_pct != null && (
            <div className="text-[11px] text-fg-subtle num">
              ATR {fmt.pctRaw(item.atr_pct)}
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {item.setup_horizon === "monthly" || item.setup_horizon === "both" ? (
          <Badge tone="amber">Next expiry (≤30d)</Badge>
        ) : null}
        {item.setup_horizon === "scalp" ||
        item.setup_horizon === "both" ||
        item.setup_horizon === "weekly" ? (
          <Badge tone="violet">Scalp 1–2d</Badge>
        ) : null}
        {item.monthly_expiry && (
          <Badge tone="muted">
            Expiry {formatExpiry(item.monthly_expiry)}
            {item.days_to_expiry != null ? ` · ${item.days_to_expiry}d` : ""}
          </Badge>
        )}
        <Badge tone={regimeTone(item.regime)}>
          {item.regime.replace(/_/g, " ")}
        </Badge>
        {item.rsi != null && (
          <Badge tone="muted">RSI {fmt.num(item.rsi, 0)}</Badge>
        )}
        {item.adx != null && (
          <Badge tone="muted">ADX {fmt.num(item.adx, 0)}</Badge>
        )}
        <Badge tone="muted">{item.quote_source}</Badge>
      </div>

      {item.signals.length === 0 ? (
        <div className="space-y-2 py-1">
          {item.watch_notes.length > 0 ? (
            <>
              <div className="text-xs font-medium text-fg-muted">
                No scalp or next-expiry setup — levels to watch
              </div>
              <ul className="text-xs text-fg-muted leading-relaxed space-y-1.5 list-none">
                {item.watch_notes.map((note, i) => (
                  <li key={i} className="pl-3 border-l-2 border-border">
                    {note}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <div className="text-xs text-fg-subtle">
              No matching weekly or monthly setup in the 30-day window.
            </div>
          )}
        </div>
      ) : (
        <div className="grid gap-2">
          {item.signals.map((row) => {
            const dir = screenerPaperDirection(row);
            const monthly = (row.horizon ?? "").toUpperCase() === "MONTHLY_ON_MONTHLY";
            return (
              <div
                key={`${row.symbol}-${row.category}-${row.horizon ?? ""}`}
                className="rounded-lg border border-border bg-bg-elevated/40 p-2.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex flex-wrap gap-1.5">
                    <Badge tone={monthly ? "amber" : "violet"}>
                      {monthly
                        ? `Next expiry · ${item.days_to_expiry ?? "?"}d`
                        : `Scalp · ${row.days_to_expiry ?? 2}d`}
                    </Badge>
                    <Badge tone={CATEGORY_TONE[row.category] ?? "muted"}>
                      {CATEGORY_LABELS[row.category] ??
                        row.category.replace(/_/g, " ")}
                    </Badge>
                    <Badge tone={dir === "LONG" ? "green" : dir === "SHORT" ? "red" : "muted"}>
                      {dir === "LONG" ? "Buy CE" : dir === "SHORT" ? "Buy PE" : "WAIT"}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge tone={scoreTone(row.score)}>
                      Score {fmt.num(row.score, 0)}
                    </Badge>
                    <TradeActionCell
                      row={row}
                      live={item.live_price ?? undefined}
                    />
                  </div>
                </div>
                {row.reasons?.[0] && (
                  <p className="text-xs text-fg mt-2 leading-relaxed">{row.reasons[0]}</p>
                )}
                {row.entry != null && (
                  <div className="grid grid-cols-3 gap-2 pt-2 mt-2 border-t border-border text-[11px]">
                    <div>
                      <div className="text-fg-subtle">Entry</div>
                      <div className="num">{formatPx(row.entry, item.currency)}</div>
                    </div>
                    <div>
                      <div className="text-fg-subtle">Stop</div>
                      <div className="num text-accent-red">
                        {formatPx(row.stop_loss, item.currency)}
                      </div>
                    </div>
                    <div>
                      <div className="text-fg-subtle">Target</div>
                      <div className="num text-accent-green">
                        {formatPx(row.target_1, item.currency)}
                      </div>
                    </div>
                  </div>
                )}
                {row.invalidation != null && (
                  <div className="text-[11px] text-fg-muted mt-1.5">
                    Invalidation {formatPx(row.invalidation, item.currency)}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
