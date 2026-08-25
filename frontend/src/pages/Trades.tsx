import { useEffect, useMemo, useRef, useState } from "react";

import { Link } from "react-router-dom";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";

import { Badge } from "@/components/Badge";

import { TradingAgentPanel } from "@/components/trades/TradingAgentPanel";

import { fmt, formatDateTimeIST, symbolDisplay } from "@/lib/format";

import {

  exitPrice,

  invested,

  tradePnl,

  tradePnlPct,

  usePaperTrades,

} from "@/lib/paperTrades";

import {

  CLOSE_REASON_LABEL,

  MONITOR_STATUS_TONE,

  runTradingAgentTick,

} from "@/lib/tradingAgent";

import type { TradeMonitorVerdict, TradingAgentTick } from "@/lib/tradingAgent";

import {

  RefreshCw,

  Trash2,

  TrendingDown,

  TrendingUp,

  Wallet,

} from "lucide-react";



const PRICE_REFRESH_INTERVAL = 60_000;

const AUTO_CLOSE_KEY = "trading-agent-auto-close";



function pnlTone(pnl: number | null): string {

  if (pnl == null) return "text-fg-muted";

  if (pnl > 0) return "text-accent-green";

  if (pnl < 0) return "text-accent-red";

  return "text-fg";

}



function holdingDuration(buyAt: string, sellAt: string | null): string {

  const end = sellAt ? new Date(sellAt).getTime() : Date.now();

  const ms = Math.max(0, end - new Date(buyAt).getTime());

  const mins = Math.floor(ms / 60000);

  if (mins < 60) return `${mins}m`;

  const hours = Math.floor(mins / 60);

  if (hours < 24) return `${hours}h ${mins % 60}m`;

  const days = Math.floor(hours / 24);

  return `${days}d ${hours % 24}h`;

}



function readAutoClosePref(): boolean {

  try {

    const v = localStorage.getItem(AUTO_CLOSE_KEY);

    return v == null ? true : v === "true";

  } catch {

    return true;

  }

}



