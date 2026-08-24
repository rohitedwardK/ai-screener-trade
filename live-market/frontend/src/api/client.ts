import axios from "axios";
import type {
  Dashboard,
  Health,
  IndexDetail,
  OptionBias,
  OptionChain,
  RegimeSnapshot,
  ScalpSetup,
  StrikeRecommendations,
  SwingSetup,
  TickResult,
} from "./types";

const baseURL = import.meta.env.VITE_API_BASE_URL ?? "/api";

const http = axios.create({
  baseURL,
  timeout: 15_000,
});

export const api = {
  dashboard: async (): Promise<Dashboard> => {
    const { data } = await http.get<Dashboard>("/v1/market/dashboard");
    return data;
  },
  indexDetail: async (
    symbol: string,
    lookback = 180,
    historyLimit = 20,
  ): Promise<IndexDetail> => {
    const { data } = await http.get<IndexDetail>(
      `/v1/chart/${encodeURIComponent(symbol)}`,
      { params: { lookback, history_limit: historyLimit } },
    );
    return data;
  },
  regimeHistory: async (symbol: string, limit = 60): Promise<RegimeSnapshot[]> => {
    const { data } = await http.get<RegimeSnapshot[]>(
      `/v1/market/regime/${encodeURIComponent(symbol)}`,
      { params: { limit } },
    );
    return data;
  },
  activeScalps: async (symbol?: string): Promise<ScalpSetup[]> => {
    const { data } = await http.get<ScalpSetup[]>("/v1/setups/scalps/active", {
      params: symbol ? { symbol } : undefined,
    });
    return data;
  },
  activeSwings: async (symbol?: string): Promise<SwingSetup[]> => {
    const { data } = await http.get<SwingSetup[]>("/v1/setups/swings/active", {
      params: symbol ? { symbol } : undefined,
    });
    return data;
  },
  optionBias: async (symbol: string): Promise<OptionBias> => {
    const { data } = await http.get<OptionBias>(
      `/v1/market/option-bias/${encodeURIComponent(symbol)}`,
    );
    return data;
  },
  optionChain: async (symbol: string, nearStrikes = 12): Promise<OptionChain> => {
    const { data } = await http.get<OptionChain>(
      `/v1/market/option-chain/${encodeURIComponent(symbol)}`,
      { params: { near_strikes: nearStrikes } },
    );
    return data;
  },
  strikeRecommendations: async (
    symbol: string,
    direction?: "LONG" | "SHORT",
    holdDays?: number,
  ): Promise<StrikeRecommendations> => {
    const params: Record<string, string | number> = {};
    if (direction) params.direction = direction;
    if (holdDays != null) params.hold_days = holdDays;
    const { data } = await http.get<StrikeRecommendations>(
      `/v1/market/strike-recommendations/${encodeURIComponent(symbol)}`,
      { params: Object.keys(params).length ? params : undefined },
    );
    return data;
  },
  health: async (): Promise<Health> => {
    const { data } = await http.get<Health>("/v1/admin/health");
    return data;
  },
  tick: async (): Promise<TickResult> => {
    const { data } = await http.post<TickResult>("/v1/admin/tick");
    return data;
  },
  hydrate: async (): Promise<Record<string, number>> => {
    const { data } = await http.post<Record<string, number>>("/v1/admin/hydrate");
    return data;
  },
};
