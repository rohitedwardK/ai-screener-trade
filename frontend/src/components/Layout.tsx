import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, liveVerificationApi, notificationsApi } from "@/api/client";
import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Loader2,
  RefreshCw,
  Search,
  Activity,
  History,
  Bell,
  ChevronDown,
  Menu,
  X,
} from "lucide-react";
import { useAppMode, type AppMode } from "@/lib/appMode";
import { useLiveVerificationPoller } from "@/lib/useLiveVerificationPoller";
import type { NotificationItem } from "@/api/types";
import { formatDateTimeIST } from "@/lib/format";
import { playNotificationSound, unlockNotificationSound } from "@/lib/notificationSound";

const NOTIFICATION_POPUP_MS = 8_000;

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
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [notificationPopups, setNotificationPopups] = useState<NotificationItem[]>([]);
  const knownNotificationIds = useRef<Set<number> | null>(null);
  const { data: notifications = [], isFetched: notificationsFetched } = useQuery({
    queryKey: ["notifications"], queryFn: notificationsApi.list,
    refetchInterval: 60_000, refetchIntervalInBackground: true,
  });
  const unreadCount = notifications.filter((item) => item.status === "UNREAD").length;

  useEffect(() => {
    if (!notificationsFetched) return;

    if (knownNotificationIds.current === null) {
      knownNotificationIds.current = new Set(notifications.map((item) => item.id));
      return;
    }

    const newItems = notifications.filter(
      (item) => item.status === "UNREAD" && !knownNotificationIds.current?.has(item.id),
    );
    notifications.forEach((item) => knownNotificationIds.current?.add(item.id));
    if (newItems.length > 0) {
      setNotificationPopups((current) => [
        ...newItems,
        ...current.filter((item) => !newItems.some((newItem) => newItem.id === item.id)),
      ].slice(0, 3));
      const highest = newItems.some((item) => item.severity === "CRITICAL") ? "CRITICAL" : "INFO";
      playNotificationSound(highest);
    }
  }, [notifications, notificationsFetched]);

  useEffect(() => {
    const unlock = () => unlockNotificationSound();
    window.addEventListener("pointerdown", unlock, { once: true });
    window.addEventListener("keydown", unlock, { once: true });
    return () => {
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
  }, []);

  useEffect(() => {
    if (notificationPopups.length === 0) return;
    const timer = window.setTimeout(
      () => setNotificationPopups((current) => current.slice(0, -1)),
      NOTIFICATION_POPUP_MS,
    );
    return () => window.clearTimeout(timer);
  }, [notificationPopups]);

  const dismissNotificationPopup = (id: number) => {
    setNotificationPopups((current) => current.filter((item) => item.id !== id));
  };

  const openNotification = async (item: NotificationItem) => {
    dismissNotificationPopup(item.id);
    if (item.status === "UNREAD") await notificationsApi.markRead(item.id);
    void qc.invalidateQueries({ queryKey: ["notifications"] });
    if (item.route) navigate(item.route);
  };

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

          <NavigationDropdown mode={mode} />

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
            <div className="relative">
              <button type="button" className="btn relative p-2.5" aria-label="Notifications" onClick={() => setNotificationsOpen((value) => !value)}>
                <Bell className="size-4" />
                {unreadCount > 0 && <span className="absolute -right-1 -top-1 rounded-full bg-accent-red px-1 text-[10px] text-white">{unreadCount}</span>}
              </button>
              {notificationsOpen && (
                <div className="absolute right-0 top-11 z-40 w-96 max-h-96 overflow-auto rounded-xl border border-border bg-bg-surface shadow-2xl">
                  <div className="border-b border-border px-4 py-3 text-sm font-medium">Monitor alerts</div>
                  {notifications.length === 0 ? <p className="p-4 text-xs text-fg-muted">No monitored opportunities yet.</p> : notifications.map((item) => (
                    <button key={item.id} type="button" className="block w-full border-b border-border p-3 text-left hover:bg-bg-elevated" onClick={() => void openNotification(item)}>
                      <div className="flex items-center gap-2 text-sm font-medium"><span className={`size-2 rounded-full ${item.severity === "CRITICAL" ? "bg-accent-red" : "bg-accent-amber"}`} />{item.title}</div>
                      <p className="mt-1 text-xs text-fg-muted">{item.message}</p>
                      <p className="mt-1 text-[10px] text-fg-subtle">{formatDateTimeIST(item.created_at)} IST</p>
                    </button>
                  ))}
                </div>
              )}
            </div>
            {mode === "HISTORICAL" && (
              <button
                type="button"
                className="btn"
                onClick={() => refreshMut.mutate()}
                disabled={refreshMut.isPending}
                title="Refresh data (Nifty 50 + gold/silver from Yahoo)"
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

      <div
        className="pointer-events-none fixed right-6 top-20 z-50 flex w-96 max-w-[calc(100vw-3rem)] flex-col gap-3"
        aria-live="polite"
        aria-label="New notifications"
      >
        {notificationPopups.map((item) => (
          <div
            key={item.id}
            className={`pointer-events-auto overflow-hidden rounded-xl border bg-bg-surface shadow-2xl ${
              item.severity === "CRITICAL" ? "border-accent-red/50" : "border-accent-amber/50"
            }`}
            role="status"
          >
            <div className="flex items-start gap-3 p-4">
              <button
                type="button"
                className="min-w-0 flex-1 text-left"
                onClick={() => void openNotification(item)}
              >
                <span className="flex items-center gap-2 text-sm font-semibold text-fg">
                  <span className={`size-2 shrink-0 rounded-full ${item.severity === "CRITICAL" ? "bg-accent-red" : "bg-accent-amber"}`} />
                  {item.title}
                </span>
                <span className="mt-1 block text-xs leading-5 text-fg-muted">{item.message}</span>
                <span className="mt-2 block text-[10px] text-fg-subtle">
                  {formatDateTimeIST(item.created_at)} IST
                </span>
              </button>
              <button
                type="button"
                className="rounded-md p-1 text-fg-subtle hover:bg-bg-elevated hover:text-fg"
                aria-label={`Dismiss ${item.title}`}
                onClick={() => dismissNotificationPopup(item.id)}
              >
                <X className="size-4" />
              </button>
            </div>
            <div className={`h-0.5 ${item.severity === "CRITICAL" ? "bg-accent-red" : "bg-accent-amber"}`} />
          </div>
        ))}
      </div>

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

const HISTORICAL_NAV_ITEMS = [
  { to: "/", label: "Dashboard" },
  { to: "/screener", label: "Screener" },
  { to: "/trades", label: "Trades" },
  { to: "/indices", label: "Indices" },
  { to: "/method-analysis", label: "Method Analysis" },
  { to: "/agents", label: "Agents" },
];

const LIVE_NAV_ITEMS = [
  { to: "/live", label: "Live Dashboard" },
  { to: "/indices", label: "Indices" },
  { to: "/method-analysis", label: "Method Analysis" },
  { to: "/agents", label: "Agents" },
];

function NavigationDropdown({ mode }: { mode: AppMode }) {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const items = mode === "LIVE" ? LIVE_NAV_ITEMS : HISTORICAL_NAV_ITEMS;
  const activeItem = items.find(({ to }) =>
    to === "/" ? location.pathname === "/" : location.pathname.startsWith(to),
  );

  useEffect(() => {
    if (!open) return;

    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };

    document.addEventListener("mousedown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <nav ref={menuRef} className="relative text-sm" aria-label="Primary navigation">
      <button
        type="button"
        className="btn min-w-40 justify-between"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="flex items-center gap-2">
          <Menu className="size-4" />
          {activeItem?.label ?? "Navigate"}
        </span>
        <ChevronDown className={`size-4 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute left-0 top-11 z-40 min-w-52 overflow-hidden rounded-xl border border-border bg-bg-surface p-1.5 shadow-2xl"
        >
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              role="menuitem"
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                `block rounded-md px-3 py-2 ${
                  isActive
                    ? "bg-bg-elevated text-fg"
                    : "text-fg-muted hover:bg-bg-elevated hover:text-fg"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      )}
    </nav>
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
