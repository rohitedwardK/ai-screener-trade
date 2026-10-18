import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "./Badge";
import { fmt, regimeTone, scoreTone, symbolDisplay } from "@/lib/format";
import {
  CATEGORY_TONE,
  LIVE_STATUS_LABEL,
  LIVE_STATUS_TONE,
} from "@/api/types";
import type { LiveVerification, ScreenerRow } from "@/api/types";
import {
  DEFAULT_QTY,
  openTradeForSymbol,
  screenerPaperDirection,
  usePaperTrades,
} from "@/lib/paperTrades";
import { ArrowDown, ArrowUp, TrendingDown, TrendingUp } from "lucide-react";

type SortKey =
  | "symbol"
  | "score"
  | "confidence"
  | "trade_quality"
  | "close"
  | "rsi"
  | "adx"
  | "atr_pct"
  | "live";

const HEADERS: { key: SortKey | null; label: string; align?: "right" }[] = [
  { key: "symbol", label: "Symbol" },
  { key: null, label: "Sector" },
  { key: null, label: "Regime" },
  { key: null, label: "Category" },
  { key: null, label: "Side" },
  { key: "live", label: "Live" },
  { key: "score", label: "Score", align: "right" },
  { key: "confidence", label: "Conf", align: "right" },
  { key: "trade_quality", label: "Quality %", align: "right" },
  { key: "close", label: "Live / Run close", align: "right" },
  { key: "rsi", label: "RSI", align: "right" },
  { key: "adx", label: "ADX", align: "right" },
  { key: "atr_pct", label: "ATR%", align: "right" },
  { key: null, label: "Entry/Stop/Target", align: "right" },
  { key: null, label: "Paper trade", align: "right" },
];

// Higher = more bullish on the persisted thesis. Used by the "Live" column
// sort so STRENGTHENED floats to the top, INVALIDATED sinks to the bottom,
// and rows with no verification land in the middle (tone-neutral).
const LIVE_RANK: Record<string, number> = {
  STRENGTHENED: 4,
  CONFIRMED: 3,
  WEAKENING: 1,
  INVALIDATED: 0,
};
const LIVE_RANK_NULL = 2;

