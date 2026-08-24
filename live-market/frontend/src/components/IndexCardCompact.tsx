import { Link } from "react-router-dom";
import type { IndexCard } from "../api/types";
import { fmt, relativeAge, symbolDisplay } from "../lib/format";
import RegimeBanner from "./RegimeBanner";

export default function IndexCardCompact({ card }: { card: IndexCard }) {
  const changePct =
    card.spot != null && card.range_support != null && card.range_resistance != null
      ? ((card.spot - (card.range_support + card.range_resistance) / 2) / card.spot) * 100
      : null;

  return (
    <Link
      to={`/index/${encodeURIComponent(card.symbol)}`}
      className="card flex flex-col gap-3 p-4 transition hover:border-border-strong hover:shadow-md"
    >
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs uppercase tracking-wide text-fg-subtle">
            {card.code}
          </div>
          <div className="text-base font-semibold text-fg">
            {symbolDisplay(card.symbol)}
          </div>
        </div>
        <RegimeBanner regime={card.regime} />
      </div>

      <div className="flex items-baseline gap-3">
        <span className="num text-3xl font-bold text-fg">
          {fmt.num(card.spot, 2)}
        </span>
        {changePct != null && (
          <span
            className={`num text-sm font-medium ${
              changePct >= 0 ? "text-accent-green" : "text-accent-red"
            }`}
          >
            {fmt.pct(changePct, 2)} vs mid
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <Field label="VWAP" value={fmt.num(card.vwap)} />
        <Field label="Daily ADX" value={fmt.num(card.daily_adx, 1)} />
        <Field label="Range" value={card.range_support && card.range_resistance ? `${fmt.num(card.range_support)} - ${fmt.num(card.range_resistance)}` : "-"} />
        <Field label="Last bar" value={relativeAge(card.last_bar_age_seconds)} />
      </div>

      <div className="flex items-center gap-2 border-t border-border pt-3 text-xs">
        <span className="badge badge-amber">{card.active_scalps} scalp</span>
        <span className="badge badge-blue">{card.active_swings} swing</span>
        {!card.has_option_chain && (
          <span className="badge badge-muted">spot-only (no chain)</span>
        )}
      </div>
    </Link>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between text-fg-muted">
      <span>{label}</span>
      <span className="num text-fg">{value}</span>
    </div>
  );
}
