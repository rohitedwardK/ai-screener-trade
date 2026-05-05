import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { paperApi } from "@/api/client";
import type { PaperReplay } from "@/api/types";
import {
  AlertTriangle,
  Calendar,
  History,
  Loader2,
  Play,
  Radio,
  RotateCcw,
  Settings,
  Wand2,
} from "lucide-react";

const todayIso = () => new Date().toISOString().slice(0, 10);

function isoDaysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

export function ActionsToolbar({
  onOpenConfig,
}: {
  onOpenConfig: () => void;
}) {
  const qc = useQueryClient();
  const [replayStart, setReplayStart] = useState<string>(isoDaysAgo(30));
  const [replayEnd, setReplayEnd] = useState<string>(todayIso());
  const [replayResult, setReplayResult] = useState<PaperReplay | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["paper-status"] });
    qc.invalidateQueries({ queryKey: ["paper-signals"] });
    qc.invalidateQueries({ queryKey: ["paper-positions-open"] });
    qc.invalidateQueries({ queryKey: ["paper-positions-closed"] });
    qc.invalidateQueries({ queryKey: ["paper-performance"] });
    qc.invalidateQueries({ queryKey: ["paper-journal"] });
  };

  const runSelection = useMutation({
    mutationFn: () => paperApi.runSelection(),
    onSuccess: () => {
      setErrorMsg(null);
      invalidateAll();
    },
    onError: (e: any) =>
      setErrorMsg(e?.response?.data?.detail ?? e?.message ?? "Run-selection failed"),
  });

  const simulateDay = useMutation({
    mutationFn: () => paperApi.simulateDay(),
    onSuccess: () => {
      setErrorMsg(null);
      invalidateAll();
    },
    onError: (e: any) =>
      setErrorMsg(e?.response?.data?.detail ?? e?.message ?? "Simulate-day failed"),
  });

  const liveTick = useMutation({
    mutationFn: () => paperApi.processLiveTick(),
    onSuccess: () => {
      setErrorMsg(null);
      invalidateAll();
      qc.invalidateQueries({ queryKey: ["paper-ledger"] });
    },
    onError: (e: any) =>
      setErrorMsg(e?.response?.data?.detail ?? e?.message ?? "Live-tick failed"),
  });

  const replay = useMutation({
    mutationFn: () => paperApi.replay(replayStart, replayEnd),
    onSuccess: (data) => {
      setErrorMsg(null);
      setReplayResult(data);
      invalidateAll();
    },
    onError: (e: any) =>
      setErrorMsg(e?.response?.data?.detail ?? e?.message ?? "Replay failed"),
  });

  const reset = useMutation({
    mutationFn: () => paperApi.reset(),
    onSuccess: () => {
      setErrorMsg(null);
      setConfirmReset(false);
      setReplayResult(null);
      invalidateAll();
    },
    onError: (e: any) =>
      setErrorMsg(e?.response?.data?.detail ?? e?.message ?? "Reset failed"),
  });

  const busy =
    runSelection.isPending ||
    simulateDay.isPending ||
    liveTick.isPending ||
    replay.isPending ||
    reset.isPending;

  return (
    <div className="card p-3 flex flex-wrap items-center gap-2">
      <button
        className="btn btn-primary"
        onClick={() => runSelection.mutate()}
        disabled={busy}
        title="Read latest screener signals, apply rules, open PENDING_ENTRY positions"
      >
        {runSelection.isPending ? (
          <Loader2 className="size-4 animate-spin" />
        ) : (
          <Wand2 className="size-4" />
        )}
        Run Selection
      </button>

      <button
        className="btn"
        onClick={() => simulateDay.mutate()}
        disabled={busy}
        title="Fill pending entries, walk open positions for stops/targets, mark-to-market"
      >
        {simulateDay.isPending ? (
          <Loader2 className="size-4 animate-spin" />
        ) : (
          <Play className="size-4" />
        )}
        Simulate Day
      </button>

      <button
        className="btn"
        onClick={() => liveTick.mutate()}
        disabled={busy}
        title="Fetch live yfinance prices now and apply fills/exits to PENDING/OPEN positions"
      >
        {liveTick.isPending ? (
          <Loader2 className="size-4 animate-spin" />
        ) : (
          <Radio className="size-4" />
        )}
        Process Live Tick
      </button>

      <div className="flex items-center gap-1.5 ml-2">
        <Calendar className="size-3.5 text-fg-muted" />
        <input
          type="date"
          className="input"
          value={replayStart}
          onChange={(e) => setReplayStart(e.target.value)}
        />
        <span className="text-fg-subtle text-xs">→</span>
        <input
          type="date"
          className="input"
          value={replayEnd}
          onChange={(e) => setReplayEnd(e.target.value)}
        />
        <button
          className="btn"
          onClick={() => replay.mutate()}
          disabled={busy || !replayStart || !replayEnd}
          title="Replay from cached CSVs day-by-day (no look-ahead)"
        >
          {replay.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <History className="size-4" />
          )}
          Replay
        </button>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <button className="btn" onClick={onOpenConfig} disabled={busy}>
          <Settings className="size-4" />
          Config
        </button>
        {confirmReset ? (
          <div className="flex items-center gap-1 rounded-md border border-accent-red/40 bg-accent-red/10 px-2 py-1">
            <span className="text-xs text-accent-red">Reset paper state?</span>
            <button
              className="btn !border-accent-red/40 !bg-accent-red/15 !text-accent-red !py-0.5 !px-2 !text-xs"
              onClick={() => reset.mutate()}
              disabled={reset.isPending}
            >
              {reset.isPending ? (
                <Loader2 className="size-3 animate-spin" />
              ) : (
                "Yes, wipe"
              )}
            </button>
            <button
              className="text-xs text-fg-muted hover:text-fg px-2"
              onClick={() => setConfirmReset(false)}
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            className="btn"
            onClick={() => setConfirmReset(true)}
            disabled={busy}
            title="Wipe all paper trades, positions, and ledger entries (config retained)"
          >
            <RotateCcw className="size-4" />
            Reset
          </button>
        )}
      </div>

      {errorMsg && (
        <div className="basis-full flex items-start gap-2 rounded-md border border-accent-red/30 bg-accent-red/5 px-3 py-2 text-xs text-accent-red">
          <AlertTriangle className="size-3.5 mt-0.5 shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      {replayResult && (
        <div className="basis-full text-xs text-fg-muted border-t border-border pt-2 mt-1 flex items-center gap-3 flex-wrap">
          <span>
            Replayed <strong>{replayResult.days_processed}</strong> day(s) from{" "}
            {replayResult.start} to {replayResult.end}.
          </span>
          <span>
            Final equity: <strong>₹{replayResult.final_equity.toLocaleString("en-IN")}</strong>
          </span>
          <span>
            Total realized P&L:{" "}
            <strong
              className={
                replayResult.total_realized_pnl >= 0
                  ? "text-accent-green"
                  : "text-accent-red"
              }
            >
              {replayResult.total_realized_pnl >= 0 ? "+" : ""}
              ₹{replayResult.total_realized_pnl.toLocaleString("en-IN")}
            </strong>
          </span>
        </div>
      )}
    </div>
  );
}
