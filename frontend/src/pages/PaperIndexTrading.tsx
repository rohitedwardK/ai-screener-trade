import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Bot,
  Loader2,
  Play,
  Radio,
  Settings,
} from "lucide-react";

import { paperIndexApi } from "@/api/client";
import { Badge } from "@/components/Badge";
import { fmt } from "@/lib/format";
import {
  BOT_STATUS_TONE,
  INDEX_CATEGORY_TONE,
  OPTION_BIAS_TONE,
  POSITION_STATUS_TONE,
  type PaperIndexBotConfig,
  type PaperIndexBotConfigUpdate,
  type PaperIndexLedgerEvent,
  type PaperIndexPosition,
  type PaperIndexStatus,
  type PaperIndexTradeSignal,
} from "@/api/types";

const POLL_INTERVAL = 30_000;

export function PaperIndexTrading() {
  const qc = useQueryClient();
  const [configOpen, setConfigOpen] = useState(false);

  const status = useQuery({
    queryKey: ["paper-index-status"],
    queryFn: paperIndexApi.getStatus,
    refetchInterval: POLL_INTERVAL,
  });
  const config = useQuery({
    queryKey: ["paper-index-config"],
    queryFn: paperIndexApi.getConfig,
  });
  const signals = useQuery({
    queryKey: ["paper-index-signals"],
    queryFn: () => paperIndexApi.listSignals({ limit: 100 }),
  });
  const openPositions = useQuery({
    queryKey: ["paper-index-positions-open"],
    queryFn: () => paperIndexApi.listPositions({ status: "open", limit: 50 }),
    refetchInterval: POLL_INTERVAL,
  });
  const closedPositions = useQuery({
    queryKey: ["paper-index-positions-closed"],
    queryFn: () => paperIndexApi.listPositions({ status: "closed", limit: 50 }),
  });
  const performance = useQuery({
    queryKey: ["paper-index-performance"],
    queryFn: () => paperIndexApi.performance(),
  });
  const journal = useQuery({
    queryKey: ["paper-index-journal"],
    queryFn: () => paperIndexApi.journal(),
    enabled: status.isSuccess,
  });
  const ledger = useQuery({
    queryKey: ["paper-index-ledger"],
    queryFn: () => paperIndexApi.listLedger({ limit: 100 }),
  });

  const todaySignals = useMemo(() => {
    if (!signals.data || signals.data.length === 0) {
      return { selected: [], skipped: [], date: null as string | null };
    }
    const latest = signals.data
      .map((s) => s.signal_date)
      .sort()
      .at(-1);
    if (!latest) return { selected: [], skipped: [], date: null };
    const slice = signals.data.filter((s) => s.signal_date === latest);
    return {
      date: latest,
      selected: slice.filter((s) => s.decision === "selected"),
      skipped: slice.filter((s) => s.decision === "skipped"),
    };
  }, [signals.data]);

  const runSelectionMut = useMutation({
    mutationFn: () => paperIndexApi.runSelection(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["paper-index-signals"] });
      qc.invalidateQueries({ queryKey: ["paper-index-status"] });
      qc.invalidateQueries({ queryKey: ["paper-index-positions-open"] });
    },
  });
  const simulateDayMut = useMutation({
    mutationFn: () => paperIndexApi.simulateDay(),
    onSuccess: () => qc.invalidateQueries(),
  });
  const liveTickMut = useMutation({
    mutationFn: () => paperIndexApi.processLiveTick(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["paper-index-status"] });
      qc.invalidateQueries({ queryKey: ["paper-index-positions-open"] });
      qc.invalidateQueries({ queryKey: ["paper-index-positions-closed"] });
      qc.invalidateQueries({ queryKey: ["paper-index-ledger"] });
    },
  });

  const isBackendDown = status.isError;

  return (
    <div className="space-y-6">
      <section className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Bot className="size-6 text-accent-cyan" />
            Paper Index Bot
          </h1>
          <p className="text-fg-muted text-sm mt-1">
            Options-only paper bot for Nifty / Bank Nifty / Sensex. Buys ATM
            CE/PE based on screener signals + option-chain bias. Max 5 trades
            per day. Simulation only.
          </p>
        </div>
      </section>

      {isBackendDown && (
        <div className="card p-6 text-fg-muted flex items-start gap-2">
          <AlertTriangle className="size-4 text-accent-amber mt-1" />
          Backend unreachable. Start the API and trigger an index refresh.
        </div>
      )}

      {!isBackendDown && (
        <>
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <div className="xl:col-span-2">
              <AccountSummary status={status.data} />
            </div>
            <BotStatusPanel status={status.data} />
          </div>

          <TradeManagerAgentCard
            status={status.data}
            onProcessTick={() => liveTickMut.mutate()}
            isProcessing={liveTickMut.isPending}
            lastResult={liveTickMut.data}
          />

          <div className="card p-3 flex items-center gap-2 flex-wrap">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => runSelectionMut.mutate()}
              disabled={runSelectionMut.isPending}
            >
              {runSelectionMut.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Play className="size-4" />
              )}
              <span>Run selection</span>
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => simulateDayMut.mutate()}
              disabled={simulateDayMut.isPending}
            >
              {simulateDayMut.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Play className="size-4" />
              )}
              <span>Simulate day</span>
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => liveTickMut.mutate()}
              disabled={liveTickMut.isPending}
            >
              {liveTickMut.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Radio className="size-4" />
              )}
              <span>Process tick now</span>
            </button>
            <button
              type="button"
              className="btn ml-auto"
              onClick={() => setConfigOpen(true)}
            >
              <Settings className="size-4" />
              <span>Bot config</span>
            </button>
          </div>

          <SignalsTable signals={todaySignals} />
          <OpenPositionsTable positions={openPositions.data ?? []} />
          <ClosedPositionsTable positions={closedPositions.data ?? []} />
          <LedgerTable events={ledger.data ?? []} />

          {performance.data && (
            <PerformanceCard performance={performance.data} />
          )}

          {journal.data && (
            <div className="card p-4 space-y-2">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold tracking-tight">AI Journal</h2>
                <Badge tone="muted">{journal.data.provider}</Badge>
              </div>
              <p className="text-sm text-fg whitespace-pre-line">
                {journal.data.summary}
              </p>
            </div>
          )}

          <div className="card p-3 flex items-start gap-2 text-xs text-fg-muted">
            <AlertTriangle className="size-3.5 mt-0.5 text-accent-amber shrink-0" />
            Paper trading simulation only. Not financial advice. Index option
            P&L is approximated from a fixed delta and does not include theta
            decay, IV crush, slippage, or broker fees.
          </div>
        </>
      )}

      {configOpen && config.data && (
        <ConfigDialog
          config={config.data}
          onClose={() => setConfigOpen(false)}
        />
      )}
    </div>
  );
}

