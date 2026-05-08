import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import {
  Activity,
  AlertTriangle,
  Loader2,
  Play,
  Sparkles,
  Workflow,
} from "lucide-react";
import { agentsApi } from "@/api/client";
import type { AgentRunRow, AgentRunStatus } from "@/api/types";
import { AGENT_LABEL } from "@/api/types";
import { AgentStatusCard } from "@/components/agents/AgentStatusCard";
import { DailyBriefingPanel } from "@/components/agents/DailyBriefingPanel";

const WORKER_AGENTS = [
  {
    key: "data_agent",
    label: "Data Agent",
    description:
      "Refreshes the per-symbol Nifty 50 OHLCV cache and the intraday index OHLCV. Verifies the cache after every fetch.",
  },
  {
    key: "analysis_agent",
    label: "Analysis Agent",
    description:
      "Scores all 50 symbols across rule-based + RF + GBM + LSTM and produces consensus picks (symbols showing up in ≥2 methods).",
  },
  {
    key: "context_agent",
    label: "Market Context Agent",
    description:
      "Reads India VIX, market regime, sector rotation, and headlines from MoneyControl + Economic Times RSS feeds.",
  },
  {
    key: "informant_agent",
    label: "Informant Agent",
    description:
      "Scans the next 5 days for earnings, ex-dividends, F&O monthly expiry, and macro events (RBI MPC, Fed FOMC, monthly auto sales). Tags affected stocks for closer attention.",
  },
  {
    key: "head_agent",
    label: "Head Agent",
    description:
      "Synthesises the briefing from worker outputs (LLM via local Ollama; deterministic markdown fallback).",
  },
] as const;

function statusForAgent(runs: AgentRunRow[], key: string): AgentRunStatus | null {
  for (const run of runs) {
    if (run.cycle_type === "DEEP" || run.cycle_type === "BOOT") {
      const s = run.worker_statuses?.[key];
      if (s) return s;
    }
  }
  return null;
}

function lastRunAtForAgent(runs: AgentRunRow[]): string | null {
  for (const run of runs) {
    if (run.cycle_type === "DEEP" || run.cycle_type === "BOOT") {
      return run.run_at;
    }
  }
  return null;
}

export function Agents() {
  const qc = useQueryClient();

  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ["agentic-status"],
    queryFn: () => agentsApi.status(),
    refetchInterval: 5_000,
  });

  const runDeepMut = useMutation({
    mutationFn: () => agentsApi.runDeep(true),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["agentic-status"] });
      void qc.invalidateQueries({ queryKey: ["agentic-briefing"] });
    },
  });

  const runFastMut = useMutation({
    mutationFn: () => agentsApi.runFast(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["agentic-status"] });
    },
  });

  const runs = status?.last_runs ?? [];
  const isRunning = status?.deep_cycle_running ?? false;
  const lastDeep = useMemo(() => lastRunAtForAgent(runs), [runs]);

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2">
          <Workflow className="size-6 text-accent-violet" />
          <h1 className="text-2xl font-bold tracking-tight">Agents</h1>
          {isRunning && (
            <span className="inline-flex items-center gap-1 text-[11px] text-accent-blue ml-2">
              <Loader2 className="size-3 animate-spin" /> Deep cycle running
            </span>
          )}
        </div>
        <p className="text-fg-muted text-sm mt-1">
          A head agent delegates work to four specialists (data, analysis,
          context, informant). The deep cycle
          (refresh → score → context → events → synthesise) repeats every
          15 min during NSE hours; a deterministic 60-sec monitor refreshes
          movers and wakes the deep cycle on invalidation breaches or new
          top movers.
        </p>
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          className="btn btn-primary text-sm"
          onClick={() => runDeepMut.mutate()}
          disabled={runDeepMut.isPending || isRunning}
        >
          {runDeepMut.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Sparkles className="size-4" />
          )}
          Run deep cycle now
        </button>
        <button
          type="button"
          className="btn text-sm"
          onClick={() => runFastMut.mutate()}
          disabled={runFastMut.isPending}
        >
          {runFastMut.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Play className="size-4" />
          )}
          Trigger fast monitor tick
        </button>
        {status?.last_deep_cycle_at && (
          <span className="text-[11px] text-fg-subtle ml-1">
            Last deep cycle: {new Date(status.last_deep_cycle_at).toLocaleString("en-IN")}
          </span>
        )}
      </div>

      {runFastMut.data && (
        <div className="card p-3 text-[12px] text-fg-muted">
          Fast tick @ {new Date(runFastMut.data.ran_at).toLocaleTimeString("en-IN")} ·{" "}
          {runFastMut.data.movers_count} movers · {runFastMut.data.note}
          {runFastMut.data.triggered_deep_cycle && (
            <span className="ml-1 text-accent-amber">→ deep cycle queued</span>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3">
        {WORKER_AGENTS.map((cfg) => (
          <AgentStatusCard
            key={cfg.key}
            label={cfg.label}
            description={cfg.description}
            status={statusForAgent(runs, cfg.key)}
            lastRunAt={lastDeep}
          />
        ))}
      </div>

      <DailyBriefingPanel />

      <div className="card p-4">
        <div className="flex items-center gap-2 mb-3">
          <Activity className="size-4 text-accent-blue" />
          <h2 className="font-semibold text-sm">Recent agent runs</h2>
          <span className="text-[11px] text-fg-subtle">last {runs.length}</span>
        </div>
        {statusLoading && (
          <div className="text-fg-muted text-sm flex items-center gap-2">
            <Loader2 className="size-4 animate-spin" />
            Loading status…
          </div>
        )}
        {!statusLoading && runs.length === 0 && (
          <div className="text-fg-muted text-sm flex items-center gap-2">
            <AlertTriangle className="size-4 text-accent-amber" />
            No agent runs yet — restart the backend or click "Run deep cycle now".
          </div>
        )}
        {!statusLoading && runs.length > 0 && (
          <table className="w-full text-left text-[13px]">
            <thead>
              <tr className="text-fg-subtle border-b border-border">
                <th className="py-1.5 pr-2 font-medium">Run at</th>
                <th className="py-1.5 pr-2 font-medium">Cycle</th>
                <th className="py-1.5 pr-2 font-medium">Status</th>
                <th className="py-1.5 pr-2 font-medium">Workers</th>
                <th className="py-1.5 pr-2 font-medium num">Duration</th>
                <th className="py-1.5 font-medium">Trigger</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="border-b border-border/60 last:border-0">
                  <td className="py-1.5 pr-2 num">
                    {new Date(r.run_at).toLocaleTimeString("en-IN", {
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}
                  </td>
                  <td className="py-1.5 pr-2 text-[11px] uppercase tracking-wide">
                    {r.cycle_type}
                  </td>
                  <td className="py-1.5 pr-2 text-[11px]">{r.status}</td>
                  <td className="py-1.5 pr-2 text-[11px] text-fg-muted">
                    {Object.entries(r.worker_statuses ?? {})
                      .map(([k, v]) => `${AGENT_LABEL[k] ?? k}: ${v}`)
                      .join(" · ") || "—"}
                  </td>
                  <td className="py-1.5 pr-2 num">
                    {r.duration_s != null ? `${r.duration_s.toFixed(1)}s` : "—"}
                  </td>
                  <td className="py-1.5 text-[11px] text-fg-muted">{r.triggered_by ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
