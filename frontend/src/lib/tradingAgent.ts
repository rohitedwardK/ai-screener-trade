import type { LiveVerification, ScreenerRow } from "@/api/types";
import type { CloseReason, PaperTrade } from "@/lib/paperTrades";

/** How the Trading Agent last assessed an open position. */
export type TradeMonitorStatus =
  | "WATCHING"
  | "NEAR_STOP"
  | "NEAR_TARGET"
  | "THESIS_WEAK"
  | "EXIT_NOW";

export interface TradeMonitorVerdict {
  tradeId: string;
  symbol: string;
  status: TradeMonitorStatus;
  /** When set, the agent recommends closing at this price for the given reason. */
  action: CloseReason | null;
  exitPrice: number | null;
  message: string;
  livePrice: number | null;
  /** Distance from live price to key levels (percent of live). */
  distanceToStopPct: number | null;
  distanceToTargetPct: number | null;
  distanceToInvalidationPct: number | null;
  screenerLiveStatus: LiveVerification["status"] | null;
}

export interface TradingAgentTick {
  checkedAt: string;
  verdicts: TradeMonitorVerdict[];
  autoClosed: { tradeId: string; symbol: string; reason: CloseReason; price: number }[];
}

const NEAR_LEVEL_PCT = 1.5;

function pctDistance(from: number, to: number): number | null {
  if (!Number.isFinite(from) || !Number.isFinite(to) || from <= 0) return null;
  return ((to - from) / from) * 100;
}

function pickScreenerRow(
  rows: ScreenerRow[],
  symbol: string,
  category: string | null,
): ScreenerRow | null {
  const matches = rows.filter((r) => r.symbol === symbol);
  if (matches.length === 0) return null;
  if (category) {
    const sameCat = matches.find((r) => r.category === category);
    if (sameCat) return sameCat;
  }
  return matches.sort((a, b) => b.score - a.score)[0] ?? null;
}

/**
 * Deterministic exit rule engine for directional paper positions. Uses the levels captured at
 * buy time first; optionally incorporates the current screener live-verifier
 * status when the symbol still appears in the run.
 */
