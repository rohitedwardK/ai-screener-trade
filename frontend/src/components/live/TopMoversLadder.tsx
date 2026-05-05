import { fmt, symbolDisplay } from "@/lib/format";
import type { LiveMover } from "@/api/types";

interface Props {
  movers: LiveMover[];
  observingSymbols: Set<string>;
}

export function TopMoversLadder({ movers, observingSymbols }: Props) {
  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-fg">Top Movers</div>
          <div className="text-xs text-fg-muted">
            Ranked by |%Δ| × log(1+RVOL); promoted into 6-sample observation windows.
          </div>
        </div>
        <span className="text-xs text-fg-muted num">{movers.length} symbols</span>
      </div>
      {movers.length === 0 ? (
        <div className="p-6 text-center text-sm text-fg-muted">
          Waiting for the first market tick…
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-xs text-fg-subtle bg-bg-elevated/40">
            <tr className="text-left">
              <th className="px-4 py-2 font-medium">#</th>
              <th className="px-4 py-2 font-medium">Symbol</th>
              <th className="px-4 py-2 font-medium text-right">Last</th>
              <th className="px-4 py-2 font-medium text-right">% Δ</th>
              <th className="px-4 py-2 font-medium text-right">RVOL</th>
              <th className="px-4 py-2 font-medium text-right">Score</th>
              <th className="px-4 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {movers.map((m) => {
              const observing = observingSymbols.has(m.symbol);
              const pctTone = m.pct_change >= 0 ? "text-accent-green" : "text-accent-red";
              return (
                <tr
                  key={m.symbol}
                  className="border-t border-border/60 hover:bg-bg-elevated/40"
                >
                  <td className="px-4 py-2 num text-fg-muted">{m.rank}</td>
                  <td className="px-4 py-2 font-medium text-fg">{symbolDisplay(m.symbol)}</td>
                  <td className="px-4 py-2 num text-right">{fmt.num(m.last, 2)}</td>
                  <td className={`px-4 py-2 num text-right ${pctTone}`}>
                    {fmt.pct(m.pct_change, 2)}
                  </td>
                  <td className="px-4 py-2 num text-right">{fmt.num(m.rvol, 2)}</td>
                  <td className="px-4 py-2 num text-right">{fmt.num(m.score, 2)}</td>
                  <td className="px-4 py-2">
                    {observing ? (
                      <span className="badge badge-blue">Observing</span>
                    ) : (
                      <span className="text-xs text-fg-subtle">queued</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
