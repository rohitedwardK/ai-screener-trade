import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { paperApi } from "@/api/client";
import { Badge } from "@/components/Badge";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Stethoscope,
  XCircle,
} from "lucide-react";

const GATE_LABEL: Record<string, string> = {
  live_trading_enabled: "Live trading toggle",
  scheduler_running: "Scheduler heartbeat",
  is_market_open: "NSE market hours",
  screener_has_recent_data: "Screener freshness",
  has_actionable_positions: "Pending / open positions",
};

function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function fmtPrice(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

export function LiveDiagnostics() {
  const [open, setOpen] = useState(false);

  const debug = useQuery({
    queryKey: ["paper-live-debug"],
    queryFn: paperApi.liveDebug,
    enabled: open,
    refetchInterval: open ? 15_000 : false,
  });

  const blockerCount = debug.data?.blockers.length ?? 0;
  const headerTone: "green" | "amber" | "red" =
    !debug.data ? "amber" : blockerCount === 0 ? "green" : "red";

  return (
    <div className="card">
      <button
        type="button"
        className="w-full flex items-center justify-between gap-2 px-4 py-3 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <div className="flex items-center gap-2">
          {open ? (
            <ChevronDown className="size-4 text-fg-muted" />
          ) : (
            <ChevronRight className="size-4 text-fg-muted" />
          )}
          <Stethoscope className="size-4 text-accent-blue" />
          <span className="font-semibold text-sm">Live Diagnostics</span>
        </div>
        <Badge tone={headerTone}>
          {!debug.data
            ? "Click to check"
            : blockerCount === 0
              ? "All gates green"
              : `${blockerCount} blocker${blockerCount > 1 ? "s" : ""}`}
        </Badge>
      </button>

      {open && (
        <div className="border-t border-border p-4 space-y-4 text-sm">
          {debug.isLoading && (
            <div className="text-fg-muted">Running diagnostic…</div>
          )}
          {debug.isError && (
            <div className="flex items-start gap-2 text-accent-red">
              <AlertTriangle className="size-4 mt-0.5" />
              <span>Diagnostic call failed: {(debug.error as Error)?.message}</span>
            </div>
          )}
          {debug.data && (
            <>
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <p className="text-fg">{debug.data.summary}</p>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-fg-subtle">
                    IST {debug.data.now_ist.slice(11, 19)}
                  </span>
                  <button
                    className="btn !py-1 !px-2 text-xs"
                    onClick={() => debug.refetch()}
                    disabled={debug.isFetching}
                  >
                    <RefreshCw
                      className={
                        debug.isFetching
                          ? "size-3 animate-spin"
                          : "size-3"
                      }
                    />
                    Re-check
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {Object.entries(debug.data.gates).map(([key, gate]) => (
                  <div
                    key={key}
                    className="flex items-start gap-2 rounded-md border border-border bg-bg-elevated px-3 py-2"
                  >
                    {gate.ok ? (
                      <CheckCircle2 className="size-4 text-accent-green mt-0.5 shrink-0" />
                    ) : (
                      <XCircle className="size-4 text-accent-red mt-0.5 shrink-0" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-medium">
                        {GATE_LABEL[key] ?? key}
                      </div>
                      {!gate.ok && gate.fix && (
                        <div className="text-[11px] text-fg-muted mt-0.5">
                          {gate.fix}
                        </div>
                      )}
                      {gate.reason && (
                        <div className="text-[11px] text-fg-subtle mt-0.5">
                          {gate.reason}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                <Stat
                  label="Last Run Selection"
                  value={
                    debug.data.last_run_selection.signal_date
                      ? `${debug.data.last_run_selection.signal_date} (${debug.data.last_run_selection.selected} sel / ${debug.data.last_run_selection.skipped} skip)`
                      : "Never"
                  }
                />
                <Stat
                  label="Prices fetched"
                  value={String(debug.data.prices_fetched)}
                />
                <Stat
                  label="Last live tick"
                  value={
                    debug.data.last_live_tick_at
                      ? new Date(debug.data.last_live_tick_at).toLocaleTimeString()
                      : "Never"
                  }
                />
                <Stat
                  label="Pending / Open"
                  value={`${debug.data.pending_positions.length} / ${debug.data.open_positions.length}`}
                />
              </div>

              {debug.data.last_run_selection.top_skip_reasons.length > 0 && (
                <details className="text-xs">
                  <summary className="cursor-pointer text-fg-muted">
                    Why were candidates skipped on{" "}
                    {debug.data.last_run_selection.signal_date}?
                  </summary>
                  <ul className="mt-2 space-y-1">
                    {debug.data.last_run_selection.top_skip_reasons.map((r) => (
                      <li
                        key={r.reason}
                        className="flex items-center justify-between border-b border-border py-1"
                      >
                        <span className="text-fg-muted truncate pr-2">
                          {r.reason}
                        </span>
                        <span className="num text-fg">{r.count}</span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}

              {debug.data.pending_positions.length > 0 && (
                <details className="text-xs" open>
                  <summary className="cursor-pointer text-fg-muted">
                    Pending entries vs live price (
                    {debug.data.pending_positions.length})
                  </summary>
                  <table className="w-full mt-2 text-xs">
                    <thead className="text-fg-subtle">
                      <tr>
                        <th className="text-left py-1">Symbol</th>
                        <th className="text-right py-1">Entry</th>
                        <th className="text-right py-1">Live</th>
                        <th className="text-right py-1">Distance</th>
                        <th className="text-right py-1">Fills now?</th>
                      </tr>
                    </thead>
                    <tbody>
                      {debug.data.pending_positions.map((p) => (
                        <tr key={p.symbol} className="border-t border-border">
                          <td className="py-1">{p.symbol}</td>
                          <td className="py-1 text-right num">
                            {fmtPrice(p.entry_price)}
                          </td>
                          <td className="py-1 text-right num">
                            {fmtPrice(p.last_price)}
                          </td>
                          <td className="py-1 text-right num">
                            {fmtPct(p.distance_to_entry_pct)}
                          </td>
                          <td className="py-1 text-right">
                            {p.would_fill_now ? (
                              <span className="text-accent-green">Yes</span>
                            ) : (
                              <span className="text-fg-muted">No</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              )}

              {debug.data.open_positions.length > 0 && (
                <details className="text-xs">
                  <summary className="cursor-pointer text-fg-muted">
                    Open positions vs stop / targets (
                    {debug.data.open_positions.length})
                  </summary>
                  <table className="w-full mt-2 text-xs">
                    <thead className="text-fg-subtle">
                      <tr>
                        <th className="text-left py-1">Symbol</th>
                        <th className="text-right py-1">Live</th>
                        <th className="text-right py-1">→ Stop</th>
                        <th className="text-right py-1">→ T1</th>
                        <th className="text-right py-1">→ T2</th>
                      </tr>
                    </thead>
                    <tbody>
                      {debug.data.open_positions.map((p) => (
                        <tr key={p.symbol} className="border-t border-border">
                          <td className="py-1">{p.symbol}</td>
                          <td className="py-1 text-right num">
                            {fmtPrice(p.last_price)}
                          </td>
                          <td className="py-1 text-right num">
                            {fmtPct(p.distance_to_stop_pct)}
                          </td>
                          <td className="py-1 text-right num">
                            {fmtPct(p.distance_to_t1_pct)}
                          </td>
                          <td className="py-1 text-right num">
                            {fmtPct(p.distance_to_t2_pct)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              )}

              {debug.data.price_fetch_error && (
                <div className="flex items-start gap-2 text-xs text-accent-red border border-accent-red/30 bg-accent-red/5 rounded-md px-3 py-2">
                  <AlertTriangle className="size-3.5 mt-0.5 shrink-0" />
                  <span>Price fetch error: {debug.data.price_fetch_error}</span>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-bg-elevated px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-fg-subtle">
        {label}
      </div>
      <div className="text-fg num truncate">{value}</div>
    </div>
  );
}
