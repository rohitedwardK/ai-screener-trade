import { LineChart, Line, ResponsiveContainer, YAxis } from "recharts";
import { fmt, symbolDisplay } from "@/lib/format";
import type { LiveObservation } from "@/api/types";

interface Props {
  observation: LiveObservation;
  pollIntervalMin: number;
  observationSamples: number;
}

export function ObservationCard({
  observation,
  pollIntervalMin,
  observationSamples,
}: Props) {
  const samples = observation.samples ?? [];
  const points = samples.map((s, i) => ({ idx: i, price: s.price }));
  const filled = observation.sample_count;
  const remaining = Math.max(observationSamples - filled, 0);

  const last = samples.at(-1)?.price ?? null;
  const first = samples.at(0)?.price ?? null;
  const dPct = first && last && first > 0 ? ((last - first) / first) * 100 : null;
  const tone =
    dPct == null ? "text-fg-muted" : dPct >= 0 ? "text-accent-green" : "text-accent-red";

  const isCooldown = observation.status === "COOLDOWN";

  return (
    <div className="card p-3">
      <div className="flex items-center justify-between mb-2">
        <div>
          <div className="text-sm font-semibold text-fg">
            {symbolDisplay(observation.symbol)}
          </div>
          <div className="text-[10px] uppercase tracking-wider text-fg-subtle">
            {isCooldown ? "Cooldown" : "Observing"}
          </div>
        </div>
        <div className="text-right text-xs">
          <div className={`num font-medium ${tone}`}>{fmt.pct(dPct, 2)}</div>
          <div className="text-fg-muted num">{fmt.num(last, 2)}</div>
        </div>
      </div>

      <div className="h-12 -mx-1">
        {points.length >= 2 ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points}>
              <YAxis hide domain={["dataMin", "dataMax"]} />
              <Line
                type="monotone"
                dataKey="price"
                stroke="currentColor"
                className={tone}
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-full flex items-center justify-center text-xs text-fg-subtle">
            Awaiting next sample…
          </div>
        )}
      </div>

      <div className="mt-2 flex items-center justify-between text-[11px] text-fg-muted">
        <SampleDots filled={filled} total={observationSamples} />
        {!isCooldown && remaining > 0 && (
          <span className="num">
            {remaining} sample{remaining === 1 ? "" : "s"} ·{" "}
            {remaining * pollIntervalMin} min
          </span>
        )}
      </div>
    </div>
  );
}

function SampleDots({ filled, total }: { filled: number; total: number }) {
  return (
    <div className="flex items-center gap-1">
      {Array.from({ length: total }).map((_, i) => (
        <span
          key={i}
          className={`size-1.5 rounded-full ${
            i < filled ? "bg-accent-blue" : "bg-border-strong"
          }`}
        />
      ))}
    </div>
  );
}
