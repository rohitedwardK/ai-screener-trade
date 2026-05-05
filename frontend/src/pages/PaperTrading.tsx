import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { paperApi } from "@/api/client";
import { AccountSummary } from "@/components/paper/AccountSummary";
import { BotStatus } from "@/components/paper/BotStatus";
import { TradeCandidatesTable } from "@/components/paper/TradeCandidatesTable";
import { OpenPositionsTable } from "@/components/paper/OpenPositionsTable";
import { ClosedTradesTable } from "@/components/paper/ClosedTradesTable";
import { PerformanceCharts } from "@/components/paper/PerformanceCharts";
import { AIJournalPanel } from "@/components/paper/AIJournalPanel";
import { ConfigPanel } from "@/components/paper/ConfigPanel";
import { ActionsToolbar } from "@/components/paper/ActionsToolbar";
import { LiveDiagnostics } from "@/components/paper/LiveDiagnostics";
import { AlertTriangle, Bot } from "lucide-react";

const POLL_INTERVAL = 30_000;

export function PaperTrading() {
  const [configOpen, setConfigOpen] = useState(false);

  const status = useQuery({
    queryKey: ["paper-status"],
    queryFn: paperApi.getStatus,
    refetchInterval: POLL_INTERVAL,
    refetchIntervalInBackground: false,
  });

  const config = useQuery({
    queryKey: ["paper-config"],
    queryFn: paperApi.getConfig,
  });

  // Latest signals: take a wide net (selected + skipped) and filter by latest date in-memory.
  const signals = useQuery({
    queryKey: ["paper-signals"],
    queryFn: () => paperApi.listSignals({ limit: 200 }),
  });

  const todaysSignals = useMemo(() => {
    if (!signals.data || signals.data.length === 0) {
      return { selected: [], skipped: [], date: null as string | null };
    }
    // Pick the most recent signal_date the bot ran on.
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

  const openPositions = useQuery({
    queryKey: ["paper-positions-open"],
    queryFn: () => paperApi.listPositions({ status: "open", limit: 100 }),
    refetchInterval: POLL_INTERVAL,
  });

  const closedPositions = useQuery({
    queryKey: ["paper-positions-closed"],
    queryFn: () => paperApi.listPositions({ status: "closed", limit: 200 }),
  });

  const performance = useQuery({
    queryKey: ["paper-performance"],
    queryFn: () => paperApi.performance(),
  });

  const journal = useQuery({
    queryKey: ["paper-journal", todaysSignals.date],
    queryFn: () => paperApi.journal(todaysSignals.date ?? undefined),
    enabled: status.isSuccess,
  });

  const isBackendDown = status.isError;

  return (
    <div className="space-y-6">
      <section className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Bot className="size-6 text-accent-violet" />
            Paper Trading
          </h1>
          <p className="text-fg-muted text-sm mt-1">
            Disciplined simulation only — no broker, no real money. Reads
            screener signals, sizes trades, simulates fills against cached
            candles.
          </p>
        </div>
      </section>

      {isBackendDown && (
        <div className="card p-6 text-fg-muted flex items-start gap-2">
          <AlertTriangle className="size-4 text-accent-amber mt-1" />
          <div>
            Backend unreachable. Start the API (
            <code className="text-xs">uvicorn app.main:app --reload</code>) and
            click Refresh, then come back to this page.
          </div>
        </div>
      )}

      {!isBackendDown && (
        <>
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <div className="xl:col-span-2">
              <AccountSummary
                status={status.data}
                performance={performance.data}
              />
            </div>
            <BotStatus status={status.data} />
          </div>

          <ActionsToolbar onOpenConfig={() => setConfigOpen(true)} />

          <LiveDiagnostics />

          <TradeCandidatesTable
            selected={todaysSignals.selected}
            skipped={todaysSignals.skipped}
          />

          <OpenPositionsTable positions={openPositions.data ?? []} />

          <PerformanceCharts performance={performance.data} />

          <ClosedTradesTable positions={closedPositions.data ?? []} />

          <AIJournalPanel journal={journal.data} />

          <div className="card p-3 flex items-start gap-2 text-xs text-fg-muted">
            <AlertTriangle className="size-3.5 mt-0.5 text-accent-amber shrink-0" />
            <span>
              Paper trading simulation only. Not financial advice. Performance
              metrics are computed from simulated fills against cached daily
              candles and do not include slippage, taxes, or broker fees.
            </span>
          </div>
        </>
      )}

      {configOpen && config.data && (
        <ConfigPanel config={config.data} onClose={() => setConfigOpen(false)} />
      )}
    </div>
  );
}
