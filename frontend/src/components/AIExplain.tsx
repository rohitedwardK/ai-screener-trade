import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { AlertTriangle, Bot, Loader2, RefreshCcw } from "lucide-react";

export function AIExplain({ symbol }: { symbol: string }) {
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["explain", symbol],
    queryFn: () => api.explain(symbol),
    enabled: !!symbol,
    staleTime: 5 * 60_000,
  });

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <Bot className="size-5 text-accent-violet" />
          <h3 className="font-semibold">AI Explanation</h3>
          {data && (
            <span className="text-[11px] text-fg-subtle uppercase tracking-wide">
              · {data.provider}
            </span>
          )}
        </div>
        <button
          className="btn"
          onClick={() => refetch()}
          disabled={isFetching}
          title="Regenerate explanation"
        >
          {isFetching ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <RefreshCcw className="size-4" />
          )}
          <span>Regenerate</span>
        </button>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-fg-muted text-sm py-6">
          <Loader2 className="size-4 animate-spin" />
          Generating explanation…
        </div>
      )}

      {isError && (
        <div className="flex items-start gap-2 text-accent-red text-sm py-2">
          <AlertTriangle className="size-4 mt-0.5" />
          Failed to load explanation. Make sure the backend is running and a
          snapshot exists for this symbol (refresh data once).
        </div>
      )}

      {data && (
        <>
          <div className="prose prose-invert max-w-none whitespace-pre-line text-[14px] leading-relaxed text-fg">
            {data.explanation}
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3">
            <div className="rounded-md border border-border bg-bg-elevated p-2">
              <div className="text-[11px] uppercase tracking-wide text-fg-muted">
                Invalidation
              </div>
              <div className="num text-accent-red font-semibold">
                {data.invalidation_level ?? "—"}
              </div>
            </div>
            <div className="rounded-md border border-border bg-bg-elevated p-2">
              <div className="text-[11px] uppercase tracking-wide text-fg-muted">
                Confidence
              </div>
              <div className="num font-semibold">
                {(data.confidence * 100).toFixed(0)}%
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
