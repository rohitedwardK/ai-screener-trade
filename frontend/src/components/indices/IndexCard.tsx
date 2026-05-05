import { Link } from "react-router-dom";
import { Badge } from "@/components/Badge";
import { fmt, regimeTone, scoreTone } from "@/lib/format";
import type { IndexRow } from "@/api/types";
import { INDEX_CATEGORY_TONE, OPTION_BIAS_TONE } from "@/api/types";

export function IndexCard({
  row,
  livePrice,
}: {
  row: IndexRow;
  livePrice?: number;
}) {
  const price = livePrice ?? row.close;
  const direction = row.direction;
  return (
    <Link
      to={`/indices/${encodeURIComponent(row.symbol)}`}
      className="card p-3 hover:border-border-strong transition group flex flex-col gap-2"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-medium tracking-tight truncate">{row.code}</div>
          <div className="text-xs text-fg-muted truncate">{row.name}</div>
        </div>
        <div className="text-right shrink-0">
          <div className="num text-base">{fmt.num(price, 2)}</div>
          {row.atr_pct != null && (
            <div className="text-[11px] text-fg-subtle num">
              ATR {fmt.pctRaw(row.atr_pct)}
            </div>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Badge tone={regimeTone(row.regime)}>{row.regime.replace(/_/g, " ")}</Badge>
        {row.category && (
          <Badge tone={INDEX_CATEGORY_TONE[row.category] ?? "muted"}>
            {row.category.replace(/_/g, " ")}
          </Badge>
        )}
        {direction && (
          <Badge tone={direction === "LONG" ? "green" : "red"}>
            {direction === "LONG" ? "CE" : "PE"}
          </Badge>
        )}
        <Badge tone={scoreTone(row.score)}>Score {fmt.num(row.score, 0)}</Badge>
        {row.option_chain_bias && (
          <Badge tone={OPTION_BIAS_TONE[row.option_chain_bias] ?? "muted"}>
            Chain {row.option_chain_bias}
          </Badge>
        )}
      </div>
      <div className="grid grid-cols-3 gap-2 pt-1 border-t border-border text-[11px]">
        <div>
          <div className="text-fg-subtle">PCR</div>
          <div className="num">{fmt.num(row.pcr ?? null, 2)}</div>
          {row.pcr_volume != null && (
            <div className="text-[10px] text-fg-subtle num">
              vol {fmt.num(row.pcr_volume, 2)}
            </div>
          )}
        </div>
        <div>
          <div className="text-fg-subtle">Max Pain</div>
          <div className="num">{fmt.num(row.max_pain ?? null, 0)}</div>
          {row.max_pain_distance_pct != null && (
            <div className="text-[10px] text-fg-subtle num">
              {fmt.pct(row.max_pain_distance_pct, 1)}
            </div>
          )}
        </div>
        <div>
          <div className="text-fg-subtle">RSI</div>
          <div className="num">{fmt.num(row.rsi ?? null, 0)}</div>
        </div>
      </div>
      {row.pivot_p != null && (
        <div className="grid grid-cols-3 gap-2 pt-1 border-t border-border text-[11px]">
          <div>
            <div className="text-fg-subtle">Pivot</div>
            <div className="num">{fmt.num(row.pivot_p, 2)}</div>
          </div>
          <div>
            <div className="text-fg-subtle">R1</div>
            <div className="num text-accent-green">
              {fmt.num(row.pivot_r1, 2)}
            </div>
          </div>
          <div>
            <div className="text-fg-subtle">S1</div>
            <div className="num text-accent-red">
              {fmt.num(row.pivot_s1, 2)}
            </div>
          </div>
        </div>
      )}
      {row.entry != null && (
        <div className="grid grid-cols-3 gap-2 pt-1 border-t border-border text-[11px]">
          <div>
            <div className="text-fg-subtle">Entry</div>
            <div className="num">{fmt.num(row.entry, 2)}</div>
          </div>
          <div>
            <div className="text-fg-subtle">Stop</div>
            <div className="num text-accent-red">{fmt.num(row.stop_loss, 2)}</div>
          </div>
          <div>
            <div className="text-fg-subtle">Target</div>
            <div className="num text-accent-green">
              {fmt.num(row.target_1, 2)}
            </div>
          </div>
        </div>
      )}
    </Link>
  );
}
