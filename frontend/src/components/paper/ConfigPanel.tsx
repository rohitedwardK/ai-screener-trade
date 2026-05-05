import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { paperApi } from "@/api/client";
import type { PaperBotConfig, PaperBotConfigUpdate } from "@/api/types";
import { Loader2, Save, X } from "lucide-react";

const POLICIES = ["conservative", "optimistic", "ohlc_approx"] as const;

export function ConfigPanel({
  config,
  onClose,
}: {
  config: PaperBotConfig;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState<PaperBotConfigUpdate>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setForm({});
  }, [config.id]);

  const update = useMutation({
    mutationFn: (patch: PaperBotConfigUpdate) => paperApi.updateConfig(patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["paper-config"] });
      qc.invalidateQueries({ queryKey: ["paper-status"] });
      onClose();
    },
    onError: (e: any) => {
      setError(e?.response?.data?.detail ?? e?.message ?? "Update failed");
    },
  });

  const onChange = <K extends keyof PaperBotConfigUpdate>(
    k: K,
    v: PaperBotConfigUpdate[K]
  ) => setForm((p) => ({ ...p, [k]: v }));

  const merged = { ...config, ...form };

  const save = () => {
    setError(null);
    if (Object.keys(form).length === 0) {
      onClose();
      return;
    }
    update.mutate(form);
  };

  return (
    <div className="fixed inset-0 z-50 bg-bg/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="card max-w-lg w-full">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div>
            <h3 className="font-semibold text-sm">Paper Trading Config</h3>
            <p className="text-xs text-fg-muted">
              Single config row. Changes apply immediately.
            </p>
          </div>
          <button onClick={onClose} className="text-fg-muted hover:text-fg">
            <X className="size-4" />
          </button>
        </div>
        <div className="p-4 grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
          <Field
            label="Virtual capital (₹)"
            value={merged.virtual_capital}
            onChange={(v) => onChange("virtual_capital", v)}
            step={1000}
          />
          <Field
            label="Max trades / day"
            value={merged.max_trades_per_day}
            onChange={(v) => onChange("max_trades_per_day", v)}
            step={1}
            min={1}
            max={20}
            integer
          />
          <Field
            label="Max open positions"
            value={merged.max_open_positions}
            onChange={(v) => onChange("max_open_positions", v)}
            step={1}
            min={1}
            max={20}
            integer
          />
          <Field
            label="Max risk / trade %"
            value={merged.max_risk_per_trade_percent}
            onChange={(v) => onChange("max_risk_per_trade_percent", v)}
            step={0.1}
            min={0.1}
            max={5}
          />
          <Field
            label="Max daily loss %"
            value={merged.max_daily_loss_percent}
            onChange={(v) => onChange("max_daily_loss_percent", v)}
            step={0.5}
            min={0.5}
            max={10}
          />
          <Field
            label="Min screener score"
            value={merged.min_score}
            onChange={(v) => onChange("min_score", v)}
            step={1}
            min={0}
            max={100}
          />
          <Field
            label="Min risk-reward"
            value={merged.min_risk_reward}
            onChange={(v) => onChange("min_risk_reward", v)}
            step={0.1}
            min={1}
            max={10}
          />
          <Field
            label="Partial exit at T1 (%)"
            value={merged.partial_exit_percent}
            onChange={(v) => onChange("partial_exit_percent", v)}
            step={5}
            min={0}
            max={100}
          />
          <label className="flex flex-col gap-1">
            <span className="text-xs text-fg-muted">Same-candle policy</span>
            <select
              className="input"
              value={merged.same_candle_policy}
              onChange={(e) => onChange("same_candle_policy", e.target.value)}
            >
              {POLICIES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-fg-muted">Trailing stop (breakeven)</span>
            <select
              className="input"
              value={merged.trailing_stop_enabled ? "yes" : "no"}
              onChange={(e) =>
                onChange("trailing_stop_enabled", e.target.value === "yes")
              }
            >
              <option value="yes">Enabled</option>
              <option value="no">Disabled</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-fg-muted">Live trading (auto fills/exits)</span>
            <select
              className="input"
              value={merged.live_trading_enabled ? "yes" : "no"}
              onChange={(e) =>
                onChange("live_trading_enabled", e.target.value === "yes")
              }
            >
              <option value="no">Disabled</option>
              <option value="yes">Enabled</option>
            </select>
          </label>
          <Field
            label="Live poll interval (s)"
            value={merged.live_poll_interval_seconds}
            onChange={(v) => onChange("live_poll_interval_seconds", v)}
            step={30}
            min={30}
            max={600}
            integer
          />
        </div>
        {merged.live_trading_enabled && (
          <div className="px-4 pb-3 -mt-1 text-[11px] text-fg-muted leading-relaxed">
            Live mode polls yfinance 1-minute prices every minute during NSE hours
            (09:15 to 15:30 IST, Mon to Fri) and applies fills, stops, targets, and
            breakeven trailing automatically. Yahoo publishes NSE 1-min bars with a
            roughly 15-minute delay. Paper trading is a simulation - no real orders
            are placed.
          </div>
        )}
        {error && (
          <div className="px-4 py-2 text-xs text-accent-red border-t border-border">
            {error}
          </div>
        )}
        <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
          <button onClick={onClose} className="btn">
            Cancel
          </button>
          <button onClick={save} className="btn btn-primary" disabled={update.isPending}>
            {update.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Save className="size-4" />
            )}
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  step = 1,
  min,
  max,
  integer = false,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
  min?: number;
  max?: number;
  integer?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-fg-muted">{label}</span>
      <input
        type="number"
        className="input num text-right"
        value={value}
        step={step}
        min={min}
        max={max}
        onChange={(e) => {
          const v = e.target.value;
          if (v === "") return;
          const parsed = integer ? parseInt(v, 10) : parseFloat(v);
          if (!Number.isNaN(parsed)) onChange(parsed);
        }}
      />
    </label>
  );
}
