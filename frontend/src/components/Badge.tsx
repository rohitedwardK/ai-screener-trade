import { classNames } from "@/lib/format";
import type { ReactNode } from "react";

type Tone = "green" | "red" | "amber" | "blue" | "violet" | "cyan" | "muted";

const toneClass: Record<Tone, string> = {
  green: "badge-green",
  red: "badge-red",
  amber: "badge-amber",
  blue: "badge-blue",
  violet: "badge-violet",
  cyan: "badge-cyan",
  muted: "badge-muted",
};

export function Badge({
  children,
  tone = "muted",
  className,
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <span className={classNames("badge", toneClass[tone], className)}>
      {children}
    </span>
  );
}
