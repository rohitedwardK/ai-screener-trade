import axios from "axios";
import type {
  AgentStatusOut,
  AllMethodStatus,
  Candle,
  CategoryCount,
  ContractRecommendation,
  DailyBriefing,
  ExplainOut,
  FastTickOut,
  IndexCandle,
  IndexDetail,
  IndexInstrument,
  IndexRow,
  LiveVerificationRunResult,
  LiveVerificationSignalRow,
  LiveVerificationSummary,
  MethodRunResult,
  MethodTrainStatus,
  MethodType,
  TrainMethodType,
  LiveMoversOut,
  OptionChain,
  RefreshResult,
  ScreenerRow,
  Stock,
  StockDetail,
  LiveAnalysisConfig,
  LiveAppMode,
  LiveDashboard,
  LiveDecision,
  LiveModeOut,
  LiveObservation,
  LiveTickOut,
  LiveWeights,
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
    include_invalidated?: boolean;
    live_status?: string;
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
// Live signal verification API
// =====================================================
const liveVerificationBase = "/v1/live-verification";

export const liveVerificationApi = {
  run: (background = false) =>
    http
      .post<LiveVerificationRunResult>(liveVerificationBase + "/run", null, {
        params: background ? { background: true } : undefined,
      })
      .then((r) => r.data),

  summary: () =>
    http
      .get<LiveVerificationSummary>(liveVerificationBase + "/summary")
      .then((r) => r.data),

  listSignals: (params?: {
    status?: string;
    symbol?: string;
    limit?: number;
  }) =>
    http
      .get<LiveVerificationSignalRow[]>(liveVerificationBase + "/signals", {
        params,
      })
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
  strikeRecommendations: (symbol: string, signal_id?: number) =>
    http
      .get<ContractRecommendation[]>(
        `/indices/${encodeURIComponent(symbol)}/strike-recommendations`,
        { params: signal_id ? { signal_id } : undefined },
      )
      .then((r) => r.data),
  activeStrikeRecommendations: () =>
    http
      .get<ContractRecommendation[]>("/indices/strike-recommendations/active")
      .then((r) => r.data),
};

// =====================================================
// Live Analysis API
// =====================================================
const liveBase = "/v1/live-analysis";

export const liveApi = {
  getMode: () => http.get<LiveModeOut>(`${liveBase}/mode`).then((r) => r.data),
  setMode: (mode: LiveAppMode) =>
    http.post<LiveModeOut>(`${liveBase}/mode`, { mode }).then((r) => r.data),

  getConfig: () =>
    http.get<LiveAnalysisConfig>(`${liveBase}/config`).then((r) => r.data),
  updateConfig: (
    patch: Partial<Omit<LiveAnalysisConfig, "weights">> & {
      weights?: Partial<LiveWeights>;
    },
  ) =>
    http
      .post<LiveAnalysisConfig>(`${liveBase}/config`, patch)
      .then((r) => r.data),

  getDashboard: () =>
    http.get<LiveDashboard>(`${liveBase}/dashboard`).then((r) => r.data),

  getDecisions: (limit = 50) =>
    http
      .get<LiveDecision[]>(`${liveBase}/decisions`, { params: { limit } })
      .then((r) => r.data),

  getObservations: (only_active = true) =>
    http
      .get<LiveObservation[]>(`${liveBase}/observations`, {
        params: { only_active },
      })
      .then((r) => r.data),

  tick: () => http.post<LiveTickOut>(`${liveBase}/tick`).then((r) => r.data),
};

// =====================================================
// Method Analysis API (demo comparison page)
// =====================================================
const maBase = "/method-analysis";

export const methodAnalysisApi = {
  train: (method: TrainMethodType) =>
    http
      .post<MethodTrainStatus>(`${maBase}/train`, null, { params: { method } })
      .then((r) => r.data),

  status: () =>
    http.get<AllMethodStatus>(`${maBase}/status`).then((r) => r.data),

  run: (method: MethodType) =>
    http
      .post<MethodRunResult>(`${maBase}/run`, null, { params: { method } })
      .then((r) => r.data),

  liveMovers: (k = 15) =>
    http
      .get<LiveMoversOut>(`${maBase}/live-movers`, { params: { k } })
      .then((r) => r.data),
};

// =====================================================
// Agentic layer (head + worker agents)
// =====================================================
const agentsBase = "/v1/agents";

export const agentsApi = {
  status: () =>
    http.get<AgentStatusOut>(`${agentsBase}/status`).then((r) => r.data),
  briefing: () =>
    http
      .get<DailyBriefing | null>(`${agentsBase}/briefing/latest`)
      .then((r) => r.data),
  briefings: (limit = 10) =>
    http
      .get<DailyBriefing[]>(`${agentsBase}/briefings`, { params: { limit } })
      .then((r) => r.data),
  runDeep: (use_llm = true) =>
    http
      .post<{ status: string; triggered_by?: string; use_llm?: boolean }>(
        `${agentsBase}/run-deep-cycle`,
        null,
        { params: { use_llm } },
      )
      .then((r) => r.data),
  runFast: () =>
    http.post<FastTickOut>(`${agentsBase}/run-fast-tick`).then((r) => r.data),
};
