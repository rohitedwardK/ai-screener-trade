// Number formatting helpers - mirror the parent app's lib/format so a
// future merge stays mechanical.

export const fmt = {
  num: (n: number | null | undefined, digits = 2) =>
    n == null || Number.isNaN(n)
      ? "-"
      : new Intl.NumberFormat("en-IN", {
          maximumFractionDigits: digits,
          minimumFractionDigits: digits,
        }).format(n),
  pct: (n: number | null | undefined, digits = 2) =>
    n == null || Number.isNaN(n)
      ? "-"
      : `${n >= 0 ? "+" : ""}${n.toFixed(digits)}%`,
  pctRaw: (n: number | null | undefined, digits = 2) =>
    n == null || Number.isNaN(n) ? "-" : `${n.toFixed(digits)}%`,
  int: (n: number | null | undefined) =>
    n == null || Number.isNaN(n) ? "-" : Math.round(n).toLocaleString("en-IN"),
};

export function symbolDisplay(symbol: string): string {
  // Convert ^NSEI -> NIFTY (display); fall through for unknown.
  switch (symbol) {
    case "^NSEI": return "NIFTY 50";
    case "^NSEBANK": return "BANK NIFTY";
    case "^BSESN": return "SENSEX";
    default: return symbol;
  }
}

export function classNames(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export function relativeAge(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return "never";
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}
