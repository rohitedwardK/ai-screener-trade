import { useMemo } from "react";
import { Badge } from "@/components/Badge";
import { fmt } from "@/lib/format";
import type { OptionChain } from "@/api/types";
import { OPTION_BIAS_TONE } from "@/api/types";

const ROW_WINDOW = 11; // ATM ± 5

export function OptionChainTable({ chain }: { chain: OptionChain }) {
  const visibleRows = useMemo(() => {
    if (!chain.spot || !chain.rows.length) return chain.rows;
    const sorted = [...chain.rows].sort((a, b) => a.strike - b.strike);
    const atmIdx = sorted.reduce(
      (best, _row, i) => {
        const cur = Math.abs(sorted[i].strike - (chain.spot ?? 0));
        return cur < best.dist ? { idx: i, dist: cur } : best;
      },
      { idx: 0, dist: Number.POSITIVE_INFINITY },
    ).idx;
    const half = Math.floor(ROW_WINDOW / 2);
    const start = Math.max(0, atmIdx - half);
    const end = Math.min(sorted.length, start + ROW_WINDOW);
    return sorted.slice(start, end);
  }, [chain]);

  const summary = chain.summary;
  const atmStrike = useMemo(() => {
    if (!chain.spot || !chain.rows.length) return null;
    let best = chain.rows[0].strike;
    let bestDist = Math.abs(best - chain.spot);
    for (const r of chain.rows) {
      const d = Math.abs(r.strike - chain.spot);
      if (d < bestDist) {
        best = r.strike;
        bestDist = d;
      }
    }
    return best;
  }, [chain]);

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-semibold tracking-tight">Option Chain</h2>
          <p className="text-xs text-fg-muted">
            {chain.code} · expiry {chain.expiry} · spot {fmt.num(chain.spot, 2)} ·
            source {chain.source}
          </p>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          <Badge tone={OPTION_BIAS_TONE[summary.bias] ?? "muted"}>
            Bias {summary.bias}
          </Badge>
          <Badge tone="muted">PCR {fmt.num(summary.pcr ?? null, 2)}</Badge>
          <Badge tone="muted">
            Max Pain {fmt.num(summary.max_pain ?? null, 0)}
          </Badge>
          {summary.iv_skew != null && (
            <Badge tone={summary.iv_skew >= 0 ? "red" : "green"}>
              IV Skew {fmt.num(summary.iv_skew, 2)}
            </Badge>
          )}
        </div>
      </div>

      {summary.notes.length > 0 && (
        <div className="text-xs text-fg-muted">
          {summary.notes.join(" · ")}
        </div>
      )}

      <div className="overflow-x-auto -mx-4">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-fg-subtle text-[11px] uppercase">
              <th className="text-right px-3 py-1.5">CE LTP</th>
              <th className="text-right px-3 py-1.5">CE OI</th>
              <th className="text-right px-3 py-1.5">CE ΔOI</th>
              <th className="text-right px-3 py-1.5">CE IV</th>
              <th className="text-center px-3 py-1.5 border-x border-border">
                Strike
              </th>
              <th className="text-right px-3 py-1.5">PE IV</th>
              <th className="text-right px-3 py-1.5">PE ΔOI</th>
              <th className="text-right px-3 py-1.5">PE OI</th>
              <th className="text-right px-3 py-1.5">PE LTP</th>
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((r) => {
              const isAtm = atmStrike != null && r.strike === atmStrike;
              return (
                <tr
                  key={r.strike}
                  className={
                    isAtm
                      ? "bg-bg-elevated/60"
                      : "hover:bg-bg-elevated/40 transition"
                  }
                >
                  <td className="text-right px-3 py-1.5 num">
                    {fmt.num(r.ce_ltp, 2)}
                  </td>
                  <td className="text-right px-3 py-1.5 num text-fg-muted">
                    {fmt.int(r.ce_oi)}
                  </td>
                  <td
                    className={`text-right px-3 py-1.5 num ${
                      (r.ce_change_oi ?? 0) > 0
                        ? "text-accent-green"
                        : (r.ce_change_oi ?? 0) < 0
                        ? "text-accent-red"
                        : "text-fg-subtle"
                    }`}
                  >
                    {fmt.int(r.ce_change_oi)}
                  </td>
                  <td className="text-right px-3 py-1.5 num text-fg-muted">
                    {fmt.num(r.ce_iv, 1)}
                  </td>
                  <td
                    className={`text-center px-3 py-1.5 num font-semibold border-x border-border ${
                      isAtm ? "text-accent-blue" : ""
                    }`}
                  >
                    {fmt.num(r.strike, 0)}
                  </td>
                  <td className="text-right px-3 py-1.5 num text-fg-muted">
                    {fmt.num(r.pe_iv, 1)}
                  </td>
                  <td
                    className={`text-right px-3 py-1.5 num ${
                      (r.pe_change_oi ?? 0) > 0
                        ? "text-accent-green"
                        : (r.pe_change_oi ?? 0) < 0
                        ? "text-accent-red"
                        : "text-fg-subtle"
                    }`}
                  >
                    {fmt.int(r.pe_change_oi)}
                  </td>
                  <td className="text-right px-3 py-1.5 num text-fg-muted">
                    {fmt.int(r.pe_oi)}
                  </td>
                  <td className="text-right px-3 py-1.5 num">
                    {fmt.num(r.pe_ltp, 2)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs pt-2 border-t border-border">
        <div>
          <div className="text-fg-subtle">Total CE OI</div>
          <div className="num">{fmt.int(summary.total_ce_oi)}</div>
        </div>
        <div>
          <div className="text-fg-subtle">Total PE OI</div>
          <div className="num">{fmt.int(summary.total_pe_oi)}</div>
        </div>
        <div>
          <div className="text-fg-subtle">CE ΔOI</div>
          <div
            className={`num ${
              summary.total_ce_change_oi >= 0
                ? "text-accent-green"
                : "text-accent-red"
            }`}
          >
            {fmt.int(summary.total_ce_change_oi)}
          </div>
        </div>
        <div>
          <div className="text-fg-subtle">PE ΔOI</div>
          <div
            className={`num ${
              summary.total_pe_change_oi >= 0
                ? "text-accent-green"
                : "text-accent-red"
            }`}
          >
            {fmt.int(summary.total_pe_change_oi)}
          </div>
        </div>
      </div>
    </div>
  );
}
