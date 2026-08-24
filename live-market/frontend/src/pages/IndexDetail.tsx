import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import CreditSpreadCard from "../components/CreditSpreadCard";
import IntradayChart from "../components/IntradayChart";
import OptionBiasCard from "../components/OptionBiasCard";
import RegimeBanner from "../components/RegimeBanner";
import ScalpCard from "../components/ScalpCard";
import StrikeRecommendationsCard from "../components/StrikeRecommendationsCard";
import SwingCard from "../components/SwingCard";
import { fmt, relativeAge, symbolDisplay } from "../lib/format";

const REFRESH_MS = 30_000;

export default function IndexDetail() {
  const { symbol = "" } = useParams();
  const [showHistory, setShowHistory] = useState(false);
  const [direction, setDirection] = useState<"LONG" | "SHORT" | "AUTO">("AUTO");
  const [holdDays, setHoldDays] = useState<number | "auto">("auto");

  const detailQ = useQuery({
    queryKey: ["index-detail", symbol],
    queryFn: () => api.indexDetail(symbol),
    refetchInterval: REFRESH_MS,
    enabled: !!symbol,
  });

  const hasChain = symbol !== "^BSESN";
  const biasQ = useQuery({
    queryKey: ["option-bias", symbol],
    queryFn: () => api.optionBias(symbol),
    refetchInterval: REFRESH_MS,
    enabled: !!symbol && hasChain,
  });
  const recsQ = useQuery({
    queryKey: ["strike-recs", symbol, direction, holdDays],
    queryFn: () => api.strikeRecommendations(
      symbol,
      direction === "AUTO" ? undefined : direction,
      holdDays === "auto" ? undefined : holdDays,
    ),
    refetchInterval: REFRESH_MS,
    enabled: !!symbol && hasChain,
  });

  if (!symbol) {
    return <p className="text-sm text-accent-red">No symbol.</p>;
  }
  if (detailQ.isLoading) {
    return <p className="text-sm text-fg-muted">Loading {symbolDisplay(symbol)}...</p>;
  }
  if (detailQ.error || !detailQ.data) {
    return (
      <div className="card p-4 text-sm text-accent-red">
        Failed to load detail for {symbol}. Is the backend running?
      </div>
    );
  }

  const d = detailQ.data;
  const c = d.card;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link to="/" className="text-xs text-accent-blue hover:underline">
            &larr; back to dashboard
          </Link>
          <h1 className="mt-1 text-2xl font-semibold text-fg">
            {symbolDisplay(c.symbol)}
            <span className="ml-2 text-sm font-normal text-fg-muted">{c.code}</span>
          </h1>
        </div>
        <RegimeBanner regime={c.regime} reasons={c.regime_reasons} size="lg" />
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Spot" value={fmt.num(c.spot)} accent="strong" />
        <Stat label="VWAP" value={fmt.num(c.vwap)} />
        <Stat label="Support" value={fmt.num(c.range_support)} accent="green" />
        <Stat label="Resistance" value={fmt.num(c.range_resistance)} accent="red" />
        <Stat label="Daily ADX" value={fmt.num(c.daily_adx, 1)} />
      </div>

      <div className="card p-4">
        <div className="mb-2 flex items-center justify-between text-xs text-fg-subtle">
          <span>1-minute OHLCV - last {d.bars.length} bars</span>
          <span>updated {relativeAge(c.last_bar_age_seconds)}</span>
        </div>
        <IntradayChart
          bars={d.bars}
          vwap={c.vwap}
          support={c.range_support}
          resistance={c.range_resistance}
        />
      </div>

      {hasChain && biasQ.data && (
        <OptionBiasCard bias={biasQ.data} />
      )}

      {hasChain && recsQ.data && (
        <StrikeRecommendationsCard
          data={recsQ.data}
          direction={direction}
          onDirectionChange={setDirection}
          holdDays={holdDays}
          onHoldDaysChange={setHoldDays}
        />
      )}

      {hasChain && recsQ.data?.credit_spread && (
        <CreditSpreadCard spread={recsQ.data.credit_spread} />
      )}

      <Section
        title={`Active scalp setups (${d.active_scalps.length})`}
        empty="No active scalp setups - either regime is not RANGE_BOUND or no entry triggered yet."
      >
        {d.active_scalps.map((s) => <ScalpCard key={s.id} setup={s} />)}
      </Section>

      <Section
        title={`Active swing setups (${d.active_swings.length})`}
        empty="No active swing setups - either regime is not TRENDING or no entry triggered yet."
      >
        {d.active_swings.map((s) => <SwingCard key={s.id} setup={s} />)}
      </Section>

      <div className="card p-4">
        <button
          className="text-sm font-medium text-accent-blue hover:underline"
          onClick={() => setShowHistory((v) => !v)}
        >
          {showHistory ? "Hide" : "Show"} resolved history
          ({d.recent_history_scalps.length + d.recent_history_swings.length})
        </button>
        {showHistory && (
          <div className="mt-4 grid grid-cols-1 gap-4">
            {d.recent_history_scalps.map((s) => <ScalpCard key={`hs-${s.id}`} setup={s} />)}
            {d.recent_history_swings.map((s) => <SwingCard key={`hw-${s.id}`} setup={s} />)}
            {d.recent_history_scalps.length + d.recent_history_swings.length === 0 && (
              <p className="text-xs text-fg-subtle">No resolved setups yet.</p>
            )}
          </div>
        )}
      </div>

      <p className="text-xs italic text-fg-subtle">{d.disclaimer}</p>
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: "green" | "red" | "strong";
}) {
  const cls =
    accent === "green"
      ? "text-accent-green"
      : accent === "red"
      ? "text-accent-red"
      : accent === "strong"
      ? "text-fg"
      : "text-fg-muted";
  return (
    <div className="card flex flex-col px-3 py-2">
      <span className="text-[10px] uppercase tracking-wide text-fg-subtle">{label}</span>
      <span className={`num text-lg font-semibold ${cls}`}>{value}</span>
    </div>
  );
}

function Section({
  title,
  empty,
  children,
}: {
  title: string;
  empty: string;
  children: React.ReactNode;
}) {
  const arr = Array.isArray(children) ? children : [children];
  const filtered = arr.filter(Boolean);
  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-fg-muted">
        {title}
      </h2>
      <div className="grid grid-cols-1 gap-4">
        {filtered.length > 0 ? filtered : (
          <p className="text-xs text-fg-subtle">{empty}</p>
        )}
      </div>
    </section>
  );
}