export function Trades() {

  const trades = usePaperTrades((s) => s.trades);

  const sell = usePaperTrades((s) => s.sell);

  const remove = usePaperTrades((s) => s.remove);

  const clearClosed = usePaperTrades((s) => s.clearClosed);



  const [autoCloseEnabled, setAutoCloseEnabled] = useState(readAutoClosePref);

  const [agentTick, setAgentTick] = useState<TradingAgentTick | null>(null);

  const lastCheckedPrices = useRef<string>("");



  const open = useMemo(

    () => trades.filter((t) => t.status === "OPEN"),

    [trades],

  );

  const closed = useMemo(

    () =>

      trades

        .filter((t) => t.status === "CLOSED")

        .sort((a, b) => (b.sellAt ?? "").localeCompare(a.sellAt ?? "")),

    [trades],

  );



  const openSymbols = useMemo(

    () => [...new Set(open.map((t) => t.symbol))],

    [open],

  );



  const {

    data: priceMap,

    dataUpdatedAt,

    isFetching: pricesFetching,

  } = useQuery({

    queryKey: ["trades-prices", openSymbols],

    queryFn: () => api.getPrices(openSymbols),

    enabled: openSymbols.length > 0,

    refetchInterval: PRICE_REFRESH_INTERVAL,

    refetchIntervalInBackground: true,

  });



  const { data: screenerRows, isFetching: screenerFetching } = useQuery({

    queryKey: ["trades-screener"],

    queryFn: () => api.listScreener({ min_score: 0, include_invalidated: true }),

    enabled: openSymbols.length > 0,

    refetchInterval: PRICE_REFRESH_INTERVAL,

    refetchIntervalInBackground: true,

  });



  const screenerForOpen = useMemo(() => {

    if (!screenerRows) return undefined;

    const set = new Set(openSymbols);

    return screenerRows.filter((r) => set.has(r.symbol));

  }, [screenerRows, openSymbols]);



  const verdictByTradeId = useMemo(() => {
    const map = new Map<string, TradeMonitorVerdict>();
    for (const v of agentTick?.verdicts ?? []) {
      map.set(v.tradeId, v);
    }
    return map;
  }, [agentTick]);



  // Trading Agent tick — re-run when prices or screener refresh.

  useEffect(() => {

    if (open.length === 0) {

      setAgentTick(null);

      return;

    }

    const priceKey = `${dataUpdatedAt}-${JSON.stringify(priceMap ?? {})}`;

    if (priceKey === lastCheckedPrices.current && agentTick != null) return;

    lastCheckedPrices.current = priceKey;



    const tick = runTradingAgentTick(

      open,

      priceMap,

      screenerForOpen,

      autoCloseEnabled,

      sell,

    );

    setAgentTick(tick);

    // sell is stable from zustand; open/priceMap drive re-evaluation

    // eslint-disable-next-line react-hooks/exhaustive-deps

  }, [open, priceMap, screenerForOpen, dataUpdatedAt, autoCloseEnabled]);



  const onToggleAutoClose = (enabled: boolean) => {

    setAutoCloseEnabled(enabled);

    try {

      localStorage.setItem(AUTO_CLOSE_KEY, String(enabled));

    } catch {

      /* ignore */

    }

  };



  const [countdown, setCountdown] = useState(PRICE_REFRESH_INTERVAL / 1000);

  useEffect(() => {

    setCountdown(PRICE_REFRESH_INTERVAL / 1000);

  }, [dataUpdatedAt]);

  useEffect(() => {

    if (openSymbols.length === 0) return;

    const id = setInterval(() => {

      setCountdown((s) => (s <= 1 ? PRICE_REFRESH_INTERVAL / 1000 : s - 1));

    }, 1000);

    return () => clearInterval(id);

  }, [openSymbols.length]);



  const priceFor = (symbol: string) => priceMap?.[symbol];



  const summary = useMemo(() => {

    let investedOpen = 0;

    let unrealized = 0;

    let unrealizedResolved = true;

    for (const t of open) {

      investedOpen += invested(t);

      const p = tradePnl(t, priceFor(t.symbol));

      if (p == null) unrealizedResolved = false;

      else unrealized += p;

    }

    let realized = 0;

    let wins = 0;

    for (const t of closed) {

      const p = tradePnl(t, null) ?? 0;

      realized += p;

      if (p > 0) wins += 1;

    }

    const winRate = closed.length > 0 ? (wins / closed.length) * 100 : null;

    return {

      investedOpen,

      unrealized,

      unrealizedResolved,

      realized,

      total: realized + unrealized,

      openCount: open.length,

      closedCount: closed.length,

      winRate,

    };

    // eslint-disable-next-line react-hooks/exhaustive-deps

  }, [open, closed, priceMap]);



  const isFetching = pricesFetching || screenerFetching;



  return (

    <div className="space-y-4">

      <div className="flex items-end justify-between flex-wrap gap-3">

        <div>

          <h1 className="text-2xl font-semibold tracking-tight">Trades</h1>

          <p className="text-fg-muted text-sm mt-1">

            Paper trades opened from screener signals. The Trading Agent monitors

            each open position against entry, stop, targets, and invalidation from

            the screener — stored locally, no real orders.

          </p>

        </div>

        {openSymbols.length > 0 && (

          <span className="flex items-center gap-1.5 text-xs text-fg-muted">

            <RefreshCw className={`size-3 ${isFetching ? "animate-spin" : ""}`} />

            Agent refresh in {countdown}s

          </span>

        )}

      </div>



      {open.length > 0 && (

        <TradingAgentPanel

          tick={agentTick}

          autoCloseEnabled={autoCloseEnabled}

          onToggleAutoClose={onToggleAutoClose}

          isFetching={isFetching}

        />

      )}



      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">

        <SummaryCard

          label="Total P&L"

          value={fmt.inr(summary.total)}

          tone={pnlTone(summary.total)}

          hint={`${summary.openCount} open · ${summary.closedCount} closed`}

        />

        <SummaryCard

          label="Unrealized (open)"

          value={summary.unrealizedResolved ? fmt.inr(summary.unrealized) : "—"}

          tone={pnlTone(summary.unrealizedResolved ? summary.unrealized : null)}

          hint={`Invested ${fmt.inr(summary.investedOpen)}`}

        />

        <SummaryCard

          label="Realized (closed)"

          value={fmt.inr(summary.realized)}

          tone={pnlTone(summary.realized)}

          hint={`${summary.closedCount} trade${summary.closedCount === 1 ? "" : "s"}`}

        />

        <SummaryCard

          label="Win rate"

          value={summary.winRate == null ? "—" : `${fmt.num(summary.winRate, 0)}%`}

          tone="text-fg"

          hint="Closed trades in profit"

        />

      </div>



      {trades.length === 0 && (

        <div className="card p-12 text-center text-fg-muted">

          <Wallet className="size-6 mx-auto mb-3 text-fg-subtle" />

          No paper trades yet. Head to the{" "}

          <Link to="/screener" className="text-accent-blue hover:underline">

            Screener

          </Link>{" "}

          and hit <span className="text-accent-green font-medium">Buy</span> on a

          signal to start tracking one.

        </div>

      )}



      {open.length > 0 && (

        <section className="space-y-2">

          <h2 className="text-sm font-semibold text-fg-muted uppercase tracking-wide">

            Open positions ({open.length})

          </h2>

          <div className="card overflow-hidden">

            <div className="overflow-x-auto">

              <table className="w-full text-sm">

                <thead className="text-xs uppercase tracking-wide text-fg-muted">

                  <tr className="border-b border-border">

                    <th className="px-3 py-2 text-left">Symbol</th>

                    <th className="px-3 py-2 text-left">Agent</th>

                    <th className="px-3 py-2 text-right">Qty</th>

                    <th className="px-3 py-2 text-right">Buy</th>

                    <th className="px-3 py-2 text-right">Stop / Inv</th>

                    <th className="px-3 py-2 text-right">Target</th>

                    <th className="px-3 py-2 text-right">Live</th>

                    <th className="px-3 py-2 text-right">P&amp;L</th>

                    <th className="px-3 py-2 text-right">Opened</th>

                    <th className="px-3 py-2 text-right">Action</th>

                  </tr>

                </thead>

                <tbody>

                  {open.map((t) => {

                    const live = priceFor(t.symbol);

                    const px = exitPrice(t, live);

                    const pnl = tradePnl(t, live);

                    const pct = tradePnlPct(t, live);

                    const verdict = verdictByTradeId.get(t.id);

                    return (

                      <tr

                        key={t.id}

                        className="border-b border-border last:border-b-0 hover:bg-bg-elevated"

                      >

                        <td className="px-3 py-2">

                          <Link

                            to={`/stock/${t.symbol}`}

                            className="font-medium text-fg hover:text-accent-blue"

                          >

                            {symbolDisplay(t.symbol)}

                          </Link>

                          <div className="text-[11px] text-fg-subtle truncate max-w-[160px]">

                            {t.name ?? ""}

                          </div>

                        </td>

                        <td className="px-3 py-2">

                          {verdict ? (

                            <Badge tone={MONITOR_STATUS_TONE[verdict.status]}>

                              {verdict.status.replace(/_/g, " ")}

                            </Badge>

                          ) : (

                            <span className="text-fg-subtle text-xs">—</span>

                          )}

                        </td>

                        <td className="px-3 py-2 text-right num">{t.quantity}</td>

                        <td className="px-3 py-2 text-right num">{fmt.inr(t.buyPrice)}</td>

                        <td className="px-3 py-2 text-right num text-xs">

                          {t.stopLoss != null ? (

                            <span className="text-accent-red">{fmt.inr(t.stopLoss)}</span>

                          ) : (

                            "—"

                          )}

                          {t.invalidation != null && (

                            <span className="text-fg-subtle">

                              {" "}

                              / {fmt.inr(t.invalidation)}

                            </span>

                          )}

                        </td>

                        <td className="px-3 py-2 text-right num text-xs text-accent-green">

                          {t.target1 != null ? fmt.inr(t.target1) : "—"}

                          {t.target2 != null && (

                            <span className="text-fg-subtle"> / {fmt.inr(t.target2)}</span>

                          )}

                        </td>

                        <td className="px-3 py-2 text-right num">

                          {px != null ? fmt.inr(px) : "—"}

                        </td>

                        <td className={`px-3 py-2 text-right num ${pnlTone(pnl)}`}>

                          {pnl != null ? (

                            <span className="inline-flex items-center justify-end gap-1">

                              {pnl > 0 ? (

                                <TrendingUp className="size-3" />

                              ) : pnl < 0 ? (

                                <TrendingDown className="size-3" />

                              ) : null}

                              {pnl >= 0 ? "+" : ""}

                              {fmt.inr(pnl)}

                              {pct != null && (

                                <span className="text-[10px]">

                                  ({pct >= 0 ? "+" : ""}

                                  {fmt.num(pct, 2)}%)

                                </span>

                              )}

                            </span>

                          ) : (

                            "—"

                          )}

                        </td>

                        <td className="px-3 py-2 text-right text-[11px] text-fg-muted num">

                          {formatDateTimeIST(t.buyAt)}

                        </td>

                        <td className="px-3 py-2 text-right">

                          <button

                            type="button"

                            onClick={() => px != null && sell(t.id, px)}

                            disabled={px == null}

                            className="inline-flex items-center gap-1 rounded-md border border-accent-red/40 bg-accent-red/10 px-2 py-1 text-xs font-medium text-accent-red hover:bg-accent-red/20 disabled:opacity-40"

                            title={

                              px == null

                                ? "Waiting for live price"

                                : `Sell ${t.quantity} @ ${fmt.inr(px)}`

                            }

                          >

                            <TrendingDown className="size-3" />

                            Sell

                          </button>

                        </td>

                      </tr>

                    );

                  })}

                </tbody>

              </table>

            </div>

          </div>

        </section>

      )}



      {closed.length > 0 && (

        <section className="space-y-2">

          <div className="flex items-center justify-between">

            <h2 className="text-sm font-semibold text-fg-muted uppercase tracking-wide">

              Trade history ({closed.length})

            </h2>

            <button

              type="button"

              onClick={clearClosed}

              className="text-xs text-fg-subtle hover:text-accent-red inline-flex items-center gap-1"

              title="Remove all closed trades from history"

            >

              <Trash2 className="size-3" />

              Clear history

            </button>

          </div>

          <div className="card overflow-hidden">

            <div className="overflow-x-auto">

              <table className="w-full text-sm">

                <thead className="text-xs uppercase tracking-wide text-fg-muted">

                  <tr className="border-b border-border">

                    <th className="px-3 py-2 text-left">Symbol</th>

                    <th className="px-3 py-2 text-right">Qty</th>

                    <th className="px-3 py-2 text-right">Buy</th>

                    <th className="px-3 py-2 text-right">Sell</th>

                    <th className="px-3 py-2 text-left">Exit</th>

                    <th className="px-3 py-2 text-right">P&amp;L</th>

                    <th className="px-3 py-2 text-right">Opened</th>

                    <th className="px-3 py-2 text-right">Closed</th>

                    <th className="px-3 py-2 text-right"></th>

                  </tr>

                </thead>

                <tbody>

                  {closed.map((t) => {

                    const pnl = tradePnl(t, null);

                    const pct = tradePnlPct(t, null);

                    const reasonLabel = t.closeReason

                      ? CLOSE_REASON_LABEL[t.closeReason]

                      : "Manual sell";

                    return (

                      <tr

                        key={t.id}

                        className="border-b border-border last:border-b-0 hover:bg-bg-elevated"

                      >

                        <td className="px-3 py-2">

                          <Link

                            to={`/stock/${t.symbol}`}

                            className="font-medium text-fg hover:text-accent-blue"

                          >

                            {symbolDisplay(t.symbol)}

                          </Link>

                          <div className="text-[11px] text-fg-subtle truncate max-w-[160px]">

                            {t.name ?? ""}

                          </div>

                        </td>

                        <td className="px-3 py-2 text-right num">{t.quantity}</td>

                        <td className="px-3 py-2 text-right num">{fmt.inr(t.buyPrice)}</td>

                        <td className="px-3 py-2 text-right num">

                          {t.sellPrice != null ? fmt.inr(t.sellPrice) : "—"}

                        </td>

                        <td className="px-3 py-2">

                          <Badge

                            tone={

                              t.closeReason === "TARGET_1" || t.closeReason === "TARGET_2"

                                ? "green"

                                : t.closeReason === "STOP_LOSS" ||

                                    t.closeReason === "INVALIDATION"

                                  ? "red"

                                  : "muted"

                            }

                          >

                            {reasonLabel}

                          </Badge>

                        </td>

                        <td className={`px-3 py-2 text-right num ${pnlTone(pnl)}`}>

                          {pnl != null ? (

                            <span>

                              {pnl >= 0 ? "+" : ""}

                              {fmt.inr(pnl)}

                              {pct != null && (

                                <span className="text-[10px]">

                                  {" "}

                                  ({pct >= 0 ? "+" : ""}

                                  {fmt.num(pct, 2)}%)

                                </span>

                              )}

                            </span>

                          ) : (

                            "—"

                          )}

                        </td>

                        <td className="px-3 py-2 text-right text-[11px] text-fg-muted num">

                          {formatDateTimeIST(t.buyAt)}

                        </td>

                        <td className="px-3 py-2 text-right text-[11px] text-fg-muted num">

                          {formatDateTimeIST(t.sellAt)}

                        </td>

                        <td className="px-3 py-2 text-right">

                          <button

                            type="button"

                            onClick={() => remove(t.id)}

                            className="text-fg-subtle hover:text-accent-red"

                            title="Delete this trade"

                          >

                            <Trash2 className="size-3.5" />

                          </button>

                        </td>

                      </tr>

                    );

                  })}

                </tbody>

              </table>

            </div>

          </div>

        </section>

      )}

    </div>

  );

}



function SummaryCard({

  label,

  value,

  tone,

  hint,

}: {

  label: string;

  value: string;

  tone: string;

  hint?: string;

}) {

  return (

    <div className="card p-4 flex flex-col gap-1">

      <span className="text-[11px] uppercase tracking-wide text-fg-muted">

        {label}

      </span>

      <span className={`text-xl font-semibold num ${tone}`}>{value}</span>

      {hint && <span className="text-[11px] text-fg-subtle">{hint}</span>}

    </div>

  );

}


