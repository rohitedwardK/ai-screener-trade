import axios from "axios";
import type {
  Candle,
  CategoryCount,
  ExplainOut,
  IndexCandle,
  IndexDetail,
  IndexInstrument,
  IndexRow,
  OptionChain,
  PaperBotConfig,
  PaperBotConfigUpdate,
  PaperIndexBotConfig,
  PaperIndexBotConfigUpdate,
  PaperIndexJournal,
  PaperIndexLedgerEvent,
  PaperIndexLiveTick,
  PaperIndexOrder,
  PaperIndexPerformance,
  PaperIndexPosition,
  PaperIndexReplay,
  PaperIndexReset,
  PaperIndexSelection,
  PaperIndexSimulateDay,
  PaperIndexStatus,
  PaperIndexTradeSignal,
  PaperJournal,
  PaperLedgerEvent,
  PaperLiveDebug,
  PaperLiveTick,
  PaperOrder,
  PaperPerformance,
  PaperPosition,
  PaperReplay,
  PaperReset,
  PaperSelection,
  PaperSimulateDay,
  PaperStatus,
  PaperTradeSignal,
  RefreshResult,
  ScreenerRow,
  Stock,
  StockDetail,
} from "./types";

const baseURL = import.meta.env.VITE_API_BASE_URL ?? "/api";

export const http = axios.create({
  baseURL,
  timeout: 120_000,
});

export const api = {
  listStocks: () => http.get<Stock[]>("/stocks").then((r) => r.data),
  getStock: (symbol: string) =>
    http.get<StockDetail>(`/stocks/${symbol}`).then((r) => r.data),
  getHistory: (symbol: string, range: string) =>
    http
      .get<Candle[]>(`/stocks/${symbol}/history`, { params: { range } })
      .then((r) => r.data),

  listScreener: (params?: {
    category?: string;
    min_score?: number;
    sector?: string;
    limit?: number;
  }) => http.get<ScreenerRow[]>("/screener", { params }).then((r) => r.data),

  categories: (top_n = 3) =>
    http
      .get<CategoryCount[]>("/screener/categories", { params: { top_n } })
      .then((r) => r.data),

  explain: (symbol: string) =>
    http.get<ExplainOut>(`/explain/${symbol}`).then((r) => r.data),

  getPrices: (symbols: string[]) =>
    http
      .get<Record<string, number>>("/stocks/prices", {
        params: { symbols: symbols.join(",") },
      })
      .then((r) => r.data),

  refresh: () => http.post<RefreshResult>("/admin/refresh").then((r) => r.data),
  refreshAsync: () =>
    http.post<{ status: string }>("/admin/refresh-async").then((r) => r.data),
};

// =====================================================
// Paper Trading API client
// =====================================================
const paperBase = "/v1/paper-trading";

export const paperApi = {
  getConfig: () =>
    http.get<PaperBotConfig>(`${paperBase}/config`).then((r) => r.data),
  updateConfig: (patch: PaperBotConfigUpdate) =>
    http.post<PaperBotConfig>(`${paperBase}/config`, patch).then((r) => r.data),

  getStatus: () =>
    http.get<PaperStatus>(`${paperBase}/status`).then((r) => r.data),

  runSelection: (date?: string) =>
    http
      .post<PaperSelection>(`${paperBase}/run-selection`, null, {
        params: date ? { date } : undefined,
      })
      .then((r) => r.data),

  simulateDay: (date?: string) =>
    http
      .post<PaperSimulateDay>(`${paperBase}/simulate-day`, null, {
        params: date ? { date } : undefined,
      })
      .then((r) => r.data),

  processLiveTick: () =>
    http
      .post<PaperLiveTick>(`${paperBase}/process-live-tick`)
      .then((r) => r.data),

  liveDebug: () =>
    http.get<PaperLiveDebug>(`${paperBase}/live-debug`).then((r) => r.data),

  replay: (start: string, end: string) =>
    http
      .post<PaperReplay>(`${paperBase}/replay`, null, {
        params: { start, end },
      })
      .then((r) => r.data),

  listSignals: (params?: {
    date?: string;
    decision?: "selected" | "skipped";
    symbol?: string;
    limit?: number;
  }) =>
    http
      .get<PaperTradeSignal[]>(`${paperBase}/signals`, { params })
      .then((r) => r.data),

  listOrders: (params?: { status?: string; symbol?: string; limit?: number }) =>
    http.get<PaperOrder[]>(`${paperBase}/orders`, { params }).then((r) => r.data),

  listPositions: (params?: { status?: string; symbol?: string; limit?: number }) =>
    http
      .get<PaperPosition[]>(`${paperBase}/positions`, { params })
      .then((r) => r.data),

  listLedger: (params?: {
    from?: string;
    to?: string;
    symbol?: string;
    limit?: number;
  }) =>
    http
      .get<PaperLedgerEvent[]>(`${paperBase}/ledger`, { params })
      .then((r) => r.data),

  performance: (params?: { from?: string; to?: string }) =>
    http
      .get<PaperPerformance>(`${paperBase}/performance`, { params })
      .then((r) => r.data),

  journal: (date?: string) =>
    http
      .get<PaperJournal>(`${paperBase}/journal`, {
        params: date ? { date } : undefined,
      })
      .then((r) => r.data),

  reset: () =>
    http
      .post<PaperReset>(`${paperBase}/reset`, null, { params: { confirm: "YES" } })
      .then((r) => r.data),
};

