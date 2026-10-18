let audioCtx: AudioContext | null = null;
let unlocked = false;

function context(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor = window.AudioContext || (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  if (!audioCtx) audioCtx = new Ctor();
  return audioCtx;
}

function tone(ctx: AudioContext, frequency: number, start: number, duration: number, gain = 0.12) {
  const osc = ctx.createOscillator();
  const amp = ctx.createGain();
  osc.type = "sine";
  osc.frequency.setValueAtTime(frequency, start);
  amp.gain.setValueAtTime(0.0001, start);
  amp.gain.exponentialRampToValueAtTime(gain, start + 0.02);
  amp.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  osc.connect(amp);
  amp.connect(ctx.destination);
  osc.start(start);
  osc.stop(start + duration + 0.02);
}

/** Browsers block AudioContext until a user gesture; call this from a click/keydown. */
export function unlockNotificationSound() {
  const ctx = context();
  if (!ctx) return;
  if (ctx.state === "suspended") void ctx.resume();
  unlocked = true;
}

export function playNotificationSound(severity = "INFO") {
  const ctx = context();
  if (!ctx) return;
  if (ctx.state === "suspended") void ctx.resume();
  if (!unlocked && ctx.state !== "running") return;

  const now = ctx.currentTime;
  const critical = severity === "CRITICAL";
  if (critical) {
    tone(ctx, 784, now, 0.1, 0.14);
    tone(ctx, 1046, now + 0.11, 0.16, 0.16);
  } else {
    tone(ctx, 659, now, 0.12, 0.1);
    tone(ctx, 880, now + 0.13, 0.18, 0.12);
  }
}
