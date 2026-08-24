import { fmt } from "../lib/format";

interface Props {
  label: string;
  spot: { entry: number; stop: number; t1: number; t2: number; invalidation: number };
  option?: {
    strike: number | null;
    type: "CE" | "PE" | null;
    expiry: string | null;
    premium_entry: number | null;
    premium_stop: number | null;
    premium_t1: number | null;
    premium_t2: number | null;
  } | null;
}

function Cell({ k, v, accent }: { k: string; v: string; accent?: "green" | "red" | "amber" | "muted" }) {
  const cls =
    accent === "green"
      ? "text-accent-green"
      : accent === "red"
      ? "text-accent-red"
      : accent === "amber"
      ? "text-accent-amber"
      : "text-fg-muted";
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-fg-subtle">{k}</span>
      <span className={`num text-sm font-medium ${cls}`}>{v}</span>
    </div>
  );
}

export default function PlanRow({ label, spot, option }: Props) {
  const optionLabel = option && option.strike != null && option.type
    ? `${option.strike} ${option.type} ${option.expiry ? new Date(option.expiry).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : ""}`
    : "spot only";
  return (
    <div className="rounded-lg border border-border bg-bg-elevated p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
          {label}
        </span>
        <span className="badge badge-muted">{optionLabel}</span>
      </div>
      <div className="grid grid-cols-5 gap-3">
        <Cell k="Entry" v={fmt.num(spot.entry)} />
        <Cell k="Stop" v={fmt.num(spot.stop)} accent="red" />
        <Cell k="T1" v={fmt.num(spot.t1)} accent="amber" />
        <Cell k="T2" v={fmt.num(spot.t2)} accent="green" />
        <Cell k="Invalidation" v={fmt.num(spot.invalidation)} accent="red" />
      </div>
      {option && option.premium_entry != null && (
        <div className="mt-3 grid grid-cols-4 gap-3 border-t border-border pt-2">
          <Cell k="Prem Entry" v={fmt.num(option.premium_entry)} />
          <Cell k="Prem Stop" v={fmt.num(option.premium_stop)} accent="red" />
          <Cell k="Prem T1" v={fmt.num(option.premium_t1)} accent="amber" />
          <Cell k="Prem T2" v={fmt.num(option.premium_t2)} accent="green" />
        </div>
      )}
    </div>
  );
}
