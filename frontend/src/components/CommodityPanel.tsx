import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { commoditiesApi } from "@/api/client";
import { CommodityCard } from "./CommodityCard";

export function CommodityPanel() {
	const { data, isLoading, isError, refetch, isFetching } = useQuery({
		queryKey: ["commodities-dashboard"],
		queryFn: () => commoditiesApi.dashboard(),
		refetchInterval: 60_000,
	});

	if (isLoading) {
		return <div className="card p-4 text-fg-muted">Loading commodities…</div>;
	}

	if (isError || !data) {
		return (
			<div className="card p-4 text-fg-muted flex items-center justify-between">
				<div>No commodity data available.</div>
				<button type="button" className="btn" onClick={() => void refetch()}>
					Refresh
				</button>
			</div>
		);
	}

	return (
		<div className="space-y-4">
			<div className="card p-4 flex items-center justify-between">
				<div>
					<h2 className="font-semibold">Commodities</h2>
					<p className="text-xs text-fg-muted mt-0.5">
						{data.quote_source} · {data.market_open ? "Market open" : "Market closed"}
					</p>
				</div>
				<button
					type="button"
					className="btn"
					onClick={() => void refetch()}
					disabled={isFetching}
				>
					<Loader2 className={`size-4 ${isFetching ? "animate-spin" : ""}`} />
				</button>
			</div>

			<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
				{data.items.map((it) => (
					<CommodityCard key={it.symbol} item={it} />
				))}
			</div>

			<p className="text-[11px] text-fg-subtle">{data.disclaimer}</p>
		</div>
	);
}