// =====================================================
// Index Analysis API
// =====================================================
export const indicesApi = {
  list: () => http.get<IndexInstrument[]>("/indices").then((r) => r.data),
  dashboard: () => http.get<IndexRow[]>("/indices/dashboard").then((r) => r.data),
  prices: (symbols?: string[]) =>
    http
      .get<Record<string, number>>("/indices/prices", {
        params: symbols?.length ? { symbols: symbols.join(",") } : undefined,
      })
      .then((r) => r.data),
  detail: (symbol: string) =>
    http
      .get<IndexDetail>(`/indices/${encodeURIComponent(symbol)}`)
      .then((r) => r.data),
  history: (symbol: string, range = "1y") =>
    http
      .get<IndexCandle[]>(`/indices/${encodeURIComponent(symbol)}/history`, {
        params: { range },
      })
      .then((r) => r.data),
  optionChain: (symbol: string) =>
    http
      .get<OptionChain>(`/indices/${encodeURIComponent(symbol)}/option-chain`)
      .then((r) => r.data),
};

// =====================================================
// Paper Index Trading API
// =====================================================
const paperIndexBase = "/v1/paper-index-trading";

export const paperIndexApi = {
  getConfig: () =>
    http.get<PaperIndexBotConfig>(`${paperIndexBase}/config`).then((r) => r.data),
  updateConfig: (patch: PaperIndexBotConfigUpdate) =>
    http
      .post<PaperIndexBotConfig>(`${paperIndexBase}/config`, patch)
      .then((r) => r.data),
  getStatus: () =>
    http.get<PaperIndexStatus>(`${paperIndexBase}/status`).then((r) => r.data),

  runSelection: (date?: string) =>
    http
      .post<PaperIndexSelection>(`${paperIndexBase}/run-selection`, null, {
        params: date ? { date } : undefined,
      })
      .then((r) => r.data),

  simulateDay: (date?: string) =>
    http
      .post<PaperIndexSimulateDay>(`${paperIndexBase}/simulate-day`, null, {
        params: date ? { date } : undefined,
      })
      .then((r) => r.data),

  processLiveTick: () =>
    http
      .post<PaperIndexLiveTick>(`${paperIndexBase}/process-live-tick`)
      .then((r) => r.data),

  replay: (start: string, end: string) =>
    http
      .post<PaperIndexReplay>(`${paperIndexBase}/replay`, null, {
        params: { start, end },
      })
      .then((r) => r.data),

  listSignals: (params?: {
    date?: string;
    decision?: "selected" | "skipped";
    symbol?: string;
    limit?: number;
  }) =>
    http
      .get<PaperIndexTradeSignal[]>(`${paperIndexBase}/signals`, { params })
      .then((r) => r.data),

  listOrders: (params?: { status?: string; symbol?: string; limit?: number }) =>
    http
      .get<PaperIndexOrder[]>(`${paperIndexBase}/orders`, { params })
      .then((r) => r.data),

  listPositions: (params?: {
    status?: string;
    symbol?: string;
    limit?: number;
  }) =>
    http
      .get<PaperIndexPosition[]>(`${paperIndexBase}/positions`, { params })
      .then((r) => r.data),

  listLedger: (params?: {
    from?: string;
    to?: string;
    symbol?: string;
    limit?: number;
  }) =>
    http
      .get<PaperIndexLedgerEvent[]>(`${paperIndexBase}/ledger`, { params })
      .then((r) => r.data),

  performance: (params?: { from?: string; to?: string }) =>
    http
      .get<PaperIndexPerformance>(`${paperIndexBase}/performance`, { params })
      .then((r) => r.data),

  journal: (date?: string) =>
    http
      .get<PaperIndexJournal>(`${paperIndexBase}/journal`, {
        params: date ? { date } : undefined,
      })
      .then((r) => r.data),

  reset: () =>
    http
      .post<PaperIndexReset>(`${paperIndexBase}/reset`, null, {
        params: { confirm: "YES" },
      })
      .then((r) => r.data),
};
