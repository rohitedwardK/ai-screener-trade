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

const IST_TZ = "Asia/Kolkata";

/** Full date + time rendered in IST, regardless of the viewer's machine tz. */
export function formatDateTimeIST(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "—";
  return new Date(ts).toLocaleString("en-IN", { timeZone: IST_TZ });
}

/** Clock time rendered in IST. Pass withSeconds for HH:MM:SS. */
export function formatTimeIST(
  iso: string | null | undefined,
  withSeconds = false,
): string {
  if (!iso) return "—";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "—";
  return new Date(ts).toLocaleTimeString("en-IN", {
    timeZone: IST_TZ,
    hour: "2-digit",
    minute: "2-digit",
    ...(withSeconds ? { second: "2-digit" } : {}),
  });
}

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

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "never";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "never";
  const seconds = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
