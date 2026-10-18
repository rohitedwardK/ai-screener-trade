import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { ScreenerRow } from "@/api/types";

/**
 * Client-side paper-trading ledger.
 *
 * A "trade" is a simulated long position opened from a screener signal: buy a
 * fixed lot (default 10 shares) at the price shown when the user clicks Buy,
 * then track P&L against the live price until the user clicks Sell. Everything
 * lives in localStorage — there is no backend persistence and, importantly, no
 * real order ever leaves the browser. This is evaluation-only tooling to see
 * how the screener's signals would have behaved.
 */
export type CloseReason =
  | "MANUAL"
  | "STOP_LOSS"
  | "INVALIDATION"
  | "TARGET_1"
  | "TARGET_2";

export interface PaperTrade {
  id: string;
  symbol: string;
  name: string | null;
  /** Signal category at the time of purchase (e.g. TREND_PULLBACK). */
  category: string | null;
  /** Signal score at the time of purchase, for later evaluation. */
  scoreAtBuy: number | null;
  /** Plan levels captured from the screener row at buy time. */
  entry: number | null;
  stopLoss: number | null;
  target1: number | null;
  target2: number | null;
  invalidation: number | null;
  /** Directional thesis: LONG profits when price rises, SHORT when it falls. */
  direction: "LONG" | "SHORT";
  quantity: number;
  buyPrice: number;
  buyAt: string; // ISO
  status: "OPEN" | "CLOSED";
  sellPrice: number | null;
  sellAt: string | null; // ISO
  closeReason: CloseReason | null;
}

export const DEFAULT_QTY = 10;

interface BuyInput {
  symbol: string;
  name?: string | null;
  category?: string | null;
  scoreAtBuy?: number | null;
  entry?: number | null;
  stopLoss?: number | null;
  target1?: number | null;
  target2?: number | null;
  invalidation?: number | null;
  direction?: "LONG" | "SHORT";
  price: number;
  quantity?: number;
}

interface PaperTradesState {
  trades: PaperTrade[];
  /** Open a long position. No-op if an OPEN position already exists for the symbol. */
  buy: (input: BuyInput) => void;
  /** Close an OPEN position at the given price, recording realized P&L. */
  sell: (id: string, sellPrice: number, reason?: CloseReason) => void;
  /** Remove a single trade from history. */
  remove: (id: string) => void;
  /** Drop all closed trades, keep open positions. */
  clearClosed: () => void;
  /** Wipe the entire ledger. */
  clearAll: () => void;
}

const STORAGE_KEY = "paper-trades";

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function legacyDirection(category: string | null): "LONG" | "SHORT" {
  const bearish = new Set([
    "TREND_BREAKDOWN",
    "BREAKDOWN_RETEST",
    "RALLY_TO_RESISTANCE",
    "WEAK_AVOID",
    "OVERBOUGHT_AVOID",
  ]);
  return category && bearish.has(category.toUpperCase()) ? "SHORT" : "LONG";
}

export const usePaperTrades = create<PaperTradesState>()(
  persist(
    (set) => ({
      trades: [],

      buy: (input) =>
        set((s) => {
          const alreadyOpen = s.trades.some(
            (t) => t.symbol === input.symbol && t.status === "OPEN",
          );
          if (alreadyOpen) return s;
          const trade: PaperTrade = {
            id: newId(),
            symbol: input.symbol,
            name: input.name ?? null,
            category: input.category ?? null,
            scoreAtBuy: input.scoreAtBuy ?? null,
            entry: input.entry ?? input.price,
            stopLoss: input.stopLoss ?? null,
            target1: input.target1 ?? null,
            target2: input.target2 ?? null,
            invalidation: input.invalidation ?? null,
            direction: input.direction ?? "LONG",
            quantity: input.quantity ?? DEFAULT_QTY,
            buyPrice: input.price,
            buyAt: new Date().toISOString(),
            status: "OPEN",
            sellPrice: null,
            sellAt: null,
            closeReason: null,
          };
          return { trades: [trade, ...s.trades] };
        }),

      sell: (id, sellPrice, reason = "MANUAL") =>
        set((s) => ({
          trades: s.trades.map((t) =>
            t.id === id && t.status === "OPEN"
              ? {
                  ...t,
                  status: "CLOSED",
                  sellPrice,
                  sellAt: new Date().toISOString(),
                  closeReason: reason,
                }
              : t,
          ),
        })),

      remove: (id) =>
        set((s) => ({ trades: s.trades.filter((t) => t.id !== id) })),

      clearClosed: () =>
        set((s) => ({ trades: s.trades.filter((t) => t.status === "OPEN") })),

      clearAll: () => set({ trades: [] }),
    }),
    {
      name: STORAGE_KEY,
      // Existing positions predate directional tracking and retain their
      // original long behavior; newly opened signals persist their direction.
      version: 2,
      migrate: (persistedState) => {
        const state = persistedState as Partial<PaperTradesState>;
        return {
          ...state,
          trades: (state.trades ?? []).map((trade) => ({
            ...trade,
            direction: trade.direction ?? legacyDirection(trade.category),
          })),
        } as PaperTradesState;
      },
      storage: createJSONStorage(() => localStorage),
    },
  ),
);

// ---------------------------------------------------------------------------
// Pure helpers (kept outside the store so components can reuse them freely).
// ---------------------------------------------------------------------------

/** The still-open position for a symbol, or null. */
export function openTradeForSymbol(
  trades: PaperTrade[],
  symbol: string,
): PaperTrade | null {
  return trades.find((t) => t.symbol === symbol && t.status === "OPEN") ?? null;
}

/** Rupees invested at entry. */
export function invested(t: PaperTrade): number {
  return t.buyPrice * t.quantity;
}

/**
 * The price used to value a trade right now: the recorded sell price for a
 * closed trade, otherwise the supplied live price. Returns null when an open
 * trade has no live price yet (so callers can show "—").
 */
export function exitPrice(
  t: PaperTrade,
  livePrice: number | null | undefined,
): number | null {
  if (t.status === "CLOSED") return t.sellPrice;
  return livePrice != null && Number.isFinite(livePrice) ? livePrice : null;
}

/** Absolute P&L in rupees, or null when it can't be computed yet. */
export function tradePnl(
  t: PaperTrade,
  livePrice: number | null | undefined,
): number | null {
  const exit = exitPrice(t, livePrice);
  if (exit == null) return null;
  const move = exit - t.buyPrice;
  return (t.direction === "SHORT" ? -move : move) * t.quantity;
}

/** P&L as a percentage of the invested amount, or null. */
export function tradePnlPct(
  t: PaperTrade,
  livePrice: number | null | undefined,
): number | null {
  const pnl = tradePnl(t, livePrice);
  const cost = invested(t);
  if (pnl == null || cost <= 0) return null;
  return (pnl / cost) * 100;
}

/**
 * Map a screener row to a paper-trade direction used by the frontend UI.
 * Missing or WAIT/NEUTRAL rows are not trades.
 */
export function screenerPaperDirection(
  row: ScreenerRow | { direction?: string | null },
): "LONG" | "SHORT" | "WAIT" {
  const dir = (row?.direction ?? "").toString().toUpperCase().trim();
  if (!dir || dir === "WAIT" || dir === "NEUTRAL") return "WAIT";
  if (dir.includes("CE") || dir.includes("CALL") || dir.includes("BUY") || dir === "LONG") return "LONG";
  if (dir.includes("PE") || dir.includes("PUT") || dir.includes("SELL") || dir === "SHORT") return "SHORT";
  return "WAIT";
}