// ---------- Account / status ----------

function AccountSummary({ status }: { status?: PaperIndexStatus }) {
  const totalPnl =
    (status?.realized_pnl_total ?? 0) + (status?.unrealized_pnl_total ?? 0);
  const startCapital = status?.virtual_capital ?? 0;
  const totalReturnPct =
    startCapital > 0 ? (totalPnl / startCapital) * 100 : 0;

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="font-semibold">Paper Account</h2>
          <p className="text-xs text-fg-muted mt-0.5">
            Simulated capital — options premium-based P&L.
          </p>
        </div>
        <div className="text-right">
          <div className="text-xs text-fg-muted">Equity</div>
          <div className="num text-2xl font-semibold">
            ₹{fmt.inr(status?.current_equity, 0)}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
        <KV
          label="Virtual capital"
          value={`₹${fmt.inr(status?.virtual_capital ?? 0, 0)}`}
        />
        <KV
          label="Total P&L"
          value={`${totalPnl >= 0 ? "+" : ""}₹${fmt.inr(totalPnl, 0)}`}
          tone={totalPnl >= 0 ? "green" : "red"}
          hint={`${totalReturnPct >= 0 ? "+" : ""}${fmt.num(totalReturnPct, 2)}%`}
        />
        <KV
          label="Realized today"
          value={`${(status?.realized_pnl_today ?? 0) >= 0 ? "+" : ""}₹${fmt.inr(
            status?.realized_pnl_today ?? 0,
            0,
          )}`}
          tone={(status?.realized_pnl_today ?? 0) >= 0 ? "green" : "red"}
        />
        <KV
          label="Unrealized"
          value={`${(status?.unrealized_pnl_total ?? 0) >= 0 ? "+" : ""}₹${fmt.inr(
            status?.unrealized_pnl_total ?? 0,
            0,
          )}`}
          tone={(status?.unrealized_pnl_total ?? 0) >= 0 ? "green" : "red"}
        />
        <KV
          label="Trades today"
          value={`${status?.trades_taken_today ?? 0} / ${
            (status?.trades_taken_today ?? 0) +
            (status?.remaining_trades_today ?? 0)
          }`}
        />
        <KV
          label="Open positions"
          value={String(status?.open_positions ?? 0)}
        />
        <KV
          label="Daily loss limit"
          value={`${fmt.num(status?.daily_loss_limit_percent ?? 0, 1)}%`}
        />
        <KV label="Market regime" value={status?.market_regime ?? "—"} />
      </div>
    </div>
  );
}

