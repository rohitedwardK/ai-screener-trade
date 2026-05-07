import { useEffect, useRef } from "react";
import { liveVerificationApi } from "@/api/client";

/**
 * Auto-poll the backend live signal verifier on a fixed cadence during
 * NSE regular trading hours.
 *
 * The hook stays out of the way unless the host page wants it on:
 *   - `enabled` defaults to false so accidental imports don't fire requests.
 *   - We also gate on a JS-side `isMarketOpen()` (Mon-Fri 09:15-15:30 IST)
 *     and on the tab being visible, mirroring the backend cron's own
 *     short-circuit. Together this means the only network round-trips
 *     happen when the user is actually looking at a relevant page during
 *     market hours.
 *
 * Backend writes are idempotent (one row per signal_id, latest wins) so
 * occasional duplicate triggers — e.g. switching tabs at exactly the
 * 15-minute boundary — are safe.
 */
const IST_OFFSET_MIN = 5 * 60 + 30;
const MARKET_OPEN_HHMM = 9 * 60 + 15;
const MARKET_CLOSE_HHMM = 15 * 60 + 30;

export function isMarketOpen(at: Date = new Date()): boolean {
  const utcMin = at.getUTCHours() * 60 + at.getUTCMinutes();
  const istMin = (utcMin + IST_OFFSET_MIN) % (24 * 60);
  const dayShift = utcMin + IST_OFFSET_MIN >= 24 * 60 ? 1 : 0;
  const istWeekday = (at.getUTCDay() + dayShift) % 7;
  if (istWeekday === 0 || istWeekday === 6) return false;
  return istMin >= MARKET_OPEN_HHMM && istMin <= MARKET_CLOSE_HHMM;
}

interface PollerOptions {
  enabled: boolean;
  intervalMs?: number;
  onSuccess?: () => void;
}

export function useLiveVerificationPoller({
  enabled,
  intervalMs = 15 * 60 * 1000,
  onSuccess,
}: PollerOptions): void {
  const onSuccessRef = useRef(onSuccess);
  onSuccessRef.current = onSuccess;

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;

    const tryFire = async () => {
      if (cancelled) return;
      if (typeof document !== "undefined" && document.visibilityState !== "visible") return;
      if (!isMarketOpen()) return;
      try {
        await liveVerificationApi.run(true);
        onSuccessRef.current?.();
      } catch (err) {
        console.warn("live verification poller request failed", err);
      }
    };

    const id = setInterval(() => {
      void tryFire();
    }, intervalMs);

    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [enabled, intervalMs]);
}
