import { Activity, AlertTriangle, CalendarClock, ExternalLink, Newspaper, RefreshCcw, Sparkles, TrendingUp } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { agentsApi } from "@/api/client";
import type { DailyBriefing, EventImpact, UpcomingEvent, VixBand } from "@/api/types";
import { EVENT_CATEGORY_LABEL, EVENT_IMPACT_TONE } from "@/api/types";
import { fmt, symbolDisplay } from "@/lib/format";

const VIX_BAND_TONE: Record<VixBand, string> = {
  NORMAL: "bg-accent-green/15 text-accent-green border-accent-green/30",
  ELEVATED: "bg-accent-amber/15 text-accent-amber border-accent-amber/30",
  PANIC: "bg-accent-red/15 text-accent-red border-accent-red/30",
  UNKNOWN: "bg-bg-elevated text-fg-muted border-border",
};

const REGIME_TONE: Record<string, string> = {
  RISK_ON: "bg-accent-green/15 text-accent-green",
  NEUTRAL: "bg-bg-elevated text-fg",
  RISK_OFF: "bg-accent-red/15 text-accent-red",
  UNKNOWN: "bg-bg-elevated text-fg-muted",
};

const IMPACT_BADGE_CLASS: Record<EventImpact, string> = {
  HIGH: "bg-accent-red/15 text-accent-red border-accent-red/30",
  MEDIUM: "bg-accent-amber/15 text-accent-amber border-accent-amber/30",
  LOW: "bg-accent-blue/15 text-accent-blue border-accent-blue/30",
};

export interface DailyBriefingPanelProps {
  /** When true, renders a compact one-line header at the top suitable for the
   * Dashboard. When false (default) renders the full detailed layout. */
  compact?: boolean;
}

export function DailyBriefingPanel({ compact = false }: DailyBriefingPanelProps) {
  const qc = useQueryClient();
  const { data: briefing, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["agentic-briefing"],
    queryFn: () => agentsApi.briefing(),
    refetchInterval: 60_000,
  });

  const runMut = useMutation({
    mutationFn: () => agentsApi.runDeep(true),
    onSuccess: () => {
      // Re-poll status + briefing on a tighter cadence until run completes.
      void qc.invalidateQueries({ queryKey: ["agentic-status"] });
      void qc.invalidateQueries({ queryKey: ["agentic-briefing"] });
    },
  });

  if (isLoading) {
    return (
      <div className="card p-4 text-fg-muted text-sm">Loading agentic briefing…</div>
    );
  }

  if (!briefing) {
    return (
      <div className="card p-4 flex items-center justify-between gap-3">
        <div className="text-sm text-fg-muted flex items-center gap-2">
          <AlertTriangle className="size-4 text-accent-amber" />
          No briefing yet. The first agent cycle runs at app start; you can
          force one now.
        </div>
        <button
          type="button"
          className="btn btn-primary text-sm"
          onClick={() => runMut.mutate()}
          disabled={runMut.isPending}
        >
          <Sparkles className="size-4" />
          Run agents now
        </button>
      </div>
    );
  }

  return compact ? (
    <CompactBriefing briefing={briefing} onRefresh={() => refetch()} fetching={isFetching} />
  ) : (
    <FullBriefing
      briefing={briefing}
      onRefresh={() => refetch()}
      onRunDeep={() => runMut.mutate()}
      fetching={isFetching}
      runPending={runMut.isPending}
    />
  );
}

