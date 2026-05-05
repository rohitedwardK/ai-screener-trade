import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams, Link } from "react-router-dom";
import { Loader2, RefreshCw, ScanLine, AlertTriangle } from "lucide-react";

import { indicesApi } from "@/api/client";
import { Badge } from "@/components/Badge";
import { IndexCard } from "@/components/indices/IndexCard";
import { OptionChainTable } from "@/components/indices/OptionChainTable";
import { fmt, regimeTone, scoreTone } from "@/lib/format";
import {
  INDEX_CATEGORY_LABELS,
  INDEX_CATEGORY_TONE,
  OPTION_BIAS_TONE,
} from "@/api/types";

const PRICE_REFRESH_INTERVAL = 60_000;
const OPTION_CHAIN_REFRESH = 60_000;

export function IndexAnalysis() {
  const { symbol } = useParams<{ symbol?: string }>();
  return symbol ? <IndexDetailView symbol={symbol} /> : <IndexListView />;
}

function IndexListView() {
  const dashboard = useQuery({
    queryKey: ["index-dashboard"],
    queryFn: indicesApi.dashboard,
  });

  const symbols = useMemo(
    () => (dashboard.data ?? []).map((r) => r.symbol),
    [dashboard.data],
  );

  const {
    data: priceMap,
    dataUpdatedAt,
    isFetching: isPriceFetching,
  } = useQuery({
    queryKey: ["index-prices", symbols],
    queryFn: () => indicesApi.prices(symbols),
    enabled: symbols.length > 0,
    refetchInterval: PRICE_REFRESH_INTERVAL,
    refetchIntervalInBackground: true,
  });

  const [countdown, setCountdown] = useState(PRICE_REFRESH_INTERVAL / 1000);
  useEffect(() => setCountdown(PRICE_REFRESH_INTERVAL / 1000), [dataUpdatedAt]);
  useEffect(() => {
    if (!symbols.length) return;
    const id = setInterval(() => {
      setCountdown((s) => (s <= 1 ? PRICE_REFRESH_INTERVAL / 1000 : s - 1));
    }, 1000);
    return () => clearInterval(id);
  }, [symbols.length]);

  if (dashboard.isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh] text-fg-muted gap-2">
        <Loader2 className="size-5 animate-spin" />
        Loading indices…
      </div>
    );
  }

  if (dashboard.isError || !dashboard.data) {
    return (
      <div className="card p-6 text-fg-muted flex items-start gap-2">
        <AlertTriangle className="size-4 text-accent-amber mt-1" />
        Backend unreachable. Start the API and trigger an index refresh from
        Admin → /admin/refresh-indices.
      </div>
    );
  }

  const rows = dashboard.data;
  const isEmpty = rows.length === 0;

  return (
    <div className="space-y-6">
      <section className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <ScanLine className="size-6 text-accent-cyan" />
            Index Analysis
          </h1>
          <p className="text-fg-muted text-sm mt-1">
            Nifty 50, Bank Nifty and Sensex with technical setup signals plus
            live option-chain bias for Nifty / Bank Nifty.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Badge tone="cyan">{rows.length} indices</Badge>
          {symbols.length > 0 && (
            <span className="flex items-center gap-1.5 text-xs text-fg-muted">
              <RefreshCw
                className={`size-3 ${isPriceFetching ? "animate-spin" : ""}`}
              />
              Price refresh in {countdown}s
            </span>
          )}
          <Link to="/paper-index-trading" className="btn btn-primary">
            Paper Index Bot
          </Link>
        </div>
      </section>

      {isEmpty && (
        <div className="card p-6 text-fg-muted">
          No index data yet. Trigger an index refresh from{" "}
          <code className="text-xs">/admin/refresh-indices</code>.
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {rows.map((row) => (
          <IndexCard
            key={row.symbol}
            row={row}
            livePrice={priceMap?.[row.symbol]}
          />
        ))}
      </div>
    </div>
  );
}

function IndexDetailView({ symbol }: { symbol: string }) {
  const navigate = useNavigate();
  const detail = useQuery({
    queryKey: ["index-detail", symbol],
    queryFn: () => indicesApi.detail(symbol),
  });

  const {
    data: priceMap,
    dataUpdatedAt: priceUpdatedAt,
    isFetching: isPriceFetching,
  } = useQuery({
    queryKey: ["index-detail-price", symbol],
    queryFn: () => indicesApi.prices([symbol]),
    refetchInterval: PRICE_REFRESH_INTERVAL,
    refetchIntervalInBackground: true,
  });

  const livePrice = priceMap?.[symbol];

  const supportsChain = detail.data?.instrument.has_options ?? false;
  const optionChain = useQuery({
    queryKey: ["index-option-chain", symbol],
    queryFn: () => indicesApi.optionChain(symbol),
    enabled: supportsChain,
    refetchInterval: OPTION_CHAIN_REFRESH,
    refetchIntervalInBackground: false,
  });

  const [priceCountdown, setPriceCountdown] = useState(
    PRICE_REFRESH_INTERVAL / 1000,
  );
  useEffect(() => {
    setPriceCountdown(PRICE_REFRESH_INTERVAL / 1000);
  }, [priceUpdatedAt]);
  useEffect(() => {
    const id = setInterval(() => {
      setPriceCountdown((s) =>
        s <= 1 ? PRICE_REFRESH_INTERVAL / 1000 : s - 1,
      );
    }, 1000);
    return () => clearInterval(id);
  }, []);

  if (detail.isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh] text-fg-muted gap-2">
        <Loader2 className="size-5 animate-spin" />
        Loading {symbol}…
      </div>
    );
  }

  if (detail.isError || !detail.data) {
    return (
      <div className="card p-6 text-fg-muted">
        Could not load index detail for {symbol}.
        <button className="btn ml-3" onClick={() => navigate("/indices")}>
          Back to indices
        </button>
      </div>
    );
  }

  const { instrument, snapshot, signals } = detail.data;
  const indicators = snapshot?.indicators_json ?? {};
  const chainSummary =
    (snapshot?.option_chain_summary_json as Record<string, unknown>) ?? {};

  return (
    <div className="space-y-6">
      <section className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <Link to="/indices" className="text-xs text-accent-blue hover:underline">
            ← All indices
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight mt-1">
            {instrument.name}
          </h1>
          <p className="text-fg-muted text-sm">
            {instrument.code} · {instrument.exchange} · Lot {instrument.lot_size}
            {" · "}Strike step {fmt.num(instrument.strike_step, 0)}
          </p>
        </div>
        <div className="text-right">
          <div className="text-3xl font-semibold tracking-tight num">
            {fmt.num(livePrice ?? snapshot?.close ?? null, 2)}
          </div>
          <div className="text-xs text-fg-muted flex items-center gap-1.5 justify-end">
            <RefreshCw
              className={`size-3 ${isPriceFetching ? "animate-spin" : ""}`}
            />
            Live refresh in {priceCountdown}s
          </div>
        </div>
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="card p-4 lg:col-span-2">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div>
              <h2 className="font-semibold tracking-tight">Latest Snapshot</h2>
              <p className="text-xs text-fg-muted">
                As-of {snapshot?.as_of_date ?? "—"}
              </p>
            </div>
            {snapshot && (
              <Badge tone={regimeTone(snapshot.regime)}>
                {snapshot.regime.replace(/_/g, " ")}
              </Badge>
            )}
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-3 text-xs">
            <KV label="RSI" value={fmt.num(indicators.rsi14 ?? null, 1)} />
            <KV label="ADX" value={fmt.num(indicators.adx ?? null, 1)} />
            <KV
              label="ATR%"
              value={fmt.pctRaw(indicators.atr_pct ?? null, 2)}
            />
            <KV
              label="MACD hist"
              value={fmt.num(indicators.macd_hist ?? null, 2)}
            />
            <KV
              label="20d return"
              value={fmt.pct(indicators.return_20d ?? null, 2)}
            />
            <KV
              label="From 52w high"
              value={fmt.pct(indicators.pct_from_52w_high ?? null, 2)}
            />
            <KV
              label="EMA20"
              value={fmt.num(indicators.ema20 ?? null, 2)}
            />
            <KV
              label="EMA50"
              value={fmt.num(indicators.ema50 ?? null, 2)}
            />
          </div>
        </div>

        <div className="card p-4 space-y-2">
          <h2 className="font-semibold tracking-tight">Option-Chain Bias</h2>
          {chainSummary && Object.keys(chainSummary).length > 0 ? (
            <div className="space-y-2 text-sm">
              <div className="flex items-center gap-2 flex-wrap">
                <Badge
                  tone={
                    OPTION_BIAS_TONE[String(chainSummary.bias ?? "Neutral")] ??
                    "muted"
                  }
                >
                  {String(chainSummary.bias ?? "Neutral")}
                </Badge>
                <span className="text-xs text-fg-muted">
                  strength {fmt.num(Number(chainSummary.bias_strength ?? 0), 2)}
                </span>
              </div>
              <KV label="PCR" value={fmt.num(Number(chainSummary.pcr ?? 0), 2)} />
              <KV
                label="PCR (vol)"
                value={
                  chainSummary.pcr_volume == null
                    ? "—"
                    : fmt.num(Number(chainSummary.pcr_volume), 2)
                }
              />
              <KV
                label="Max Pain"
                value={fmt.num(Number(chainSummary.max_pain ?? 0), 0)}
              />
              <KV
                label="MP vs Spot"
                value={
                  chainSummary.max_pain_distance_pct == null
                    ? "—"
                    : fmt.pct(Number(chainSummary.max_pain_distance_pct), 2)
                }
              />
              <KV
                label="IV Skew"
                value={fmt.num(Number(chainSummary.iv_skew ?? 0), 2)}
              />
              {Array.isArray(chainSummary.notes) &&
                (chainSummary.notes as string[]).length > 0 && (
                  <ul className="text-[11px] text-fg-muted list-disc ml-4 space-y-0.5">
                    {(chainSummary.notes as string[]).map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                )}
            </div>
          ) : (
            <p className="text-xs text-fg-muted">
              {instrument.has_options
                ? "Run an index refresh to fetch the latest option chain."
                : "Option chain not tracked for this index."}
            </p>
          )}
        </div>
      </div>

      {indicators.pivot_p != null && (
        <div className="card p-4 space-y-2">
          <div className="flex items-end justify-between">
            <div>
              <h2 className="font-semibold tracking-tight">Pivot Levels</h2>
              <p className="text-xs text-fg-muted">
                Classical floor-trader pivots from the previous daily candle.
              </p>
            </div>
            {indicators.pivot_distance_pct != null && (
              <span className="text-xs text-fg-muted num">
                Spot vs P {fmt.pct(indicators.pivot_distance_pct, 2)}
              </span>
            )}
          </div>
          <div className="grid grid-cols-3 sm:grid-cols-7 gap-2 text-xs">
            <PivotKV label="S3" value={indicators.pivot_s3} tone="red" />
            <PivotKV label="S2" value={indicators.pivot_s2} tone="red" />
            <PivotKV label="S1" value={indicators.pivot_s1} tone="red" />
            <PivotKV label="P" value={indicators.pivot_p} />
            <PivotKV label="R1" value={indicators.pivot_r1} tone="green" />
            <PivotKV label="R2" value={indicators.pivot_r2} tone="green" />
            <PivotKV label="R3" value={indicators.pivot_r3} tone="green" />
          </div>
        </div>
      )}

      <div className="card p-4 space-y-2">
        <h2 className="font-semibold tracking-tight">Recent Signals</h2>
        {signals.length === 0 ? (
          <p className="text-xs text-fg-muted">No signals yet.</p>
        ) : (
          <div className="overflow-x-auto -mx-4">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-fg-subtle text-[11px] uppercase">
                  <th className="text-left px-3 py-1.5">When</th>
                  <th className="text-left px-3 py-1.5">Setup</th>
                  <th className="text-left px-3 py-1.5">Direction</th>
                  <th className="text-right px-3 py-1.5">Score</th>
                  <th className="text-right px-3 py-1.5">Spot</th>
                  <th className="text-right px-3 py-1.5">Entry</th>
                  <th className="text-right px-3 py-1.5">Stop</th>
                  <th className="text-right px-3 py-1.5">T1</th>
                  <th className="text-right px-3 py-1.5">T2</th>
                  <th className="text-left px-3 py-1.5">Chain</th>
                </tr>
              </thead>
              <tbody>
                {signals.map((s) => (
                  <tr
                    key={s.id}
                    className="hover:bg-bg-elevated/40 transition border-t border-border"
                  >
                    <td className="px-3 py-1.5 text-xs text-fg-muted">
                      {s.as_of_date}
                    </td>
                    <td className="px-3 py-1.5">
                      <Badge
                        tone={INDEX_CATEGORY_TONE[s.category] ?? "muted"}
                        className="!text-[11px]"
                      >
                        {INDEX_CATEGORY_LABELS[s.category] ?? s.category}
                      </Badge>
                    </td>
                    <td className="px-3 py-1.5">
                      <Badge tone={s.direction === "LONG" ? "green" : "red"}>
                        {s.direction === "LONG" ? "CE" : "PE"}
                      </Badge>
                    </td>
                    <td className="px-3 py-1.5 text-right num">
                      <Badge tone={scoreTone(s.score)}>
                        {fmt.num(s.score, 0)}
                      </Badge>
                    </td>
                    <td className="px-3 py-1.5 text-right num">
                      {fmt.num(s.spot, 2)}
                    </td>
                    <td className="px-3 py-1.5 text-right num">
                      {fmt.num(s.entry, 2)}
                    </td>
                    <td className="px-3 py-1.5 text-right num text-accent-red">
                      {fmt.num(s.stop_loss, 2)}
                    </td>
                    <td className="px-3 py-1.5 text-right num text-accent-green">
                      {fmt.num(s.target_1, 2)}
                    </td>
                    <td className="px-3 py-1.5 text-right num text-accent-green">
                      {fmt.num(s.target_2, 2)}
                    </td>
                    <td className="px-3 py-1.5">
                      {s.option_chain_bias ? (
                        <Badge
                          tone={OPTION_BIAS_TONE[s.option_chain_bias] ?? "muted"}
                        >
                          {s.option_chain_bias}
                        </Badge>
                      ) : (
                        <span className="text-fg-subtle text-xs">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {supportsChain && optionChain.data && (
        <OptionChainTable chain={optionChain.data} />
      )}
      {supportsChain && optionChain.isError && (
        <div className="card p-6 text-fg-muted flex items-start gap-2">
          <AlertTriangle className="size-4 text-accent-amber mt-1" />
          Option chain temporarily unavailable. NSE may be rate-limiting; retry in
          a minute.
        </div>
      )}

      <div className="card p-3 flex items-start gap-2 text-xs text-fg-muted">
        <AlertTriangle className="size-3.5 mt-0.5 text-accent-amber shrink-0" />
        Research and decision-support only. Not financial advice. Always validate
        against your own plan and respect the invalidation level.
      </div>
    </div>
  );
}

function KV({
  label,
  value,
}: {
  label: string;
  value: string | number | null | undefined;
}) {
  return (
    <div>
      <div className="text-fg-subtle">{label}</div>
      <div className="num">{value ?? "—"}</div>
    </div>
  );
}

function PivotKV({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | null | undefined;
  tone?: "green" | "red";
}) {
  const toneClass =
    tone === "green"
      ? "text-accent-green"
      : tone === "red"
        ? "text-accent-red"
        : "";
  return (
    <div>
      <div className="text-fg-subtle">{label}</div>
      <div className={`num ${toneClass}`}>{fmt.num(value ?? null, 2)}</div>
    </div>
  );
}
