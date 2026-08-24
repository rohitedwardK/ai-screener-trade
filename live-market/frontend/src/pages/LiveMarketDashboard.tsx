import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import IndexCardCompact from "../components/IndexCardCompact";

const REFRESH_MS = 30_000;

export default function LiveMarketDashboard() {
  const qc = useQueryClient();
  const dashboardQ = useQuery({
    queryKey: ["dashboard"],
    queryFn: api.dashboard,
    refetchInterval: REFRESH_MS,
  });
  const healthQ = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 60_000,
  });
  const tickMut = useMutation({
    mutationFn: api.tick,
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["health"] });
    },
  });

  if (dashboardQ.isLoading) {
    return <p className="text-sm text-fg-muted">Loading dashboard...</p>;
  }
  if (dashboardQ.error || !dashboardQ.data) {
    return (
      <div className="card p-4 text-sm text-accent-red">
        Failed to load dashboard. Is the Live Market backend running on
        port 8001?
      </div>
    );
  }

  const data = dashboardQ.data;
  const fetched = new Date(data.fetched_at).toLocaleTimeString("en-IN", {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-fg">Live Market</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Intraday regime + scalp / swing setups for the three indices.
            Polls Upstox every 1 minute during NSE hours.
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs text-fg-subtle">
          <span>fetched {fetched}</span>
          {healthQ.data && (
            <>
              <span
                className={`badge ${healthQ.data.upstox_configured && !healthQ.data.upstox_token_dead ? "badge-green" : "badge-red"}`}
              >
                upstox: {healthQ.data.upstox_token_dead ? "dead" : healthQ.data.upstox_configured ? "live" : "missing"}
              </span>
              <span className="badge badge-muted">
                bars {Object.values(healthQ.data.bar_counts).reduce((a, b) => a + b, 0)}
              </span>
            </>
          )}
          <button
            className="btn"
            disabled={tickMut.isPending}
            onClick={() => tickMut.mutate()}
          >
            {tickMut.isPending ? "ticking..." : "manual tick"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {data.indices.map((card) => (
          <IndexCardCompact key={card.symbol} card={card} />
        ))}
      </div>

      <p className="text-xs italic text-fg-subtle">{data.disclaimer}</p>
    </div>
  );
}
