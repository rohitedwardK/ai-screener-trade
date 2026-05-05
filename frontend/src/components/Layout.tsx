import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useState } from "react";
import { AlertTriangle, Loader2, RefreshCw, Search } from "lucide-react";

export function Layout() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [symbolQuery, setSymbolQuery] = useState("");

  const refreshMut = useMutation({
    mutationFn: () => api.refresh(),
    onSuccess: () => {
      qc.invalidateQueries();
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
            <span className="ml-2 text-xs font-normal text-fg-muted">Nifty 50</span>
          </NavLink>

          <nav className="flex items-center gap-1 text-sm">
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                `px-3 py-1.5 rounded-md ${
                  isActive
                    ? "bg-bg-elevated text-fg"
                    : "text-fg-muted hover:text-fg hover:bg-bg-elevated"
                }`
              }
            >
              Dashboard
            </NavLink>
            <NavLink
              to="/screener"
              className={({ isActive }) =>
                `px-3 py-1.5 rounded-md ${
                  isActive
                    ? "bg-bg-elevated text-fg"
                    : "text-fg-muted hover:text-fg hover:bg-bg-elevated"
                }`
              }
            >
              Screener
            </NavLink>
            <NavLink
              to="/paper-trading"
              className={({ isActive }) =>
                `px-3 py-1.5 rounded-md ${
                  isActive
                    ? "bg-bg-elevated text-fg"
                    : "text-fg-muted hover:text-fg hover:bg-bg-elevated"
                }`
              }
            >
              Paper Trading
            </NavLink>
            <NavLink
              to="/indices"
              className={({ isActive }) =>
                `px-3 py-1.5 rounded-md ${
                  isActive
                    ? "bg-bg-elevated text-fg"
                    : "text-fg-muted hover:text-fg hover:bg-bg-elevated"
                }`
              }
            >
              Indices
            </NavLink>
            <NavLink
              to="/paper-index-trading"
              className={({ isActive }) =>
                `px-3 py-1.5 rounded-md ${
                  isActive
                    ? "bg-bg-elevated text-fg"
                    : "text-fg-muted hover:text-fg hover:bg-bg-elevated"
                }`
              }
            >
              Index Bot
            </NavLink>
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
          </form>
        </div>
        {refreshMut.isPending && (
          <div className="border-t border-border bg-accent-blue/5 px-6 py-1.5 text-xs text-accent-blue">
            Refreshing data — fetching 50 symbols, computing indicators and signals…
          </div>
        )}
        {refreshMut.isError && (
          <div className="border-t border-border bg-accent-red/5 px-6 py-1.5 text-xs text-accent-red">
            Refresh failed. Check the backend logs.
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