export function ScreenerTable({
  rows,
  livePrices,
}: {
  rows: ScreenerRow[];
  livePrices?: Record<string, number>;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const sorted = useMemo(() => {
    const copy = [...rows];
    const livePriceFor = (sym: string, fallback: number) =>
      livePrices?.[sym] ?? fallback;

    const liveRank = (row: ScreenerRow) =>
      row.live ? LIVE_RANK[row.live.status] ?? LIVE_RANK_NULL : LIVE_RANK_NULL;

    copy.sort((a, b) => {
      let av: number | string;
      let bv: number | string;
      if (sortKey === "trade_quality") {
        const aq = a.trade_quality?.quality_score;
        const bq = b.trade_quality?.quality_score;
        if (aq == null || bq == null) return aq == null ? (bq == null ? 0 : 1) : -1;
        av = aq;
        bv = bq;
      } else if (sortKey === "close") {
        av = livePriceFor(a.symbol, a.close);
        bv = livePriceFor(b.symbol, b.close);
      } else if (sortKey === "live") {
        av = liveRank(a);
        bv = liveRank(b);
      } else {
        av = (a[sortKey] ?? 0) as number | string;
        bv = (b[sortKey] ?? 0) as number | string;
      }
      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "asc" ? av - bv : bv - av;
      }
      return sortDir === "asc"
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
    });
    return copy;
  }, [rows, sortKey, sortDir, livePrices]);

  const onSort = (key: SortKey | null) => {
    if (!key) return;
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "symbol" ? "asc" : "desc");
    }
  };

  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs uppercase tracking-wide text-fg-muted">
            <tr className="border-b border-border">
              {HEADERS.map((h) => (
                <th
                  key={h.label}
                  className={`px-3 py-2 ${
                    h.align === "right" ? "text-right" : "text-left"
                  } ${h.key ? "cursor-pointer select-none hover:text-fg" : ""}`}
                  onClick={() => onSort(h.key)}
                >
                  <span className="inline-flex items-center gap-1">
                    {h.label}
                    {sortKey === h.key &&
                      (sortDir === "asc" ? (
                        <ArrowUp className="size-3" />
                      ) : (
                        <ArrowDown className="size-3" />
                      ))}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 && (
              <tr>
                <td
                  colSpan={HEADERS.length}
                  className="px-3 py-12 text-center text-fg-muted"
                >
                  No signals match your filters. Try lowering min score or running a refresh.
                </td>
              </tr>
            )}
            {sorted.map((r) => (
              <tr
                key={`${r.symbol}-${r.category}`}
                className="border-b border-border last:border-b-0 hover:bg-bg-elevated"
              >
                <td className="px-3 py-2">
                  <Link to={`/stock/${r.symbol}`} className="font-medium text-fg hover:text-accent-blue">
                    {symbolDisplay(r.symbol)}
                  </Link>
                  <div className="text-[11px] text-fg-subtle truncate max-w-[180px]">
                    {r.name ?? ""}
                  </div>
                </td>
                <td className="px-3 py-2 text-fg-muted">{r.sector ?? "—"}</td>
                <td className="px-3 py-2">
                  <Badge tone={regimeTone(r.regime)}>
                    {r.regime.replace(/_/g, " ")}
                  </Badge>
                </td>
                <td className="px-3 py-2">
                  <Badge tone={CATEGORY_TONE[r.category] ?? "muted"}>
                    {r.category.replace(/_/g, " ")}
                  </Badge>
                </td>
                <td className="px-3 py-2">
                  <Badge tone={r.direction === "LONG" ? "green" : r.direction === "SHORT" ? "red" : "muted"}>
                    {r.direction ?? "WAIT"}
                  </Badge>
                </td>
                <td className="px-3 py-2">
                  <LiveStatusCell live={r.live} />
                </td>
                <td className="px-3 py-2 text-right">
                  <Badge tone={scoreTone(r.score)}>{fmt.num(r.score, 0)}</Badge>
                </td>
                <td className="px-3 py-2 text-right num">
                  {fmt.num(r.confidence * 100, 0)}%
                </td>
                <td className="px-3 py-2 text-right num" title={r.trade_quality
                  ? `${r.trade_quality.target}. As of ${r.trade_quality.as_of ?? "unknown"}. ${r.trade_quality.disclaimer}`
                  : undefined}>
                  {r.trade_quality?.quality_score != null
                    ? `${fmt.num(r.trade_quality.quality_score, 1)}%`
                    : <span className="text-xs text-fg-subtle">{(r.trade_quality?.status ?? "untrained").replace(/_/g, " ")}</span>}
                </td>
                <td className="px-3 py-2 text-right num">
                  <PriceCell row={r} live={livePrices?.[r.symbol]} />
                </td>
                <td className="px-3 py-2 text-right num">{fmt.num(r.rsi, 0)}</td>
                <td className="px-3 py-2 text-right num">{fmt.num(r.adx, 0)}</td>
                <td className="px-3 py-2 text-right num">{fmt.pctRaw(r.atr_pct)}</td>
                <td className="px-3 py-2 text-right num text-xs">
                  {r.entry != null ? (
                    <span>
                      {fmt.inr(r.entry)} /{" "}
                      <span className="text-accent-red">{fmt.inr(r.stop_loss)}</span> /{" "}
                      <span className="text-accent-green">{fmt.inr(r.target_1)}</span>
                      <span className="block text-fg-muted">Invalidation {fmt.inr(r.invalidation)}</span>
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  <TradeActionCell row={r} live={livePrices?.[r.symbol]} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LiveStatusCell({ live }: { live: LiveVerification | null }) {
  if (!live) {
    return <span className="text-[11px] text-fg-subtle">—</span>;
  }
  const label = LIVE_STATUS_LABEL[live.status];
  const distanceParts: string[] = [];
  if (live.distance_to_stop_pct != null) {
    distanceParts.push(`stop ${fmt.pct(live.distance_to_stop_pct, 1)}`);
  }
  if (live.distance_to_t1_pct != null) {
    distanceParts.push(`T1 ${fmt.pct(live.distance_to_t1_pct, 1)}`);
  }
  const tooltipLines: string[] = [
    `Status: ${label}`,
    `Live close: ${fmt.inr(live.live_close)}`,
  ];
  if (live.live_rsi != null) {
    tooltipLines.push(`Live RSI: ${fmt.num(live.live_rsi, 0)}`);
  }
  tooltipLines.push(`Live regime: ${live.live_regime.replace(/_/g, " ")}`);
  if (live.score_delta != null) {
    tooltipLines.push(`Score delta: ${fmt.num(live.score_delta, 1)}`);
  }
  if (distanceParts.length) {
    tooltipLines.push(`Distance: ${distanceParts.join(" · ")}`);
  }
  if (live.notes.length > 0) {
    tooltipLines.push(...live.notes);
  }
  return (
    <span title={tooltipLines.join("\n")}>
      <Badge tone={LIVE_STATUS_TONE[live.status]}>{label}</Badge>
    </span>
  );
}

export function TradeActionCell({ row, live }: { row: ScreenerRow; live?: number }) {
  const trades = usePaperTrades((s) => s.trades);
  const buy = usePaperTrades((s) => s.buy);
  const sell = usePaperTrades((s) => s.sell);

  const hasLive = live != null && Number.isFinite(live);
  const price = hasLive ? (live as number) : row.close;
  const open = openTradeForSymbol(trades, row.symbol);
  const direction = screenerPaperDirection(row);
  const optionLabel = direction === "LONG" ? "CE" : "PE";

  if (open) {
    const move = price - open.buyPrice;
    const pnl = (open.direction === "SHORT" ? -move : move) * open.quantity;
    const tone = pnl > 0 ? "text-accent-green" : pnl < 0 ? "text-accent-red" : "text-fg-muted";
    return (
      <div className="flex flex-col items-end gap-1">
        <button
          type="button"
          onClick={() => sell(open.id, price)}
          className="inline-flex items-center gap-1 rounded-md border border-accent-red/40 bg-accent-red/10 px-2 py-1 text-xs font-medium text-accent-red hover:bg-accent-red/20"
          title={`Close ${open.direction.toLowerCase()} ${open.quantity} @ ${fmt.inr(price)} (opened @ ${fmt.inr(open.buyPrice)})`}
        >
          <TrendingDown className="size-3" />
          Close {open.quantity}
        </button>
        <span className={`text-[10px] num ${tone}`}>
          {pnl >= 0 ? "+" : ""}
          {fmt.inr(pnl)}
        </span>
      </div>
    );
  }

  if (direction === "WAIT") {
    return (
      <span className="text-[11px] uppercase tracking-wide text-fg-subtle" title="No trade — WAIT">
        WAIT
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={() =>
        buy({
          symbol: row.symbol,
          name: row.name,
          category: row.category,
          scoreAtBuy: row.score,
          entry: row.entry,
          stopLoss: row.stop_loss,
          target1: row.target_1,
          target2: row.target_2,
          invalidation: row.invalidation,
          direction,
          price,
        })
      }
      className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium ${direction === "LONG"
        ? "border-accent-green/40 bg-accent-green/10 text-accent-green hover:bg-accent-green/20"
        : "border-accent-red/40 bg-accent-red/10 text-accent-red hover:bg-accent-red/20"}`}
      title={`${optionLabel}: track ${fmt.num(DEFAULT_QTY, 0)} ${direction.toLowerCase()} @ ${fmt.inr(price)} (paper trade)`}
    >
      {direction === "LONG" ? <TrendingUp className="size-3" /> : <TrendingDown className="size-3" />}
      {optionLabel} {fmt.num(DEFAULT_QTY, 0)}
    </button>
  );
}

function PriceCell({ row, live }: { row: ScreenerRow; live?: number }) {
  const hasLive = live != null && Number.isFinite(live);
  const displayPrice = hasLive ? live : row.close;
  const baseline = row.close;
  const diff = hasLive ? (live as number) - baseline : 0;
  const pct = hasLive && baseline > 0 ? (diff / baseline) * 100 : 0;
  const tone =
    !hasLive || Math.abs(diff) < 0.01
      ? "text-fg"
      : diff > 0
      ? "text-accent-green"
      : "text-accent-red";

  return (
    <div className="flex flex-col items-end leading-tight">
      <span className={`num ${tone}`}>{fmt.inr(displayPrice)}</span>
      {hasLive ? (
        Math.abs(diff) >= 0.01 ? (
          <span
            className={`flex items-center justify-end gap-0.5 text-[10px] num ${tone}`}
            title={`Run close: ${fmt.inr(baseline)}`}
          >
            {diff > 0 ? (
              <TrendingUp className="size-3" />
            ) : (
              <TrendingDown className="size-3" />
            )}
            {diff >= 0 ? "+" : ""}
            {fmt.num(diff, 2)} ({pct >= 0 ? "+" : ""}
            {fmt.num(pct, 2)}%)
          </span>
        ) : (
          <span className="text-[10px] text-fg-subtle num">
            run close {fmt.inr(baseline)}
          </span>
        )
      ) : (
        <span className="text-[10px] text-fg-subtle num">run close</span>
      )}
    </div>
  );
}
