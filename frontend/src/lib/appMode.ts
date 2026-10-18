import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { http } from "@/api/client";

/**
 * App-wide mode toggle: HISTORICAL (default, dark theme, full historical
 * navigation) vs LIVE (light theme, focused real-time analysis dashboard).
 *
 * State is persisted to localStorage so a refresh stays in the user's chosen
 * mode, AND mirrored to the backend (`/v1/live-analysis/mode`) so the
 * APScheduler `intraday-live-analysis-tick` job knows whether to actually
 * run each cron wake-up.
 *
 * Theme switching: this store toggles the `dark` class on `<html>` whenever
 * the mode changes. Tailwind tokens are routed through CSS custom properties
 * (see `index.css`) so every existing utility (e.g. `bg-bg-surface`)
 * automatically picks the right palette.
 */
export type AppMode = "HISTORICAL" | "LIVE";

interface AppModeState {
  mode: AppMode;
  syncing: boolean;
  syncError: string | null;
  setMode: (next: AppMode) => Promise<void>;
  hydrateFromBackend: () => Promise<void>;
}

const STORAGE_KEY = "app-mode";

function applyThemeClass(mode: AppMode) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (mode === "LIVE") {
    root.classList.remove("dark");
  } else {
    root.classList.add("dark");
  }
}

export const useAppMode = create<AppModeState>()(
  persist(
    (set, get) => ({
      mode: "HISTORICAL",
      syncing: false,
      syncError: null,

      setMode: async (next) => {
        if (get().mode === next) return;
        set({ mode: next, syncing: true, syncError: null });
        applyThemeClass(next);
        try {
          await http.post("/v1/live-analysis/mode", { mode: next });
          set({ syncing: false });
        } catch (err) {
          // Local mode flip stands - we don't want to bounce the UI back -
          // but surface the error so the user knows the backend tick is
          // unaware (e.g. backend down, mode-mismatch warning in UI).
          const message = err instanceof Error ? err.message : "Mode sync failed";
          set({ syncing: false, syncError: message });
        }
      },

      hydrateFromBackend: async () => {
        try {
          const { data } = await http.get<{ mode: AppMode; market_open: boolean }>(
            "/v1/live-analysis/mode",
          );
          if (data.mode && data.mode !== get().mode) {
            // Backend is the source of truth on cold start (e.g. another
            // operator changed mode while this browser was closed).
            set({ mode: data.mode });
            applyThemeClass(data.mode);
          }
        } catch {
          // Silent: a missing backend just means we keep the persisted local
          // value. No UI noise on first paint.
        }
      },
    }),
    {
      name: STORAGE_KEY,
      version: 1,
      migrate: (persistedState, version) => {
        return persistedState as any;
      },
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ mode: state.mode }),
      onRehydrateStorage: () => (state) => {
        if (state) {
          applyThemeClass(state.mode);
        }
      },
    },
  ),
);

/** Imperative entry point used by `index.html` / `main.tsx` before React
 * mounts so we don't see a dark-flash before the persisted light theme
 * applies. */
export function bootstrapInitialTheme(): void {
  if (typeof window === "undefined") return;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      applyThemeClass("HISTORICAL");
      return;
    }
    const parsed = JSON.parse(raw) as { state?: { mode?: AppMode } };
    applyThemeClass(parsed.state?.mode === "LIVE" ? "LIVE" : "HISTORICAL");
  } catch {
    applyThemeClass("HISTORICAL");
  }
}