export function evaluateOpenTrade(
  trade: PaperTrade,
  livePrice: number | null | undefined,
  screenerRow?: ScreenerRow | null,
): TradeMonitorVerdict {
  const base: TradeMonitorVerdict = {
    tradeId: trade.id,
    symbol: trade.symbol,
    status: "WATCHING",
    action: null,
    exitPrice: null,
    message: "Within plan — monitoring entry, stop, targets, and invalidation.",
    livePrice: livePrice ?? null,
    distanceToStopPct: null,
    distanceToTargetPct: null,
    distanceToInvalidationPct: null,
    screenerLiveStatus: screenerRow?.live?.status ?? null,
  };

  if (livePrice == null || !Number.isFinite(livePrice)) {
    return {
      ...base,
      status: "WATCHING",
      message: "Waiting for live price before level checks.",
    };
  }

  const stop = trade.stopLoss;
  const inv = trade.invalidation;
  const t1 = trade.target1;
  const t2 = trade.target2;
  const isShort = trade.direction === "SHORT";

  if (stop != null) {
    base.distanceToStopPct = pctDistance(livePrice, stop);
  }
  if (t1 != null) {
    base.distanceToTargetPct = pctDistance(livePrice, t1);
  }
  if (inv != null) {
    base.distanceToInvalidationPct = pctDistance(livePrice, inv);
  }

  // Hard exits — price has crossed a recorded plan level.
  if (stop != null && (isShort ? livePrice >= stop : livePrice <= stop)) {
    return {
      ...base,
      status: "EXIT_NOW",
      action: "STOP_LOSS",
      exitPrice: livePrice,
      message: `Live ${livePrice.toFixed(2)} crossed stop ${stop.toFixed(2)} — close the ${trade.direction.toLowerCase()} thesis.`,
    };
  }
  if (inv != null && (isShort ? livePrice > inv : livePrice < inv)) {
    return {
      ...base,
      status: "EXIT_NOW",
      action: "INVALIDATION",
      exitPrice: livePrice,
      message: `Live ${livePrice.toFixed(2)} crossed invalidation ${inv.toFixed(2)} — thesis broken.`,
    };
  }
  if (t2 != null && (isShort ? livePrice <= t2 : livePrice >= t2)) {
    return {
      ...base,
      status: "EXIT_NOW",
      action: "TARGET_2",
      exitPrice: livePrice,
      message: `Live ${livePrice.toFixed(2)} reached target 2 ${t2.toFixed(2)} — book profit.`,
    };
  }
  if (t1 != null && (isShort ? livePrice <= t1 : livePrice >= t1)) {
    return {
      ...base,
      status: "EXIT_NOW",
      action: "TARGET_1",
      exitPrice: livePrice,
      message: `Live ${livePrice.toFixed(2)} reached target 1 ${t1.toFixed(2)} — book profit.`,
    };
  }

  // Screener intelligence — live verifier flagged the persisted signal.
  const liveStatus = screenerRow?.live?.status;
  if (liveStatus === "INVALIDATED") {
    return {
      ...base,
      status: "EXIT_NOW",
      action: "INVALIDATION",
      exitPrice: livePrice,
      message: "Screener live status INVALIDATED — close per signal verification.",
    };
  }
  if (liveStatus === "WEAKENING") {
    return {
      ...base,
      status: "THESIS_WEAK",
      message: "Screener live status WEAKENING — tighten risk or consider exit.",
    };
  }

  // Proximity warnings.
  if (
    base.distanceToStopPct != null &&
    (isShort ? base.distanceToStopPct > 0 : base.distanceToStopPct < 0) &&
    Math.abs(base.distanceToStopPct) <= NEAR_LEVEL_PCT
  ) {
    return {
      ...base,
      status: "NEAR_STOP",
      message: `Within ${NEAR_LEVEL_PCT}% of stop — watch invalidation closely.`,
    };
  }
  if (
    base.distanceToTargetPct != null &&
    (isShort ? base.distanceToTargetPct < 0 : base.distanceToTargetPct > 0) &&
    Math.abs(base.distanceToTargetPct) <= NEAR_LEVEL_PCT
  ) {
    return {
      ...base,
      status: "NEAR_TARGET",
      message: `Within ${NEAR_LEVEL_PCT}% of target 1 — prepare to book profit.`,
    };
  }

  if (liveStatus === "STRENGTHENED" || liveStatus === "CONFIRMED") {
    return {
      ...base,
      status: "WATCHING",
      message: `Screener live ${liveStatus.replace(/_/g, " ").toLowerCase()} — hold while levels intact.`,
    };
  }

  return base;
}

export function runTradingAgentTick(
  openTrades: PaperTrade[],
  priceMap: Record<string, number> | undefined,
  screenerRows: ScreenerRow[] | undefined,
  autoClose: boolean,
  closeTrade: (id: string, price: number, reason: CloseReason) => void,
): TradingAgentTick {
  const checkedAt = new Date().toISOString();
  const autoClosed: TradingAgentTick["autoClosed"] = [];
  const verdicts: TradeMonitorVerdict[] = [];

  for (const trade of openTrades) {
    const row = screenerRows
      ? pickScreenerRow(screenerRows, trade.symbol, trade.category)
      : null;
    const live = priceMap?.[trade.symbol];
    const verdict = evaluateOpenTrade(trade, live, row);
    verdicts.push(verdict);

    if (
      autoClose &&
      verdict.action &&
      verdict.exitPrice != null &&
      Number.isFinite(verdict.exitPrice)
    ) {
      closeTrade(trade.id, verdict.exitPrice, verdict.action);
      autoClosed.push({
        tradeId: trade.id,
        symbol: trade.symbol,
        reason: verdict.action,
        price: verdict.exitPrice,
      });
    }
  }

  return { checkedAt, verdicts, autoClosed };
}

export const CLOSE_REASON_LABEL: Record<CloseReason, string> = {
  MANUAL: "Manual sell",
  STOP_LOSS: "Stop loss",
  INVALIDATION: "Invalidation",
  TARGET_1: "Target 1",
  TARGET_2: "Target 2",
};

export const MONITOR_STATUS_TONE: Record<
  TradeMonitorStatus,
  "green" | "red" | "amber" | "blue" | "muted"
> = {
  WATCHING: "blue",
  NEAR_STOP: "amber",
  NEAR_TARGET: "green",
  THESIS_WEAK: "amber",
  EXIT_NOW: "red",
};
