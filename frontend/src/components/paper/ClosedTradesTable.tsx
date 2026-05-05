import { Link } from "react-router-dom";
import { Badge } from "@/components/Badge";
import { fmt, symbolDisplay } from "@/lib/format";
import type { PaperPosition } from "@/api/types";
import { POSITION_STATUS_TONE } from "@/api/types";

function statusLabel(s: string): string {
  return s.replace(/_/g, " ");
}

export function ClosedTradesTable({ positions }: { positions: PaperPosition[] }) {
  if (positions.length === 0) {
    return (
      <div className="card p-6 text-fg-muted text-sm">
        No closed paper trades yet. They will appear here as targets / stops /
        time-exits are hit.
      </div>
    );
  }

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <h3 className="font-semibold text-sm">Closed Paper Trades</h3>
        <p className="text-xs text-fg-muted">
          {positions.length} closed trade(s). Sorted newest first.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs uppercase tracking-wide text-fg-muted">
            <tr className="border-b border-border">
              <th className="px-3 py-2 text-left">Symbol</th>
              <th className="px-3 py-2 text-left">Setup</th>
              <th className="px-3 py-2 text-left">Entry → Exit</th>
              <th className="px-3 py-2 text-right">Qty</th>
              <th className="px-3 py-2 text-right">Entry</th>
              <th className="px-3 py-2 text-right">Exit</th>
              <th className="px-3 py-2 text-right">P&L</th>
              <th className="px-3 py-2 text-right">Days</th>
              <th className="px-3 py-2 text-left">Result</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => {
              const tone = POSITION_STATUS_TONE[p.status] ?? "muted";
              const pnl = p.realized_pnl;
              const winner = pnl > 0;
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
                  <td className="px-3 py-2 text-xs text-fg-muted">
                    {p.entry_date ?? "—"} → {p.exit_date ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-right num">{p.quantity}</td>
                  <td className="px-3 py-2 text-right num">
                    {fmt.inr(p.entry_price, 1)}
                  </td>
                  <td className="px-3 py-2 text-right num">
                    {fmt.inr(p.exit_price, 1)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right num font-medium ${
                      winner ? "text-accent-green" : "text-accent-red"
                    }`}
                  >
                    {winner ? "+" : ""}
                    {fmt.inr(pnl, 0)}
                  </td>
                  <td className="px-3 py-2 text-right num">
                    {p.holding_days ?? "—"}
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
