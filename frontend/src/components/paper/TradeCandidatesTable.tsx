import { Link } from "react-router-dom";
import { Badge } from "@/components/Badge";
import { fmt, symbolDisplay } from "@/lib/format";
import type { PaperTradeSignal } from "@/api/types";
import { CheckCircle2, XCircle } from "lucide-react";

function confidenceTone(conf: string | null): "green" | "amber" | "red" | "muted" {
  if (conf === "High") return "green";
  if (conf === "Medium") return "amber";
  if (conf === "Low") return "red";
  return "muted";
}

function riskTone(risk: string | null): "green" | "amber" | "red" | "muted" {
  if (risk === "Low") return "green";
  if (risk === "Medium") return "amber";
  if (risk === "High") return "red";
  return "muted";
}

export function TradeCandidatesTable({
  selected,
  skipped,
}: {
  selected: PaperTradeSignal[];
  skipped: PaperTradeSignal[];
}) {
  const all = [...selected, ...skipped].sort(
    (a, b) => b.automation_score - a.automation_score
  );

  if (all.length === 0) {
    return (
      <div className="card p-6 text-fg-muted text-sm">
        No paper-trade candidates yet. Run a refresh on the screener and then
        click <strong>Run Selection</strong> in the toolbar.
      </div>
    );
  }

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-sm">Today's Trade Candidates</h3>
          <p className="text-xs text-fg-muted">
            {selected.length} selected · {skipped.length} skipped · ranked by
            automation score
          </p>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs uppercase tracking-wide text-fg-muted">
            <tr className="border-b border-border">
              <th className="px-3 py-2 text-left">Symbol</th>
              <th className="px-3 py-2 text-left">Setup</th>
              <th className="px-3 py-2 text-right">Score</th>
              <th className="px-3 py-2 text-right">Auto</th>
              <th className="px-3 py-2 text-right">R:R</th>
              <th className="px-3 py-2 text-right">Entry</th>
              <th className="px-3 py-2 text-right">Stop</th>
              <th className="px-3 py-2 text-right">Target</th>
              <th className="px-3 py-2 text-left">Confidence</th>
              <th className="px-3 py-2 text-left">Risk</th>
              <th className="px-3 py-2 text-left">Decision</th>
            </tr>
          </thead>
          <tbody>
            {all.map((s) => (
              <tr
                key={s.id}
                className={`border-b border-border last:border-b-0 hover:bg-bg-elevated ${
                  s.decision === "skipped" ? "opacity-70" : ""
                }`}
              >
                <td className="px-3 py-2">
                  <Link
                    to={`/stock/${s.symbol}`}
                    className="font-medium text-fg hover:text-accent-blue"
                  >
                    {symbolDisplay(s.symbol)}
                  </Link>
                  <div className="text-[11px] text-fg-subtle">
                    {s.trend ?? ""}
                  </div>
                </td>
                <td className="px-3 py-2 text-xs text-fg-muted">
                  {s.setup_type}
                </td>
                <td className="px-3 py-2 text-right num">
                  {fmt.num(s.screener_score, 0)}
                </td>
                <td className="px-3 py-2 text-right num font-medium">
                  {fmt.num(s.automation_score, 1)}
                </td>
                <td className="px-3 py-2 text-right num">
                  {s.risk_reward != null ? fmt.num(s.risk_reward, 2) : "—"}
                </td>
                <td className="px-3 py-2 text-right num">
                  {fmt.inr(s.entry, 1)}
                </td>
                <td className="px-3 py-2 text-right num text-accent-red">
                  {fmt.inr(s.stop_loss, 1)}
                </td>
                <td className="px-3 py-2 text-right num text-accent-green">
                  {fmt.inr(s.target_1, 1)}
                </td>
                <td className="px-3 py-2">
                  <Badge tone={confidenceTone(s.confidence)}>
                    {s.confidence ?? "—"}
                  </Badge>
                </td>
                <td className="px-3 py-2">
                  <Badge tone={riskTone(s.risk_level)}>
                    {s.risk_level ?? "—"}
                  </Badge>
                </td>
                <td className="px-3 py-2">
                  {s.decision === "selected" ? (
                    <Badge tone="green">
                      <CheckCircle2 className="size-3" /> Selected
                    </Badge>
                  ) : (
                    <div className="flex flex-col gap-0.5">
                      <Badge tone="muted">
                        <XCircle className="size-3" /> Skipped
                      </Badge>
                      {s.skip_reason && (
                        <span
                          className="text-[10px] text-fg-subtle max-w-[260px] truncate"
                          title={s.skip_reason}
                        >
                          {s.skip_reason}
                        </span>
                      )}
                    </div>
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
