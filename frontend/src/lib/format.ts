export const fmt = {
  inr: (n: number | null | undefined, digits = 2) =>
    n == null || Number.isNaN(n)
      ? "—"
      : new Intl.NumberFormat("en-IN", {
          maximumFractionDigits: digits,
          minimumFractionDigits: digits,
        }).format(n),
  num: (n: number | null | undefined, digits = 2) =>
    n == null || Number.isNaN(n)
      ? "—"
      : new Intl.NumberFormat("en-IN", {
          maximumFractionDigits: digits,
          minimumFractionDigits: digits,
        }).format(n),
  pct: (n: number | null | undefined, digits = 1) =>
    n == null || Number.isNaN(n) ? "—" : `${n >= 0 ? "+" : ""}${n.toFixed(digits)}%`,
  pctRaw: (n: number | null | undefined, digits = 1) =>
    n == null || Number.isNaN(n) ? "—" : `${n.toFixed(digits)}%`,
  int: (n: number | null | undefined) =>
    n == null || Number.isNaN(n) ? "—" : Math.round(n).toLocaleString("en-IN"),
};

export const symbolDisplay = (s: string) => s.replace(/\.NS$/, "");

export function classNames(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

export function regimeTone(regime: string): "green" | "red" | "amber" | "blue" | "muted" {
  switch (regime) {
    case "STRONG_UPTREND":
    case "UPTREND":
      return "green";
    case "STRONG_DOWNTREND":
    case "DOWNTREND":
      return "red";
    case "VOLATILE":
      return "amber";
    case "RANGE":
      return "blue";
    default:
      return "muted";
  }
}

export function scoreTone(score: number): "green" | "amber" | "red" | "muted" {
  if (score >= 70) return "green";
  if (score >= 50) return "amber";
  if (score > 0) return "red";
  return "muted";
}
