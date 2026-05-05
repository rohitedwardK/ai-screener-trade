import type { PaperJournal } from "@/api/types";
import { Sparkles } from "lucide-react";

export function AIJournalPanel({ journal }: { journal: PaperJournal | undefined }) {
  if (!journal) {
    return (
      <div className="card p-4 text-fg-muted text-sm">Loading AI journal…</div>
    );
  }
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-semibold text-sm flex items-center gap-2">
          <Sparkles className="size-4 text-accent-violet" />
          AI Trade Journal
        </h3>
        <span className="text-[11px] text-fg-subtle">
          {journal.date} · provider: {journal.provider}
        </span>
      </div>
      <div className="whitespace-pre-line text-sm text-fg leading-relaxed">
        {journal.summary}
      </div>
    </div>
  );
}