function CompactBriefing({ briefing, onRefresh, fetching }: {
  briefing: DailyBriefing;
  onRefresh: () => void;
  fetching: boolean;
}) {
  const vixBand = (briefing.vix_band ?? "UNKNOWN") as VixBand;
  return (
    <div className="card p-3 flex flex-wrap items-center gap-3 text-sm">
      <div className="flex items-center gap-2">
        <Activity className="size-4 text-accent-violet" />
        <span className="font-semibold">Agentic briefing</span>
        <span className="text-[11px] text-fg-subtle num">
          {new Date(briefing.run_at).toLocaleTimeString("en-IN", {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>
      <span className={`px-2 py-0.5 rounded-full text-[11px] ${REGIME_TONE[briefing.regime] ?? REGIME_TONE.UNKNOWN}`}>
        Regime: {briefing.regime}
      </span>
      <span className={`px-2 py-0.5 rounded-full text-[11px] border ${VIX_BAND_TONE[vixBand]}`}>
        VIX: {briefing.vix_value != null ? fmt.num(briefing.vix_value, 2) : "n/a"} ({vixBand})
      </span>
      <span className="text-[11px] text-fg-muted">
        Trend: <span className="text-fg">{briefing.market_trend ?? "—"}</span>
      </span>
      <span className="text-[11px] text-fg-muted">
        Top picks: <span className="text-fg num">{briefing.top_picks.length}</span>
      </span>
      {briefing.upcoming_events && briefing.upcoming_events.length > 0 && (
        <span className="text-[11px] text-fg-muted flex items-center gap-1">
          <CalendarClock className="size-3.5 text-accent-violet" />
          Events 5d: <span className="text-fg num">{briefing.upcoming_events.length}</span>
        </span>
      )}
      <button
        type="button"
        className="btn ml-auto text-xs"
        onClick={onRefresh}
        disabled={fetching}
      >
        <RefreshCcw className="size-3.5" />
        Refresh
      </button>
    </div>
  );
}

function FullBriefing({
  briefing,
  onRefresh,
  onRunDeep,
  fetching,
  runPending,
}: {
  briefing: DailyBriefing;
  onRefresh: () => void;
  onRunDeep: () => void;
  fetching: boolean;
  runPending: boolean;
}) {
  const vixBand = (briefing.vix_band ?? "UNKNOWN") as VixBand;

  return (
    <div className="space-y-4">
      <div className="card p-4">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles className="size-5 text-accent-violet" />
              <h2 className="font-semibold text-lg">Agentic briefing</h2>
              <span className="text-[11px] text-fg-subtle num">
                Generated {new Date(briefing.run_at).toLocaleString("en-IN")}
              </span>
            </div>
            <p className="text-[12px] text-fg-muted mt-1">
              Synthesised by the head agent from Data → Analysis → Context worker outputs.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn text-sm"
              onClick={onRefresh}
              disabled={fetching}
            >
              <RefreshCcw className="size-4" />
              Refresh
            </button>
            <button
              type="button"
              className="btn btn-primary text-sm"
              onClick={onRunDeep}
              disabled={runPending}
            >
              <Sparkles className="size-4" />
              {runPending ? "Triggered…" : "Run agents now"}
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 mb-4">
          <span className={`px-2.5 py-1 rounded-full text-xs ${REGIME_TONE[briefing.regime] ?? REGIME_TONE.UNKNOWN}`}>
            Regime: {briefing.regime}
          </span>
          <span className={`px-2.5 py-1 rounded-full text-xs border ${VIX_BAND_TONE[vixBand]}`}>
            India VIX: {briefing.vix_value != null ? fmt.num(briefing.vix_value, 2) : "n/a"} ({vixBand})
          </span>
          <span className="px-2.5 py-1 rounded-full text-xs bg-bg-elevated text-fg">
            Trend: {briefing.market_trend ?? "—"}
          </span>
        </div>

        {briefing.market_summary_md && (
          <div className="prose prose-invert max-w-none text-sm whitespace-pre-wrap leading-relaxed">
            {briefing.market_summary_md}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card p-4">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp className="size-4 text-accent-green" />
            <h3 className="font-semibold text-sm">Top consensus picks</h3>
            <span className="text-[11px] text-fg-subtle">
              {briefing.top_picks.length} picks · {briefing.consensus_picks.length} candidates
            </span>
          </div>
          {briefing.top_picks.length === 0 ? (
            <p className="text-sm text-fg-muted">No symbols crossed the consensus threshold this cycle.</p>
          ) : (
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="text-fg-subtle border-b border-border">
                  <th className="py-1.5 pr-2 font-medium">Symbol</th>
                  <th className="py-1.5 pr-2 font-medium">Votes</th>
                  <th className="py-1.5 pr-2 font-medium num">Score</th>
                  <th className="py-1.5 pr-2 font-medium num">Mean conf</th>
                  <th className="py-1.5 pr-2 font-medium num">Close</th>
                  <th className="py-1.5 font-medium">Regime</th>
                </tr>
              </thead>
              <tbody>
                {briefing.top_picks.map((p) => (
                  <tr key={p.symbol} className="border-b border-border/60 last:border-0">
                    <td className="py-1.5 pr-2 font-medium">
                      <div className="flex items-center gap-1.5">
                        {symbolDisplay(p.symbol)}
                        {p.upcoming_event && p.upcoming_event.category && (
                          <span
                            title={`${p.upcoming_event.title ?? ""} (${p.upcoming_event.date ?? ""})`}
                            className={`px-1.5 py-0.5 rounded text-[10px] border ${
                              IMPACT_BADGE_CLASS[(p.upcoming_event.impact ?? "LOW") as EventImpact]
                            }`}
                          >
                            {EVENT_CATEGORY_LABEL[p.upcoming_event.category]}
                            {p.upcoming_event.days_until != null
                              ? ` ${p.upcoming_event.days_until === 0 ? "today" : `${p.upcoming_event.days_until}d`}`
                              : ""}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="py-1.5 pr-2 text-[11px] text-fg-muted">
                      {p.vote_count}/4 · {p.votes.join(", ")}
                    </td>
                    <td className="py-1.5 pr-2 num">{fmt.num(p.score, 1)}</td>
                    <td className="py-1.5 pr-2 num">{fmt.num(p.mean_confidence, 2)}</td>
                    <td className="py-1.5 pr-2 num">{p.close != null ? fmt.inr(p.close) : "—"}</td>
                    <td className="py-1.5 text-[11px] text-fg-muted">{p.regime ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card p-4">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp className="size-4 text-accent-blue" />
            <h3 className="font-semibold text-sm">Sector rotation</h3>
            <span className="text-[11px] text-fg-subtle">{briefing.sector_rotation.length} sectors</span>
          </div>
          {briefing.sector_rotation.length === 0 ? (
            <p className="text-sm text-fg-muted">No sector data yet. Run an EOD refresh to populate.</p>
          ) : (
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="text-fg-subtle border-b border-border">
                  <th className="py-1.5 pr-2 font-medium">Sector</th>
                  <th className="py-1.5 pr-2 font-medium num">Count</th>
                  <th className="py-1.5 pr-2 font-medium num">Total</th>
                  <th className="py-1.5 font-medium num">Mean</th>
                </tr>
              </thead>
              <tbody>
                {briefing.sector_rotation.map((s) => (
                  <tr key={s.sector} className="border-b border-border/60 last:border-0">
                    <td className="py-1.5 pr-2">{s.sector}</td>
                    <td className="py-1.5 pr-2 num">{s.count}</td>
                    <td className="py-1.5 pr-2 num">{fmt.num(s.total_score, 1)}</td>
                    <td className="py-1.5 num">{fmt.num(s.mean_score, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <UpcomingEventsCard events={briefing.upcoming_events ?? []} />

      <div className="card p-4">
        <div className="flex items-center gap-2 mb-3">
          <Newspaper className="size-4 text-accent-cyan" />
          <h3 className="font-semibold text-sm">Recent market news</h3>
          <span className="text-[11px] text-fg-subtle">{briefing.news_headlines.length} headlines</span>
        </div>
        {briefing.news_headlines.length === 0 ? (
          <p className="text-sm text-fg-muted">No headlines fetched. Check that RSS feeds are reachable.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {briefing.news_headlines.map((h) => (
              <li key={h.link} className="flex items-start gap-2">
                <span className="text-[11px] text-fg-subtle uppercase tracking-wide shrink-0">
                  {h.source}
                </span>
                <a
                  href={h.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-fg hover:text-accent-blue inline-flex items-start gap-1"
                >
                  {h.title}
                  <ExternalLink className="size-3 mt-1 shrink-0" />
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>

      <p className="text-[11px] text-fg-subtle">{briefing.disclaimer}</p>
    </div>
  );
}

function UpcomingEventsCard({ events }: { events: UpcomingEvent[] }) {
  return (
    <div className="card p-4">
      <div className="flex items-center gap-2 mb-3">
        <CalendarClock className="size-4 text-accent-violet" />
        <h3 className="font-semibold text-sm">Upcoming events (next 5 days)</h3>
        <span className="text-[11px] text-fg-subtle">
          {events.length} {events.length === 1 ? "event" : "events"} · expect higher volatility
        </span>
      </div>
      {events.length === 0 ? (
        <p className="text-sm text-fg-muted">
          No earnings, ex-dividends, F&amp;O expiries or macro prints in the next 5 days.
        </p>
      ) : (
        <ul className="space-y-2 text-[13px]">
          {events.map((ev) => {
            const tone = EVENT_IMPACT_TONE[ev.impact] ?? "blue";
            const badgeClass = IMPACT_BADGE_CLASS[ev.impact] ?? IMPACT_BADGE_CLASS.LOW;
            const visibleSyms = ev.symbols.slice(0, 4);
            const extra = ev.symbols.length - visibleSyms.length;
            return (
              <li
                key={`${ev.date}-${ev.category}-${ev.title}`}
                className="flex flex-wrap items-start gap-2 border-b border-border/40 pb-2 last:border-0 last:pb-0"
              >
                <span className={`px-1.5 py-0.5 rounded text-[10px] border shrink-0 ${badgeClass}`}>
                  {ev.impact}
                </span>
                <span className="text-[11px] text-fg-subtle shrink-0 num">
                  {ev.date} ({ev.days_until === 0 ? "today" : `${ev.days_until}d`})
                </span>
                <span className="text-fg">
                  <span className="font-medium">{EVENT_CATEGORY_LABEL[ev.category]}</span>
                  {" — "}
                  {ev.title}
                </span>
                <span className={`text-[11px] ml-auto text-accent-${tone}`}>
                  {visibleSyms.map((s) => (s === "MARKET" ? "Market-wide" : symbolDisplay(s))).join(", ")}
                  {extra > 0 ? ` +${extra}` : ""}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