function TradeManagerAgentCard({
  status,
  onProcessTick,
  isProcessing,
  lastResult,
}: {
  status?: PaperIndexStatus;
  onProcessTick: () => void;
  isProcessing: boolean;
  lastResult?: {
    processed_at: string;
    symbols_priced: number;
    exits_triggered: number;
    realized_pnl_today: number;
    bot_status: string;
  };
}) {
  const enabled = status?.live_trading_enabled ?? false;
  const open = status?.is_market_open ?? false;
  const lastTick = status?.last_live_tick_at ?? lastResult?.processed_at ?? null;
  const agentTone: "green" | "amber" | "muted" = enabled
    ? open
      ? "green"
      : "amber"
    : "muted";
  const agentLabel = enabled
    ? open
      ? "Active"
      : "Idle (market closed)"
    : "Disabled";

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold tracking-tight flex items-center gap-2">
            <Activity className="size-4 text-accent-cyan" />
            Trade Manager Agent
          </h2>
          <p className="text-xs text-fg-muted mt-0.5">
            Polls live spot every minute during NSE hours and walks open
            positions through SL / T1 / T2 / breakeven trail. Simulation
            only - never opens new positions intraday.
          </p>
        </div>
        <Badge tone={agentTone}>{agentLabel}</Badge>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
        <KV
          label="Enabled"
          value={enabled ? "Yes" : "No"}
          tone={enabled ? "green" : "muted"}
        />
        <KV
          label="Market"
          value={open ? "Open" : "Closed"}
          tone={open ? "green" : "muted"}
        />
        <KV
          label="Last tick"
          value={lastTick ? new Date(lastTick).toLocaleTimeString() : "—"}
        />
        <KV
          label="Last priced"
          value={
            lastResult?.symbols_priced != null
              ? String(lastResult.symbols_priced)
              : "—"
          }
          hint={
            lastResult?.exits_triggered != null
              ? `${lastResult.exits_triggered} exits`
              : undefined
          }
        />
      </div>
      <p className="text-[11px] text-fg-subtle">
        Toggle the agent on from Bot config &rarr; Live trading enabled.
        yfinance Indian-index 1-min bars are ~15 minutes delayed.
      </p>
      {/* Manual button is in the action toolbar so the agent panel stays compact. */}
      <button
        type="button"
        className="btn w-full"
        onClick={onProcessTick}
        disabled={isProcessing}
      >
        {isProcessing ? (
          <Loader2 className="size-4 animate-spin" />
        ) : (
          <Radio className="size-4" />
        )}
        <span>Run agent tick now</span>
      </button>
    </div>
  );
}

