import { ShieldCheck, RefreshCw } from "lucide-react";
import { Badge } from "./Badge";
import { formatRelative } from "@/lib/format";
import type { LiveVerificationSummary } from "@/api/types";

/**
 * Compact banner showing the latest live verification counts.
 * Renders nothing when the summary is empty / not loaded yet so callers
 * can drop it in unconditionally.
 *
 * Optional `onRerun` wires the "Re-verify now" button — pass the
 * `liveVerificationApi.run` mutation. Hidden when omitted.
 */
export function LiveVerificationBanner({
  summary,
  onRerun,
  rerunDisabled,
}: {
  readonly summary: LiveVerificationSummary | null | undefined;
  readonly onRerun?: () => void;
  readonly rerunDisabled?: boolean;
}) {
  if (!summary || summary.total === 0) {
    return null;
  }
  return (
    <section
      className="card p-3 flex items-center gap-3 flex-wrap"
      aria-label="Live signal verification summary"
    >
      <div className="flex items-center gap-2 text-sm">
        <ShieldCheck className="size-4 text-accent-blue" />
        <span className="font-medium">Live verification</span>
        <span className="text-xs text-fg-muted">
          persisted thesis vs current market
        </span>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <Badge tone="green">{summary.confirmed} confirmed</Badge>
        <Badge tone="amber">{summary.weakening} weakening</Badge>
        <Badge tone="red">{summary.invalidated} invalidated</Badge>
        <Badge tone="blue">{summary.strengthened} strengthened</Badge>
      </div>
      <div className="ml-auto flex items-center gap-3">
        <span className="text-xs text-fg-subtle">
          refreshed {formatRelative(summary.last_run_at)}
          {summary.source ? ` · ${summary.source}` : ""}
        </span>
        {onRerun && (
          <button
            type="button"
            onClick={onRerun}
            disabled={rerunDisabled}
            className="text-xs flex items-center gap-1 text-accent-blue hover:underline disabled:opacity-60 disabled:cursor-not-allowed"
            title="Trigger an immediate live verification pass"
          >
            <RefreshCw
              className={`size-3 ${rerunDisabled ? "animate-spin" : ""}`}
            />
            Re-verify now
          </button>
        )}
      </div>
    </section>
  );
}
