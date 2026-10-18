import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmt } from "@/lib/format";
import { AlertTriangle, Bot, Loader2, RefreshCcw, Sparkles } from "lucide-react";
import type { ExplainSections } from "@/api/types";

function Section({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-fg-muted mb-1">
        {title}
      </div>
      <div className="text-[14px] leading-relaxed text-fg">{children}</div>
    </div>
  );
}

function StructuredBody({
  sections,
  fallback,
}: {
  sections: ExplainSections | undefined;
  fallback: string;
}) {
  if (!sections?.setup) {
    return (
      <div className="whitespace-pre-line text-[14px] leading-relaxed text-fg">
        {fallback}
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {sections.setup && <Section title="Setup">{sections.setup}</Section>}
      {sections.indicators && (
        <Section title="Indicators">{sections.indicators}</Section>
      )}
      {sections.rules.length > 0 && (
        <Section title="Rules that fired">
          <ul className="list-disc ml-4 space-y-1 text-fg-muted">
            {sections.rules.map((rule, i) => (
              <li key={i}>{rule}</li>
            ))}
          </ul>
        </Section>
      )}
      {sections.plan && <Section title="Plan">{sections.plan}</Section>}
      {sections.risks && (
        <Section title="What to watch">{sections.risks}</Section>
      )}
    </div>
  );
}

export function AIExplain({ symbol }: { symbol: string }) {
  const [requested, setRequested] = useState(false);

  useEffect(() => {
    setRequested(false);
  }, [symbol]);

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["explain", symbol],
    queryFn: () => api.explain(symbol),
    enabled: requested && !!symbol,
    staleTime: 5 * 60_000,
  });

  const generate = () => {
    if (requested) {
      void refetch();
      return;
    }
    setRequested(true);
  };

  const busy = isFetching || (requested && isLoading);

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <Bot className="size-5 text-accent-violet" />
          <h3 className="font-semibold">AI Explanation</h3>
          {requested && data && (
            <span className="text-[11px] text-fg-subtle uppercase tracking-wide">
              · {data.provider}
            </span>
          )}
        </div>
        {requested && data && !isError && (
          <button
            className="btn"
            onClick={() => void refetch()}
            disabled={busy}
            title="Regenerate explanation"
          >
            {busy ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <RefreshCcw className="size-4" />
            )}
            <span>Regenerate</span>
          </button>
        )}
      </div>

      {!requested && (
        <div className="py-2">
          <p className="text-sm text-fg-muted mb-3">
            Generate a structured walkthrough of this snapshot — setup,
            indicators, rules, plan, and invalidation. Nothing is sent until
            you ask.
          </p>
          <button className="btn btn-primary" onClick={generate} disabled={!symbol}>
            <Sparkles className="size-4" />
            <span>Generate explanation</span>
          </button>
        </div>
      )}

      {requested && busy && !data && (
        <div className="flex items-center gap-2 text-fg-muted text-sm py-6">
          <Loader2 className="size-4 animate-spin" />
          Generating explanation…
        </div>
      )}

      {requested && isError && (
        <div className="space-y-3">
          <div className="flex items-start gap-2 text-accent-red text-sm py-2">
            <AlertTriangle className="size-4 mt-0.5" />
            Failed to load explanation. Make sure the backend is running and a
            snapshot exists for this symbol (refresh data once).
          </div>
          <button className="btn" onClick={() => void refetch()} disabled={busy}>
            {busy ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <RefreshCcw className="size-4" />
            )}
            <span>Retry</span>
          </button>
        </div>
      )}

      {requested && data && (
        <>
          <StructuredBody sections={data.sections} fallback={data.explanation} />

          <div className="mt-4 grid grid-cols-2 gap-3">
            <div className="rounded-md border border-border bg-bg-elevated p-2">
              <div className="text-[11px] uppercase tracking-wide text-fg-muted">
                Invalidation
              </div>
              <div className="num text-accent-red font-semibold">
                {fmt.num(data.invalidation_level)}
              </div>
            </div>
            <div className="rounded-md border border-border bg-bg-elevated p-2">
              <div className="text-[11px] uppercase tracking-wide text-fg-muted">
                Confidence
              </div>
              <div className="num font-semibold">
                {fmt.pctRaw(data.confidence * 100, 0)}
              </div>
            </div>
          </div>

          <div className="mt-4 flex items-start gap-2 rounded-md border border-accent-amber/30 bg-accent-amber/5 p-2 text-[12px] text-accent-amber">
            <AlertTriangle className="size-4 mt-0.5" />
            <span>{data.disclaimer}</span>
          </div>
        </>
      )}
    </div>
  );
}
