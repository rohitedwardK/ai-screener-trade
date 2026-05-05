import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "./Badge";
import { fmt, regimeTone, scoreTone, symbolDisplay } from "@/lib/format";
import { CATEGORY_TONE } from "@/api/types";
import type { ScreenerRow } from "@/api/types";
import { ArrowDown, ArrowUp, TrendingDown, TrendingUp } from "lucide-react";

type SortKey =
  | "symbol"
  | "score"
  | "confidence"
  | "close"
  | "rsi"
  | "adx"
  | "atr_pct";

const HEADERS: { key: SortKey | null; label: string; align?: "right" }[] = [
  { key: "symbol", label: "Symbol" },
  { key: null, label: "Sector" },
  { key: null, label: "Regime" },
  { key: null, label: "Category" },
  { key: "score", label: "Score", align: "right" },
  { key: "confidence", label: "Conf", align: "right" },
  { key: "close", label: "Live / Run close", align: "right" },
  { key: "rsi", label: "RSI", align: "right" },
  { key: "adx", label: "ADX", align: "right" },
  { key: "atr_pct", label: "ATR%", align: "right" },
  { key: null, label: "Entry/Stop/Target", align: "right" },
];

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

    copy.sort((a, b) => {
      let av: number | string;
      let bv: number | string;
      if (sortKey === "close") {
        av = livePriceFor(a.symbol, a.close);
        bv = livePriceFor(b.symbol, b.close);
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
                <td className="px-3 py-2 text-right">
                  <Badge tone={scoreTone(r.score)}>{fmt.num(r.score, 0)}</Badge>
                </td>
                <td className="px-3 py-2 text-right num">
                  {fmt.num(r.confidence * 100, 0)}%
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
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
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