function BotStatusPanel({ status }: { status?: PaperIndexStatus }) {
  if (!status) {
    return (
      <div className="card p-4 flex items-center gap-2 text-fg-muted">
        <Loader2 className="size-4 animate-spin" />
        Loading status…
      </div>
    );
  }
  const tone = BOT_STATUS_TONE[status.bot_status] ?? "muted";
  return (
    <div className="card p-4 space-y-3">
      <div>
        <h2 className="font-semibold">Bot status</h2>
        <p className="text-xs text-fg-muted">Kill-switch evaluation</p>
      </div>
      <Badge tone={tone}>{status.bot_status.replace(/_/g, " ")}</Badge>
      {status.reason && (
        <div className="text-xs text-fg-muted leading-relaxed">
          {status.reason}
        </div>
      )}
      <p className="text-[11px] text-fg-subtle pt-2 border-t border-border">
        {status.disclaimer}
      </p>
    </div>
  );
}

// ---------- Tables ----------

function SignalsTable({
  signals,
}: {
  signals: {
    selected: PaperIndexTradeSignal[];
    skipped: PaperIndexTradeSignal[];
    date: string | null;
  };
}) {
  const allRows = [...signals.selected, ...signals.skipped];
  return (
    <div className="card p-4 space-y-2">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-semibold tracking-tight">Today's Candidates</h2>
          <p className="text-xs text-fg-muted">
            {signals.date ? `Run for ${signals.date}` : "No run yet"} ·{" "}
            {signals.selected.length} selected · {signals.skipped.length} skipped
          </p>
        </div>
      </div>
      {allRows.length === 0 ? (
        <p className="text-xs text-fg-muted">
          No signals yet. Trigger Run selection above.
        </p>
      ) : (
        <div className="overflow-x-auto -mx-4">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-fg-subtle text-[11px] uppercase">
                <th className="text-left px-3 py-1.5">Index</th>
                <th className="text-left px-3 py-1.5">Setup</th>
                <th className="text-left px-3 py-1.5">Side</th>
                <th className="text-right px-3 py-1.5">Score</th>
                <th className="text-right px-3 py-1.5">R:R</th>
                <th className="text-right px-3 py-1.5">Strike</th>
                <th className="text-right px-3 py-1.5">Lots</th>
                <th className="text-right px-3 py-1.5">Premium</th>
                <th className="text-left px-3 py-1.5">Chain</th>
                <th className="text-left px-3 py-1.5">Decision</th>
              </tr>
            </thead>
            <tbody>
              {allRows.map((s) => (
                <tr
                  key={s.id}
                  className="hover:bg-bg-elevated/40 transition border-t border-border"
                >
                  <td className="px-3 py-1.5">
                    <div className="font-medium">{s.code}</div>
                    <div className="text-[11px] text-fg-subtle">{s.symbol}</div>
                  </td>
                  <td className="px-3 py-1.5">
                    <Badge
                      tone={
                        INDEX_CATEGORY_TONE[
                          s.setup_type
                            .toUpperCase()
                            .replace(/ /g, "_") as keyof typeof INDEX_CATEGORY_TONE
                        ] ?? "muted"
                      }
                    >
                      {s.setup_type}
                    </Badge>
                  </td>
                  <td className="px-3 py-1.5">
                    <Badge tone={s.direction === "LONG" ? "green" : "red"}>
                      {s.option_type}
                    </Badge>
                  </td>
                  <td className="px-3 py-1.5 text-right num">
                    {fmt.num(s.automation_score, 1)}
                  </td>
                  <td className="px-3 py-1.5 text-right num">
                    {fmt.num(s.risk_reward, 2)}
                  </td>
                  <td className="px-3 py-1.5 text-right num">
                    {fmt.num(s.strike, 0)}
                  </td>
                  <td className="px-3 py-1.5 text-right num">
                    {s.lots ?? "—"}
                  </td>
                  <td className="px-3 py-1.5 text-right num">
                    {fmt.num(s.entry_premium, 2)}
                  </td>
                  <td className="px-3 py-1.5">
                    {s.option_chain_bias ? (
                      <Badge
                        tone={
                          OPTION_BIAS_TONE[s.option_chain_bias] ?? "muted"
                        }
                      >
                        {s.option_chain_bias}
                      </Badge>
                    ) : (
                      <span className="text-fg-subtle text-xs">—</span>
                    )}
                  </td>
                  <td className="px-3 py-1.5">
                    <Badge tone={s.decision === "selected" ? "green" : "muted"}>
                      {s.decision}
                    </Badge>
                    {s.skip_reason && (
                      <div className="text-[11px] text-fg-subtle mt-0.5 max-w-xs truncate">
                        {s.skip_reason}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function OpenPositionsTable({
  positions,
}: {
  positions: PaperIndexPosition[];
}) {
  return (
    <div className="card p-4 space-y-2">
      <h2 className="font-semibold tracking-tight">Open Positions</h2>
      {positions.length === 0 ? (
        <p className="text-xs text-fg-muted">No open positions.</p>
      ) : (
        <div className="overflow-x-auto -mx-4">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-fg-subtle text-[11px] uppercase">
                <th className="text-left px-3 py-1.5">Index</th>
                <th className="text-left px-3 py-1.5">Contract</th>
                <th className="text-right px-3 py-1.5">Entry Spot</th>
                <th className="text-right px-3 py-1.5">Entry Prem</th>
                <th className="text-right px-3 py-1.5">Stop</th>
                <th className="text-right px-3 py-1.5">T1</th>
                <th className="text-right px-3 py-1.5">T2</th>
                <th className="text-right px-3 py-1.5">Lots</th>
                <th className="text-right px-3 py-1.5">Unrealized</th>
                <th className="text-left px-3 py-1.5">Status</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr
                  key={p.id}
                  className="hover:bg-bg-elevated/40 transition border-t border-border"
                >
                  <td className="px-3 py-1.5">
                    <div className="font-medium">{p.code}</div>
                    <div className="text-[11px] text-fg-subtle">
                      {p.setup_type}
                    </div>
                  </td>
                  <td className="px-3 py-1.5">
                    <Badge tone={p.direction === "LONG" ? "green" : "red"}>
                      {p.option_type} {fmt.num(p.strike, 0)}
                    </Badge>
                    <div className="text-[11px] text-fg-subtle mt-0.5">
                      Exp {p.expiry}
                    </div>
                  </td>
                  <td className="px-3 py-1.5 text-right num">
                    {fmt.num(p.entry_spot, 2)}
                  </td>
                  <td className="px-3 py-1.5 text-right num">
                    {fmt.num(p.entry_premium, 2)}
                  </td>
                  <td className="px-3 py-1.5 text-right num text-accent-red">
                    {fmt.num(p.stop_loss, 2)}
                  </td>
                  <td className="px-3 py-1.5 text-right num text-accent-green">
                    {fmt.num(p.target_1, 2)}
                  </td>
                  <td className="px-3 py-1.5 text-right num text-accent-green">
                    {fmt.num(p.target_2, 2)}
                  </td>
                  <td className="px-3 py-1.5 text-right num">{p.lots}</td>
                  <td
                    className={`px-3 py-1.5 text-right num ${
                      p.unrealized_pnl >= 0
                        ? "text-accent-green"
                        : "text-accent-red"
                    }`}
                  >
                    {p.unrealized_pnl >= 0 ? "+" : ""}₹
                    {fmt.inr(p.unrealized_pnl, 0)}
                  </td>
                  <td className="px-3 py-1.5">
                    <Badge tone={POSITION_STATUS_TONE[p.status] ?? "muted"}>
                      {p.status.replace(/_/g, " ")}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ClosedPositionsTable({
  positions,
}: {
  positions: PaperIndexPosition[];
}) {
  if (positions.length === 0) return null;
  return (
    <div className="card p-4 space-y-2">
      <h2 className="font-semibold tracking-tight">Closed Trades</h2>
      <div className="overflow-x-auto -mx-4">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-fg-subtle text-[11px] uppercase">
              <th className="text-left px-3 py-1.5">Index</th>
              <th className="text-left px-3 py-1.5">Contract</th>
              <th className="text-left px-3 py-1.5">Reason</th>
              <th className="text-right px-3 py-1.5">Entry</th>
              <th className="text-right px-3 py-1.5">Exit</th>
              <th className="text-right px-3 py-1.5">Lots</th>
              <th className="text-right px-3 py-1.5">P&L</th>
              <th className="text-left px-3 py-1.5">Status</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr
                key={p.id}
                className="hover:bg-bg-elevated/40 transition border-t border-border"
              >
                <td className="px-3 py-1.5">
                  <div className="font-medium">{p.code}</div>
                  <div className="text-[11px] text-fg-subtle">
                    {p.setup_type}
                  </div>
                </td>
                <td className="px-3 py-1.5">
                  <Badge tone={p.direction === "LONG" ? "green" : "red"}>
                    {p.option_type} {fmt.num(p.strike, 0)}
                  </Badge>
                </td>
                <td className="px-3 py-1.5 text-xs text-fg-muted">
                  {p.exit_reason ?? "—"}
                </td>
                <td className="px-3 py-1.5 text-right num">
                  {fmt.num(p.entry_premium, 2)}
                </td>
                <td className="px-3 py-1.5 text-right num">
                  {fmt.num(p.exit_price, 2)}
                </td>
                <td className="px-3 py-1.5 text-right num">{p.lots}</td>
                <td
                  className={`px-3 py-1.5 text-right num ${
                    p.realized_pnl >= 0 ? "text-accent-green" : "text-accent-red"
                  }`}
                >
                  {p.realized_pnl >= 0 ? "+" : ""}₹{fmt.inr(p.realized_pnl, 0)}
                </td>
                <td className="px-3 py-1.5">
                  <Badge tone={POSITION_STATUS_TONE[p.status] ?? "muted"}>
                    {p.status.replace(/_/g, " ")}
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LedgerTable({ events }: { events: PaperIndexLedgerEvent[] }) {
  if (events.length === 0) return null;
  return (
    <div className="card p-4 space-y-2">
      <h2 className="font-semibold tracking-tight">Event Ledger</h2>
      <div className="overflow-x-auto -mx-4 max-h-96 overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-bg-elevated">
            <tr className="text-fg-subtle text-[11px] uppercase">
              <th className="text-left px-3 py-1.5">Date</th>
              <th className="text-left px-3 py-1.5">Event</th>
              <th className="text-left px-3 py-1.5">Index</th>
              <th className="text-right px-3 py-1.5">Qty</th>
              <th className="text-right px-3 py-1.5">Price</th>
              <th className="text-right px-3 py-1.5">P&L</th>
              <th className="text-left px-3 py-1.5">Note</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <tr
                key={e.id}
                className="hover:bg-bg-elevated/40 transition border-t border-border"
              >
                <td className="px-3 py-1.5 text-xs text-fg-muted">{e.date}</td>
                <td className="px-3 py-1.5 text-xs">
                  {e.event_type.replace(/_/g, " ")}
                </td>
                <td className="px-3 py-1.5 text-xs">
                  {e.code} {e.option_type} {fmt.num(e.strike, 0)}
                </td>
                <td className="px-3 py-1.5 text-right num">{e.quantity}</td>
                <td className="px-3 py-1.5 text-right num">
                  {fmt.num(e.price, 2)}
                </td>
                <td
                  className={`px-3 py-1.5 text-right num ${
                    e.pnl >= 0 ? "text-accent-green" : "text-accent-red"
                  }`}
                >
                  {e.pnl ? `${e.pnl >= 0 ? "+" : ""}₹${fmt.inr(e.pnl, 0)}` : "—"}
                </td>
                <td className="px-3 py-1.5 text-xs text-fg-muted truncate max-w-xs">
                  {e.note ?? ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PerformanceCard({
  performance,
}: {
  performance: NonNullable<
    Awaited<ReturnType<typeof paperIndexApi.performance>>
  >;
}) {
  return (
    <div className="card p-4 space-y-2">
      <h2 className="font-semibold tracking-tight">Performance</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
        <KV label="Trades" value={String(performance.total_trades)} />
        <KV
          label="Win rate"
          value={`${fmt.num(performance.win_rate, 1)}%`}
          hint={`${performance.winning_trades}W / ${performance.losing_trades}L`}
        />
        <KV
          label="Profit factor"
          value={fmt.num(performance.profit_factor, 2)}
        />
        <KV
          label="Expectancy"
          value={`₹${fmt.inr(performance.expectancy, 0)}`}
        />
        <KV
          label="Avg win"
          value={`₹${fmt.inr(performance.average_win, 0)}`}
          tone="green"
        />
        <KV
          label="Avg loss"
          value={`₹${fmt.inr(performance.average_loss, 0)}`}
          tone="red"
        />
        <KV
          label="Max DD"
          value={`${fmt.num(performance.max_drawdown_percent, 2)}%`}
          tone="amber"
        />
        <KV
          label="Avg holding"
          value={`${fmt.num(performance.average_holding_days, 1)} d`}
        />
      </div>
    </div>
  );
}

function ConfigDialog({
  config,
  onClose,
}: {
  config: PaperIndexBotConfig;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<PaperIndexBotConfigUpdate>({});
  const updateMut = useMutation({
    mutationFn: (patch: PaperIndexBotConfigUpdate) =>
      paperIndexApi.updateConfig(patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["paper-index-config"] });
      qc.invalidateQueries({ queryKey: ["paper-index-status"] });
      onClose();
    },
  });

  const setField = <K extends keyof PaperIndexBotConfigUpdate>(
    key: K,
    value: PaperIndexBotConfigUpdate[K],
  ) => setDraft((d) => ({ ...d, [key]: value }));

  return (
    <div className="fixed inset-0 z-40 bg-black/50 flex items-center justify-center p-4">
      <div className="card p-5 w-full max-w-lg space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold">Paper-index bot config</h3>
          <button className="btn" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <NumField
            label="Virtual capital"
            value={draft.virtual_capital ?? config.virtual_capital}
            onChange={(v) => setField("virtual_capital", v)}
          />
          <NumField
            label="Max trades / day"
            value={draft.max_trades_per_day ?? config.max_trades_per_day}
            step={1}
            onChange={(v) => setField("max_trades_per_day", Math.round(v))}
          />
          <NumField
            label="Max risk / trade %"
            value={
              draft.max_risk_per_trade_percent ??
              config.max_risk_per_trade_percent
            }
            step={0.1}
            onChange={(v) => setField("max_risk_per_trade_percent", v)}
          />
          <NumField
            label="Max daily loss %"
            value={draft.max_daily_loss_percent ?? config.max_daily_loss_percent}
            step={0.1}
            onChange={(v) => setField("max_daily_loss_percent", v)}
          />
          <NumField
            label="Min score"
            value={draft.min_score ?? config.min_score}
            step={1}
            onChange={(v) => setField("min_score", v)}
          />
          <NumField
            label="Min R:R"
            value={draft.min_risk_reward ?? config.min_risk_reward}
            step={0.1}
            onChange={(v) => setField("min_risk_reward", v)}
          />
          <SelectField
            label="Moneyness"
            value={draft.option_moneyness ?? config.option_moneyness}
            options={["ATM", "ITM1", "OTM1"]}
            onChange={(v) => setField("option_moneyness", v)}
          />
          <NumField
            label="Delta estimate"
            value={draft.option_delta_estimate ?? config.option_delta_estimate}
            step={0.05}
            onChange={(v) => setField("option_delta_estimate", v)}
          />
          <SelectField
            label="Same-candle policy"
            value={draft.same_candle_policy ?? config.same_candle_policy}
            options={["conservative", "optimistic", "ohlc_approx"]}
            onChange={(v) => setField("same_candle_policy", v)}
          />
          <NumField
            label="Intraday signal min"
            value={
              draft.intraday_signal_minutes ?? config.intraday_signal_minutes
            }
            step={1}
            onChange={(v) => setField("intraday_signal_minutes", Math.round(v))}
          />
          <NumField
            label="Entry expiry (days)"
            value={
              draft.entry_order_expiry_days ?? config.entry_order_expiry_days
            }
            step={1}
            onChange={(v) =>
              setField("entry_order_expiry_days", Math.max(1, Math.round(v)))
            }
          />
          <NumField
            label="Max holding (days)"
            value={draft.max_holding_days ?? config.max_holding_days}
            step={1}
            onChange={(v) =>
              setField("max_holding_days", Math.max(1, Math.round(v)))
            }
          />
          <NumField
            label="Intraday horizon (days)"
            value={
              draft.intraday_horizon_days ?? config.intraday_horizon_days
            }
            step={1}
            onChange={(v) =>
              setField("intraday_horizon_days", Math.max(1, Math.round(v)))
            }
          />
          <BoolField
            label="Trailing stop"
            value={draft.trailing_stop_enabled ?? config.trailing_stop_enabled}
            onChange={(v) => setField("trailing_stop_enabled", v)}
          />
          <BoolField
            label="Use chain bias"
            value={draft.use_option_chain_bias ?? config.use_option_chain_bias}
            onChange={(v) => setField("use_option_chain_bias", v)}
          />
          <BoolField
            label="Live trading enabled"
            value={draft.live_trading_enabled ?? config.live_trading_enabled}
            onChange={(v) => setField("live_trading_enabled", v)}
          />
          <NumField
            label="Live poll seconds"
            value={
              draft.live_poll_interval_seconds ??
              config.live_poll_interval_seconds
            }
            step={1}
            onChange={(v) =>
              setField("live_poll_interval_seconds", Math.max(15, Math.round(v)))
            }
          />
        </div>
        <div className="flex items-center justify-end gap-2 pt-2 border-t border-border">
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            disabled={updateMut.isPending || Object.keys(draft).length === 0}
            onClick={() => updateMut.mutate(draft)}
          >
            {updateMut.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : null}
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

function NumField({
  label,
  value,
  step,
  onChange,
}: {
  label: string;
  value: number;
  step?: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-fg-muted">{label}</span>
      <input
        type="number"
        step={step ?? 0.01}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="input"
      />
    </label>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-fg-muted">{label}</span>
      <select
        className="input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

function BoolField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2">
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="text-xs text-fg-muted">{label}</span>
    </label>
  );
}

function KV({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "green" | "red" | "amber" | "blue" | "muted";
}) {
  const toneClass = {
    green: "text-accent-green",
    red: "text-accent-red",
    amber: "text-accent-amber",
    blue: "text-accent-blue",
    muted: "text-fg",
  }[tone ?? "muted"];
  return (
    <div className="flex flex-col gap-0.5">
      <div className="text-xs text-fg-muted">{label}</div>
      <div className={`num text-base font-semibold ${toneClass}`}>{value}</div>
      {hint && <div className="text-[11px] text-fg-subtle">{hint}</div>}
    </div>
  );
}
