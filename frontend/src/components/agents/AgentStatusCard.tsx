import { Activity, AlertCircle, CheckCircle2, CircleDashed, Loader2 } from "lucide-react";
import type { AgentRunStatus } from "@/api/types";

interface Props {
  label: string;
  description: string;
  status: AgentRunStatus | null;
  lastRunAt?: string | null;
}

const STATUS_PRESENTATION: Record<
  AgentRunStatus,
  { label: string; tone: string; icon: React.ReactNode }
> = {
  OK: {
    label: "Ready",
    tone: "text-accent-green border-accent-green/30 bg-accent-green/10",
    icon: <CheckCircle2 className="size-3.5" />,
  },
  RUNNING: {
    label: "Running",
    tone: "text-accent-blue border-accent-blue/30 bg-accent-blue/10",
    icon: <Loader2 className="size-3.5 animate-spin" />,
  },
  PARTIAL: {
    label: "Degraded",
    tone: "text-accent-amber border-accent-amber/30 bg-accent-amber/10",
    icon: <AlertCircle className="size-3.5" />,
  },
  ERROR: {
    label: "Error",
    tone: "text-accent-red border-accent-red/30 bg-accent-red/10",
    icon: <AlertCircle className="size-3.5" />,
  },
  SKIPPED: {
    label: "Skipped",
    tone: "text-fg-muted border-border bg-bg-elevated",
    icon: <CircleDashed className="size-3.5" />,
  },
};

const IDLE_PRESENTATION = {
  label: "Idle",
  tone: "text-fg-muted border-border bg-bg-elevated",
  icon: <CircleDashed className="size-3.5" />,
};

function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "n/a";
  const d = new Date(iso);
  const diff = Math.max(0, Date.now() - d.getTime());
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function AgentStatusCard({ label, description, status, lastRunAt }: Props) {
  const p = status ? STATUS_PRESENTATION[status] : IDLE_PRESENTATION;
  return (
    <div className="card p-4 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Activity className="size-4 text-accent-violet shrink-0" />
          <h3 className="font-semibold text-sm truncate">{label}</h3>
        </div>
        <span
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium uppercase tracking-wide border ${p.tone}`}
        >
          {p.icon}
          {p.label}
        </span>
      </div>
      <p className="text-[12px] text-fg-muted leading-relaxed">{description}</p>
      <div className="text-[11px] text-fg-subtle">Last seen: {formatRelative(lastRunAt)}</div>
    </div>
  );
}
