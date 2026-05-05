import { Link } from "react-router-dom";
import { Badge } from "@/components/Badge";
import { fmt, symbolDisplay } from "@/lib/format";
import type { PaperPosition } from "@/api/types";
import { POSITION_STATUS_TONE } from "@/api/types";

function statusLabel(s: string): string {
  return s.replace(/_/g, " ");
}

export function OpenPositionsTable({ positions }: { positions: PaperPosition[] }) {
  if (positions.length === 0) {
    return (
      <div className="card p-6 text-fg-muted text-sm">
        No open paper positions. Once <strong>Run Selection</strong> finds a
        candidate and the next candle fills the entry, it will appear here.
      </div>
    );
  }

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <h3 className="font-semibold text-sm">Open Paper Positions</h3>
        <p className="text-xs text-fg-muted">
          Mark-to-market against the latest cached close.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs uppercase tracking-wide text-fg-muted">
            <tr className="border-b border-border">
              <th className="px-3 py-2 text-left">Symbol</th>
              <th className="px-3 py-2 text-left">Setup</th>
              <th className="px-3 py-2 text-right">Qty</th>
              <th className="px-3 py-2 text-right">Entry</th>
              <th className="px-3 py-2 text-right">Mark</th>
              <th className="px-3 py-2 text-right">Stop</th>
              <th className="px-3 py-2 text-right">T1</th>
              <th className="px-3 py-2 text-right">T2</th>
              <th className="px-3 py-2 text-right">Unrealized</th>
              <th className="px-3 py-2 text-right">Realized</th>
              <th className="px-3 py-2 text-left">Status</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => {
              const tone = POSITION_STATUS_TONE[p.status] ?? "muted";
              const ur = p.unrealized_pnl;
              const rl = p.realized_pnl;
              return (
                <tr
                  key={p.id}
                  className="border-b border-border last:border-b-0 hover:bg-bg-elevated"
                >
                  <td className="px-3 py-2">
                    <Link
                      to={`/stock/${p.symbol}`}
                      className="font-medium text-fg hover:text-accent-blue"
                    >
                      {symbolDisplay(p.symbol)}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-xs text-fg-muted">
                    {p.setup_type}
                  </td>
                  <td className="px-3 py-2 text-right num">
                    {p.remaining_quantity}
                    {p.remaining_quantity !== p.quantity && (
                      <span className="text-fg-subtle"> / {p.quantity}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right num">
                    {fmt.inr(p.entry_price, 1)}
                  </td>
                  <td className="px-3 py-2 text-right num">
                    {fmt.inr(p.current_price, 1)}
                  </td>
                  <td className="px-3 py-2 text-right num text-accent-red">
                    {fmt.inr(p.stop_loss, 1)}
                    {p.breakeven_moved && (
                      <span className="ml-1 text-[10px] text-accent-amber">BE</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right num text-accent-green">
                    {fmt.inr(p.target_1, 1)}
                  </td>
                  <td className="px-3 py-2 text-right num text-accent-green">
                    {fmt.inr(p.target_2, 1)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right num font-medium ${
                      ur >= 0 ? "text-accent-green" : "text-accent-red"
                    }`}
                  >
                    {ur >= 0 ? "+" : ""}
                    {fmt.inr(ur, 0)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right num ${
                      rl >= 0 ? "text-accent-green" : "text-accent-red"
                    }`}
                  >
                    {rl >= 0 ? "+" : ""}
                    {fmt.inr(rl, 0)}
                  </td>
                  <td className="px-3 py-2">
                    <Badge tone={tone}>{statusLabel(p.status)}</Badge>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
