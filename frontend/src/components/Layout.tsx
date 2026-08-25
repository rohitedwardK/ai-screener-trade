import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, liveVerificationApi } from "@/api/client";
import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Loader2,
  RefreshCw,
  Search,
  Activity,
  History,
} from "lucide-react";
import { useAppMode, type AppMode } from "@/lib/appMode";
import { useLiveVerificationPoller } from "@/lib/useLiveVerificationPoller";

/**
 * Top-level chrome: header, mode toggle, nav, search, footer.
 *
 * Mode toggle: switching to LIVE flips `<html class="dark">` off (light
 * palette) and tells the backend scheduler to start running the
 * `intraday-live-analysis-tick` job. Switching back restores the dark
 * theme + full historical navigation.
 */
export function Layout() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [symbolQuery, setSymbolQuery] = useState("");

  const mode = useAppMode((s) => s.mode);
  const setMode = useAppMode((s) => s.setMode);
  const syncing = useAppMode((s) => s.syncing);
  const syncError = useAppMode((s) => s.syncError);
  const hydrate = useAppMode((s) => s.hydrateFromBackend);

  // Reconcile local persisted mode with whatever the backend believes - if
  // another operator already flipped it, we follow.
  useEffect(() => {
    void hydrate();
  }, [hydrate]);

  // Refresh chains two stages:
  //   1. EOD pipeline (`api.refresh`) — incremental yfinance pull, no-op
  //      once today's daily bar is already cached.
  //   2. Live signal verification — projects an intraday today-bar from the
  //      latest LTP and reconciles every persisted signal so the UI shows
  //      CONFIRMED / WEAKENING / INVALIDATED / STRENGTHENED status.
  // Failures in stage 2 are logged but don't roll back stage 1; the EOD
  // baseline is the source of truth.
  const [refreshStage, setRefreshStage] = useState<
    "idle" | "eod" | "live" | "done"
  >("idle");
  const refreshMut = useMutation({
    mutationFn: async () => {
      setRefreshStage("eod");
      const eod = await api.refresh();
      setRefreshStage("live");
      try {
        await liveVerificationApi.run();
      } catch (err) {
        console.warn("Live verification step failed", err);
      }
      setRefreshStage("done");
      return eod;
    },
    onSuccess: () => {
      qc.invalidateQueries();
      setTimeout(() => setRefreshStage("idle"), 1500);
    },
    onError: () => {
      setRefreshStage("idle");
    },
  });

  // Auto-poll the live verifier every 15 minutes during NSE hours so the
  // dashboard "live status" pills stay in sync without a manual click.
  useLiveVerificationPoller({
    enabled: mode === "HISTORICAL",
    intervalMs: 15 * 60 * 1000,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["screener"] });
      qc.invalidateQueries({ queryKey: ["categories"] });
      qc.invalidateQueries({ queryKey: ["live-verification-summary"] });
    },
  });

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const q = symbolQuery.trim().toUpperCase();
    if (!q) return;
    const sym = q.endsWith(".NS") ? q : `${q}.NS`;
    navigate(`/stock/${sym}`);
    setSymbolQuery("");
  };

  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-30 border-b border-border bg-bg/80 backdrop-blur">
        <div className="mx-auto max-w-[1400px] px-6 h-14 flex items-center gap-6">
          <NavLink to="/" className="font-semibold tracking-tight text-fg">
            <span className="text-accent-blue">AI</span> Stock Screener
            <span className="ml-2 text-xs font-normal text-fg-muted">
              {mode === "LIVE" ? "Live · Nifty 50" : "Nifty 50"}
            </span>
          </NavLink>

          <ModeToggle mode={mode} onChange={setMode} disabled={syncing} />

          <nav className="flex items-center gap-1 text-sm">
            {mode === "LIVE" ? (
              <>
                <NavLinkPill to="/live" label="Live Dashboard" />
                <NavLinkPill to="/indices" label="Indices" />
                <NavLinkPill to="/method-analysis" label="Method Analysis" />
                <NavLinkPill to="/agents" label="Agents" />
              </>
            ) : (
              <>
                <NavLinkPill to="/" end label="Dashboard" />
                <NavLinkPill to="/screener" label="Screener" />
                <NavLinkPill to="/trades" label="Trades" />
                <NavLinkPill to="/indices" label="Indices" />
                <NavLinkPill to="/method-analysis" label="Method Analysis" />
                <NavLinkPill to="/agents" label="Agents" />
              </>
            )}
          </nav>

          <form onSubmit={onSearch} className="ml-auto flex items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 size-4 text-fg-subtle" />
              <input
                value={symbolQuery}
                onChange={(e) => setSymbolQuery(e.target.value)}
                placeholder="Symbol e.g. RELIANCE"
                className="input pl-8 w-56"
              />
            </div>
            {mode === "HISTORICAL" && (
              <button
                type="button"
                className="btn"
                onClick={() => refreshMut.mutate()}
                disabled={refreshMut.isPending}
                title="Refresh data (fetches all Nifty 50 from Yahoo)"
              >
                {refreshMut.isPending ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <RefreshCw className="size-4" />
                )}
                <span>Refresh</span>
              </button>
            )}
          </form>
        </div>
        {refreshMut.isPending && (
          <div className="border-t border-border bg-accent-blue/5 px-6 py-1.5 text-xs text-accent-blue">
            {refreshStage === "live"
              ? "Cross-checking live prices against persisted signals…"
              : "Refreshing data — fetching 50 symbols, computing indicators and signals…"}
          </div>
        )}
        {refreshMut.isError && (
          <div className="border-t border-border bg-accent-red/5 px-6 py-1.5 text-xs text-accent-red">
            Refresh failed. Check the backend logs.
          </div>
        )}
        {syncError && (
          <div className="border-t border-border bg-accent-amber/5 px-6 py-1.5 text-xs text-accent-amber">
            Mode toggle could not reach the backend ({syncError}). The UI is in {mode}{" "}
            mode but the scheduler may not be in sync.
          </div>
        )}
      </header>

      <main className="flex-1 mx-auto w-full max-w-[1400px] px-6 py-6">
        <Outlet />
      </main>

      <footer className="border-t border-border bg-bg-surface">
        <div className="mx-auto max-w-[1400px] px-6 py-3 flex items-center gap-3 text-xs text-fg-muted">
          <AlertTriangle className="size-4 text-accent-amber" />
          <span>
            Research and decision-support only. Not financial advice. Always validate
            against your own plan, confirm with price action, and respect the
            invalidation level.
          </span>
        </div>
      </footer>
    </div>
  );
}

