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
import { formatDateTimeIST, formatTimeIST } from "@/lib/format";
import { AgentStatusCard } from "@/components/agents/AgentStatusCard";
import { DailyBriefingPanel } from "@/components/agents/DailyBriefingPanel";
import { ResearchPanel } from "@/components/agents/ResearchPanel";

const WORKER_AGENTS = [
  {
    key: "data_agent",
    label: "Data Worker",
    description:
      "Refreshes the per-symbol Nifty 50 OHLCV cache and the intraday index OHLCV. Verifies the cache after every fetch.",
  },
  {
    key: "analysis_agent",
    label: "Analysis Worker",
    description:
      "Scores cached symbols with Random Forest and the rule-based baseline; highlights symbols appearing in both lists.",
  },
  {
    key: "context_agent",
    label: "Context Inputs Worker",
    description: "Collects VIX, regime, trend, sectors, and headlines for the deterministic briefing.",
  },
  {
    key: "informant_agent",
    label: "Informant Worker",
    description:
      "Scans the next 5 days for earnings, ex-dividends, F&O monthly expiry, and macro events (RBI MPC, Fed FOMC, monthly auto sales). Tags affected stocks for closer attention.",
  },
] as const;

const AI_AGENTS = [
  { type: "MARKET_CONTEXT", label: "Market Context Agent", description: "Investigates conflicting market context using bounded read-only tools." },
  { type: "RESEARCH", label: "Research Agent", description: "Reviews cached research candidates and selects supported ideas." },
  { type: "BRIEFING", label: "Briefing AI", description: "Adds an Ollama-written summary after the deterministic briefing is saved." },
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
          Workers refresh and analyze market data even when Ollama is offline.
          Optional AI tasks wait in a persistent queue and run when the local model is available.
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
            Last deep cycle: {formatDateTimeIST(status.last_deep_cycle_at)} IST
          </span>
        )}
      </div>

      {runFastMut.data && (
        <div className="card p-3 text-[12px] text-fg-muted">
          Fast tick @ {formatTimeIST(runFastMut.data.ran_at, true)} IST ·{" "}
          {runFastMut.data.movers_count} movers · {runFastMut.data.note}
          {runFastMut.data.triggered_deep_cycle && (
            <span className="ml-1 text-accent-amber">→ deep cycle queued</span>
          )}
        </div>
      )}

      <section className="space-y-3">
        <h2 className="font-semibold text-sm">Workers</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
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
      </section>

      <div className="card p-4">
        <div className="flex items-center gap-2 mb-3">
          <Activity className="size-4 text-accent-blue" />
          <h2 className="font-semibold text-sm">Recent worker cycles</h2>
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
                    {formatTimeIST(r.run_at, true)}
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

      <section className="space-y-3">
        <div className="flex flex-wrap items-center gap-4">
          <h2 className="font-semibold text-sm">AI agents and tasks</h2>
          <span className={`text-xs ${status?.ollama_available ? "text-accent-green" : "text-accent-amber"}`}>AI layer: {status?.ollama_available ? "Online" : "Offline"}</span>
          <span className="text-xs text-fg-muted">AI tasks pending: {status?.ai_tasks_pending ?? 0}</span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {AI_AGENTS.map((agent) => {
            const task = status?.ai_tasks?.find((row) => row.task_type === agent.type);
            return <div key={agent.type} className="card p-4 space-y-2">
              <div className="flex justify-between gap-2"><h3 className="font-semibold text-sm">{agent.label}</h3><span className={`text-[11px] ${task?.status === "COMPLETED" ? "text-accent-green" : task?.status === "FAILED" ? "text-accent-red" : task?.status === "PENDING" || task?.status === "RETRY_WAIT" ? "text-accent-amber" : task?.status === "RUNNING" ? "text-accent-blue" : "text-fg-subtle"}`}>{task?.status?.replaceAll("_", " ") ?? "No task yet"}</span></div>
              <p className="text-xs text-fg-muted">{agent.description}</p>
              {agent.type === "MARKET_CONTEXT" && task?.status === "COMPLETED" && <p className="text-[11px] text-accent-green">LLM JSON: valid tool actions</p>}
              {agent.type === "MARKET_CONTEXT" && task?.status === "RETRY_WAIT" && <p className="text-[11px] text-accent-amber">LLM action: retrying after an error</p>}
              {task && <p className="text-[11px] text-fg-subtle">Updated {formatDateTimeIST(task.updated_at)} IST</p>}
            </div>;
          })}
        </div>
        {(status?.ai_tasks?.length ?? 0) > 0 && <div className="card p-4 space-y-2">
          <h3 className="font-semibold text-sm">Recent AI tasks</h3>
          {status?.ai_tasks?.slice(0, 8).map((task) => <div key={task.id} className="text-xs border-t border-border pt-2 space-y-1">
            <div className="flex flex-wrap gap-x-3 gap-y-1"><span className="font-medium">{task.task_type.replaceAll("_", " ")}</span><span>{task.status.replaceAll("_", " ")}</span><span className="text-fg-subtle">{formatDateTimeIST(task.created_at)} IST</span>{task.error && <span className="text-accent-amber">{task.error}</span>}</div>
            {task.result && <details><summary className="cursor-pointer text-accent-blue">View AI result</summary><pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap text-fg-muted">{JSON.stringify(task.result, null, 2)}</pre></details>}
          </div>)}
        </div>}
      </section>
      <ResearchPanel />
      <DailyBriefingPanel />
      <div className="text-[11px] text-fg-muted flex flex-wrap gap-x-5 gap-y-2 pb-2" aria-label="AI task status legend">
        <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-full bg-accent-green" /> Green: AI task completed</span>
        <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-full bg-accent-amber" /> Yellow: pending or retrying</span>
        <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-full bg-fg-subtle" /> Gray: no task or expired evidence</span>
        <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-full bg-accent-red" /> Red: AI task failed</span>
      </div>
    </div>
  );
}
