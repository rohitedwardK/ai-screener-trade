import { REGIME_TONE } from "../api/types";

const REGIME_LABEL: Record<string, string> = {
  TRENDING_UP: "TRENDING UP",
  TRENDING_DOWN: "TRENDING DOWN",
  RANGE_BOUND: "RANGE-BOUND",
  CHOPPY: "CHOPPY",
};

const TONE_BG: Record<string, string> = {
  green: "bg-accent-green/15 border-accent-green/40 text-accent-green",
  red: "bg-accent-red/15 border-accent-red/40 text-accent-red",
  blue: "bg-accent-blue/15 border-accent-blue/40 text-accent-blue",
  amber: "bg-accent-amber/15 border-accent-amber/40 text-accent-amber",
  muted: "bg-bg-elevated border-border text-fg-muted",
};

interface Props {
  regime: string;
  reasons?: string[];
  size?: "sm" | "lg";
}

export default function RegimeBanner({ regime, reasons = [], size = "sm" }: Props) {
  const tone = REGIME_TONE[regime] ?? "muted";
  const label = REGIME_LABEL[regime] ?? regime;
  const bgCls = TONE_BG[tone];
  const padCls = size === "lg" ? "px-4 py-3 text-base" : "px-2.5 py-1 text-xs";
  return (
    <div
      className={`inline-flex flex-col rounded-md border font-semibold tracking-wide ${bgCls} ${padCls}`}
    >
      <span>{label}</span>
      {size === "lg" && reasons.length > 0 && (
        <ul className="mt-1 list-disc pl-4 text-xs font-normal opacity-80">
          {reasons.slice(0, 3).map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
