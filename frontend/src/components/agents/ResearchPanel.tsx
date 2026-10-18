import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Search } from "lucide-react";
import { agentsApi } from "@/api/client";
import type { ResearchRequest } from "@/api/types";
import { fmt, formatDateTimeIST } from "@/lib/format";

export function ResearchPanel() {
  const qc = useQueryClient();
  const [asset, setAsset] = useState<ResearchRequest["asset_class"]>("stock");
  const [horizon, setHorizon] = useState<ResearchRequest["horizon"]>("swing");
  const [useLLM, setUseLLM] = useState(true);
  const [runId, setRunId] = useState<number | null>(null);
  const history = useQuery({
    queryKey: ["research-history", asset, horizon],
    queryFn: () => agentsApi.researchHistory(asset, horizon),
    refetchInterval: 15_000,
  });
  const research = useMutation({
    mutationFn: (request: ResearchRequest) => agentsApi.research(request),
    onSuccess: () => {
      setRunId(null);
      void qc.invalidateQueries({ queryKey: ["research-history"] });
    },
  });
  const result = history.data?.find((r) => r.id === runId) ?? history.data?.[0];
  const unsupported = asset === "stock" && horizon === "intraday";

  return <section className="card p-4 space-y-4">
    <div>
      <h2 className="font-semibold flex items-center gap-2"><Search className="size-4 text-accent-violet" />Research opportunities</h2>
      <p className="text-sm text-fg-muted mt-1">Investigate cached market evidence and compare up to three ideas. Every idea needs valid levels and supporting evidence.</p>
    </div>
    <div className="flex flex-wrap items-end gap-3">
      <label className="text-sm">Market
        <select className="input block mt-1" value={asset} disabled={research.isPending} onChange={(e) => { setAsset(e.target.value as typeof asset); setRunId(null); }}>
          <option value="stock">Stocks</option><option value="index">Indices</option>
        </select>
      </label>
      <label className="text-sm">Horizon
        <select className="input block mt-1" value={horizon} disabled={research.isPending} onChange={(e) => { setHorizon(e.target.value as typeof horizon); setRunId(null); }}>
          <option value="swing">Swing (daily evidence)</option><option value="intraday">Intraday (15-minute evidence)</option>
        </select>
      </label>
      <label className="flex items-center gap-2 text-sm py-2"><input type="checkbox" checked={useLLM} disabled={research.isPending} onChange={(e) => setUseLLM(e.target.checked)} />Agent investigation</label>
      <button type="button" className="btn btn-primary" disabled={research.isPending || unsupported} onClick={() => research.mutate({ asset_class: asset, horizon, use_llm: useLLM })}>
        {research.isPending && <Loader2 className="size-4 animate-spin" />}{research.isPending ? "Researching…" : "Research opportunities"}
      </button>
    </div>
    <p className="text-xs text-fg-muted">Commodity research will be enabled after contract identity and proxy-data validation. Index ideas show spot levels.</p>
    {unsupported && <p className="text-sm text-accent-amber">Stock intraday research needs a timestamped intraday cache. Choose swing or index research.</p>}
    {(research.isError || history.isError) && <p role="alert" className="text-sm text-accent-red">Research could not be loaded or saved. Check the backend connection and retry.</p>}
    {history.isLoading && <p className="text-sm text-fg-muted">Loading saved research…</p>}
    {history.data && history.data.length > 0 && <label className="block text-sm">Saved research
      <select className="input block mt-1" value={result?.id ?? ""} onChange={(e) => setRunId(Number(e.target.value))}>
        {history.data.map((r) => <option key={r.id} value={r.id ?? ""}>{formatDateTimeIST(r.run_at)} IST · {r.mode}</option>)}
      </select>
    </label>}
    {result ? <div className="space-y-3" aria-live="polite">
      <p className="text-xs text-fg-muted">Saved analysis from {formatDateTimeIST(result.run_at)} IST · {result.mode === "agent" ? "Agent investigation" : result.mode === "fallback" ? "Deterministic fallback" : "Deterministic research"}. Levels are historical references until rechecked.</p>
      {result.ideas.length === 0 && <p className="text-sm">No supported ideas selected for this run.</p>}
      <div className="grid gap-3 lg:grid-cols-3">
        {result.ideas.map((idea) => <article key={idea.id} className="rounded-lg border border-border p-3 space-y-3">
          <div className="flex justify-between gap-2"><strong>{idea.symbol}</strong><span className="badge">{idea.direction} · Watching</span></div>
          <p className="text-xs text-fg-muted">{idea.category.replaceAll("_", " ")} · Rule score {fmt.num(idea.score)}</p>
          <p className="text-sm">{idea.thesis}</p>
          <dl className="grid grid-cols-2 gap-2 text-sm">
            {([['Entry reference', idea.entry], ['Stop', idea.stop_loss], ['Target 1', idea.target_1], ['Target 2', idea.target_2], ['Invalidation', idea.invalidation]] as const).map(([label, value]) => <div key={label}><dt className="text-fg-muted text-xs">{label}</dt><dd className="num">{fmt.num(value)}</dd></div>)}
          </dl>
          <p className="text-xs">{idea.trigger}</p>
          <p className="text-xs text-fg-muted">{idea.data_quality} · {idea.timeframe}<br />Observed {formatDateTimeIST(idea.observed_at)} IST<br />{idea.source}</p>
          <details className="text-xs space-y-2"><summary className="cursor-pointer text-accent-blue">Evidence and limitations</summary>
            <ul className="list-disc pl-4 space-y-1">{idea.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul>
            <ul className="list-disc pl-4 space-y-1 text-accent-amber">{idea.counter_evidence.map((e, i) => <li key={i}>{e}</li>)}</ul>
            <dl className="grid grid-cols-2 gap-1">{Object.entries(idea.indicators).map(([k, v]) => <div key={k}><dt className="text-fg-muted">{k}</dt><dd className="num">{fmt.num(v)}</dd></div>)}</dl>
          </details>
        </article>)}
      </div>
      {result.warnings.length > 0 && <details className="text-sm text-accent-amber"><summary className="cursor-pointer">Data gaps and research notes ({fmt.num(result.warnings.length)})</summary><ul className="list-disc pl-5 mt-2">{result.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></details>}
      <details className="text-xs"><summary className="cursor-pointer text-fg-muted">Research tool history and dated context</summary><pre className="mt-2 overflow-auto max-h-80 whitespace-pre-wrap">{JSON.stringify({ context: result.context, steps: result.trace }, null, 2)}</pre></details>
    </div> : !history.isLoading && <p className="text-sm text-fg-muted">Choose a market and horizon to start your first research run.</p>}
    <p className="text-xs text-fg-subtle">Research and decision-support only. Not financial advice.</p>
  </section>;
}