function NavLinkPill({
  to,
  label,
  end,
}: {
  to: string;
  label: string;
  end?: boolean;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `px-3 py-1.5 rounded-md ${
          isActive
            ? "bg-bg-elevated text-fg"
            : "text-fg-muted hover:text-fg hover:bg-bg-elevated"
        }`
      }
    >
      {label}
    </NavLink>
  );
}

function ModeToggle({
  mode,
  onChange,
  disabled,
}: {
  mode: AppMode;
  onChange: (next: AppMode) => Promise<void>;
  disabled: boolean;
}) {
  return (
    <div
      className="inline-flex rounded-md border border-border bg-bg-surface p-0.5 text-xs"
      role="group"
      aria-label="Application mode"
    >
      <ModeButton
        active={mode === "HISTORICAL"}
        disabled={disabled}
        onClick={() => onChange("HISTORICAL")}
        icon={<History className="size-3.5" />}
        label="Historical"
      />
      <ModeButton
        active={mode === "LIVE"}
        disabled={disabled}
        onClick={() => onChange("LIVE")}
        icon={<Activity className="size-3.5" />}
        label="Live"
        variant="live"
      />
    </div>
  );
}

function ModeButton({
  active,
  disabled,
  onClick,
  icon,
  label,
  variant,
}: {
  active: boolean;
  disabled: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  variant?: "live";
}) {
  const activeClasses =
    variant === "live"
      ? "bg-accent-green/15 text-accent-green border-accent-green/30"
      : "bg-bg-elevated text-fg border-border-strong";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-[4px] border transition ${
        active
          ? activeClasses
          : "border-transparent text-fg-muted hover:text-fg hover:bg-bg-elevated"
      } disabled:opacity-50`}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}
