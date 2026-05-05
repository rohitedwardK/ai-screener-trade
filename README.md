# AI Stock Screener — Nifty 50

A production-quality, **research-only** AI-powered stock screener for the Nifty 50 universe.
Fetches up to 5 years of daily OHLCV from Yahoo Finance, computes a battery of
technical indicators, classifies each stock's regime, runs a rule-based scoring
engine, and uses a pluggable LLM layer to explain the findings in plain English.

> **Disclaimer:** This project is for research and decision-support only. It is
> **not financial advice**. Every signal carries an invalidation level and a
> confidence score — respect them.

---

## Features

- **Daily refresh pipeline**: yfinance per-symbol fetch with **CSV cache + incremental updates** → SQLite → indicators → snapshots → signals.
- **CSV-cached historical data**: 5y of daily OHLCV is fetched once and persisted as one CSV per symbol in `backend/data/ohlcv/`. Subsequent runs only fetch days after the cached last date (with a 5-day overlap so split/dividend adjustments propagate). Each symbol's CSV is committed immediately, so a partial network failure never loses progress.
- **9 signal categories** answering the 10 user questions (Momentum Leaders, Fresh Breakouts, Pullback Entries, Oversold Recovering, Overbought – Avoid, Weak – Avoid, High Risk, Swing Next Week, Intraday Watch Tomorrow).
- **ATR-based trade plans** — every actionable signal includes `entry`, `stop_loss`, `target_1`, `target_2`, `invalidation`, and a `confidence` score.
- **Pluggable AI explanation layer** — defaults to a deterministic template; flip a single env var to use Ollama (local LLM) or any OpenAI-compatible API (OpenAI, Gemini, Groq, etc.).
- **Modern dark dashboard** in React + Vite + Tailwind: category cards, sortable/filterable screener table, full stock detail with EMA-overlaid price chart, indicator panel, AI panel.
- **Unit tests** for indicators, signal logic, regime classification, and risk math.
- **Paper trading bot (simulation only)** — decision engine, position sizing, simulated order/position lifecycle, historical replay, kill switches, daily performance metrics, and an AI-generated trade journal. All under `/api/v1/paper-trading/*`. See [Paper Trading Layer](#paper-trading-layer-simulation-only).
- **Index analysis + Paper-Index-Bot** — daily + intraday OHLCV for Nifty 50 / Bank Nifty / Sensex, NSE option chain (yfinance fallback) with PCR, max-pain, IV-skew, and a parallel paper bot that buys ATM/ITM/OTM CE or PE based on technical setup + chain bias. Hard cap of **5 trades/day**, independent of the stock bot. See [Index Layer](#index-analysis--paper-index-bot).
- **Architected for upgrade** — repository pattern + env-driven config means swapping SQLite → Postgres, APScheduler → Celery, requests-cache SQLite → Redis is configuration only.

---

## Architecture

```
React (Vite) ──HTTP──▶  FastAPI ──▶ Repository (SQLAlchemy) ──▶ SQLite (snapshots, signals)
                          │                  ▲
                          ├── APScheduler (daily refresh)
                          ├── Analysis Engine (indicators / patterns / regime / signals)
                          └── AI Explanation (template | ollama | openai-compat)
                                       ▲
                                       │
              Smart fetcher (per-symbol incremental, app-paced)
                                       │
                                       ▼
                       data/ohlcv/{SYMBOL}.csv  ← canonical OHLCV store
                                       │
                                       ▼
                           yfinance 1.3 (curl_cffi)
```

### Data flow

1. **First run**: each Nifty 50 symbol is fetched with `period=5y`, normalised, and saved to `backend/data/ohlcv/{SYMBOL}.csv` (~110 KB × 50 = ~5.5 MB total).
2. **Subsequent runs**: the fetcher reads each CSV's last date, requests only `[last_date - 5 days, today]` from Yahoo, and merges (overlap days replace existing rows so splits/dividends propagate).
3. **Stale cache** (>7 days): triggers a full re-fetch automatically.
4. **Force full**: `POST /admin/refresh?full=true` ignores the cache for every symbol.
5. The full enriched DataFrame is upserted into SQLite for fast indexed queries; only **new** rows are upserted on incremental runs (older history is already there).

---

## Quick Start

### 1. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env

# One-time seed: downloads 5y data for all 50 symbols and generates signals.
# Takes 30–90 seconds depending on bandwidth and the yfinance cache state.
python -m app.seed

# Run API (also starts the daily scheduler):
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs for interactive Swagger.

### 2. Frontend

```powershell
cd frontend
copy .env.example .env
npm install
npm run dev
```

Open http://localhost:5173.

The Vite dev server proxies `/api/*` → `http://127.0.0.1:8000`, so no CORS pain locally.

---

## Configuration (`backend/.env`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `DB_URL` | `sqlite:///./screener.db` | SQLAlchemy DSN. Swap to Postgres later. |
| `HISTORY_PERIOD` | `5y` | yfinance period (`3y`, `5y`, `10y`, `max`…). |
| `INTERVAL` | `1d` | Daily candles only (intraday has tight history limits). |
| `REFRESH_CRON_HOUR` | `18` | IST hour for daily refresh. |
| `REFRESH_CRON_MINUTE` | `30` | IST minute for daily refresh. |
| `ENABLE_SCHEDULER` | `true` | Disable to run API without background jobs. |
| `LLM_PROVIDER` | `template` | `template` \| `ollama` \| `openai`. |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama daemon URL. |
| `OLLAMA_MODEL` | `llama3.1` | Model tag. |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible endpoint. |
| `OPENAI_API_KEY` | _empty_ | Required when `LLM_PROVIDER=openai`. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Chat completion model. |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Comma-separated list. |

### Switching the AI provider

- **Template (default, free, no setup):** `LLM_PROVIDER=template`
- **Ollama (free, local):** install [ollama](https://ollama.ai/), `ollama pull llama3.1`, then set `LLM_PROVIDER=ollama`.
- **OpenAI:** set `LLM_PROVIDER=openai`, `OPENAI_API_KEY=sk-...`. Works with any OpenAI-compatible API by changing `OPENAI_BASE_URL`.

If a remote LLM call fails, the backend silently falls back to the template explanation.

---

## API

| Endpoint | Description |
| --- | --- |
| `GET /screener?category=...&min_score=...&sector=...` | All matched signals from the latest run. |
| `GET /screener/categories?top_n=3` | Aggregate counts + top N stocks per category. |
| `GET /stocks` | List all stocks in the universe. |
| `GET /stocks/{symbol}` | Stock detail: latest snapshot + recent signals. |
| `GET /stocks/{symbol}/history?range=1y` | OHLCV time series for charting. |
| `GET /explain/{symbol}` | LLM-generated explanation with disclaimer + invalidation. |
| `POST /admin/refresh` | Run the pipeline synchronously (incremental by default). Pass `?full=true` to force a complete re-download. |
| `POST /admin/refresh-async` | Same, but returns immediately and runs in the background. |
| `GET /admin/cache-status` | Diagnostic: symbol, last cached date, and row count for every CSV. |
| `GET /health` | Liveness probe. |

---

## How the signals work

### Indicators (daily, 5y history)
EMA(20/50/200), RSI(14), MACD(12,26,9), ADX(14), ATR(14), Bollinger(20,2), OBV, 20/50-day volume averages, 5/20/60-day returns, distance from 52-week high/low.

### Regime classification
Each stock is labelled one of `STRONG_UPTREND`, `UPTREND`, `RANGE`, `DOWNTREND`, `STRONG_DOWNTREND`, `VOLATILE` based on EMA stack, ADX strength, and ATR%.

### Patterns
20-day breakout (with volume surge), pullback to EMA20/50 in uptrend, oversold bounce (RSI<30 then turning up), bearish reversal (lower-highs + RSI rolling over), bullish/bearish engulfing, hammer.

### Signal categories → user questions

| Category | Answers |
| --- | --- |
| `MOMENTUM_LEADER` | Q1 — Which stocks are momentum leaders? |
| `FRESH_BREAKOUT` | Q2 — Fresh breakout candidates. |
| `PULLBACK_ENTRY` | Q3 — Pullback entry candidates. |
| `OVERSOLD_RECOVERING` | Q4 — Oversold but recovering. |
| `OVERBOUGHT_AVOID` | Q5 — Overbought, don't chase. |
| `WEAK_AVOID` | Q6 — Weak, avoid. |
| `HIGH_RISK` | Q7 — High risk (vol/volume). |
| `SWING_NEXT_WEEK` | Q8 — Swing trade candidates next week. |
| `INTRADAY_WATCH_TOMORROW` | Q9 — Intraday watchlist. |

Q10 (trend / momentum / risk / entry / stop / target per stock) is answered on every Stock Detail page.

### Risk, scoring and confidence

- **Score (0–100):** count of supporting rules ÷ category cap × 100.
- **Confidence (0–1):** min(1, supporting_rules ÷ required_minimum). Surfaces in the UI as a percentage.
- **Stops:** ATR-based — 2.0× ATR for momentum holds, 1.5× ATR for swing, 1.0× ATR for intraday.
- **Targets:** R:R of 1.5× and 3.0× the stop distance (1.0× / 2.0× for intraday).
- **Invalidation:** equal to the stop loss; surfaced prominently in the Stock Detail card and AI panel.

---

## Paper Trading Layer (simulation only)

Built on top of the screener as a **disciplined paper trading bot** — it never connects to a real broker, never places real orders, and never moves real money. Every "trade" is simulated against the cached OHLCV CSVs.

> **Disclaimer:** Paper trading simulation only. Not financial advice. Use it to validate strategy discipline, not to predict P&L.

### What it does

1. Reads the latest screener output and adapts each `Signal + Snapshot` into the canonical paper-bot input (trend, setup_type, R:R, confidence/risk buckets, entry zone).
2. Aggregates per-stock regimes into a market regime (`Bullish` if ≥60% UPTREND, `Bearish` if ≥60% DOWNTREND, else `Sideways`).
3. Filters candidates against the rules (score ≥ 75, R:R ≥ 2.0, confidence ≥ Medium, risk_level ≤ Medium, market not Bearish, allowed setup, RSI ≤ 75, valid plan, no duplicate-symbol position).
4. Ranks survivors by a weighted **automation_score** (`0.35*score + 0.25*setup_quality + 0.20*rr + 0.10*liquidity + 0.10*regime`) and takes the top **N** where `N = max_trades_per_day - taken_today` — never forces a fill.
5. Sizes each selected trade: `floor(risk_budget / (entry - stop))` then four reductions (confidence Medium = -25%, risk_level Medium = -20%, Oversold Recovery = -50%, ATR% ≥ 4.5 = -25%) and rejects if quantity ≤ 0, stop > 8% of entry, or position > 25% of capital.
6. Simulates entry, stop loss, target 1 (50% partial by default), target 2, breakeven trailing after T1, and time exit (intraday). Same-candle conflicts use a configurable policy (`conservative` / `optimistic` / `ohlc_approx`).
7. Writes immutable ledger events for every state change. Updates daily P&L, win rate, profit factor, drawdown, expectancy.
8. **Kill switches**: pauses new entries on daily loss ≥ 2%, three consecutive losses, max-open-positions, daily-trade cap, or bearish market regime.
9. Generates an **AI journal** for the day reusing the same pluggable LLM provider (template fallback if no LLM is configured).

### Architecture

```
screener Signal+Snapshot ──▶ adapter ──▶ ScreenerSignal ──▶ DecisionEngine ──┐
                                          │                                   │
       per-stock regime ─▶ regime aggr ──▶┘                                   │
                                                                              ▼
                       ┌────────────────────────────  PaperTradingService  ◀─┘
                       │                                          │
                       ▼                                          ▼
                   sizing                                    OrderSimulator
                       │                                          │
                       ▼                                          ▼
                 PaperPositionManager  ──▶  paper_positions  ◀─────┘
                       │                          │
                       ▼                          ▼
                  paper_orders               paper_ledger (immutable)
                                                  │
                                                  ▼
                                    PerformanceService → paper_daily_performance
                                                  │
                                                  ▼
                                          AIJournalService
```

Six new SQLite tables are created on startup (no migration tool needed): `paper_bot_config`, `paper_trade_signals` (selected **and** skipped for full audit), `paper_orders`, `paper_positions`, `paper_ledger`, `paper_daily_performance`.

### Daily flow

The backend mounts the paper-trading router at `/v1/paper-trading/*`. The Vite dev proxy rewrites `/api` → root, so the **frontend** consumes `/api/v1/paper-trading/*` while a **direct curl** call uses `/v1/paper-trading/*`.

```powershell
# 1. Refresh the screener as usual
curl.exe -X POST "http://127.0.0.1:8000/admin/refresh"

# 2. Run paper-bot selection: reads latest screener signals, applies rules, opens PENDING_ENTRY positions.
curl.exe -X POST "http://127.0.0.1:8000/v1/paper-trading/run-selection"

# 3. Next day (or same day if you have today's candle): simulate fills, stops, targets.
curl.exe -X POST "http://127.0.0.1:8000/v1/paper-trading/simulate-day?date=2026-05-06"

# 4. Walk a historical date range to backtest current rules:
curl.exe -X POST "http://127.0.0.1:8000/v1/paper-trading/replay?start=2026-04-01&end=2026-05-01"

# 5. Read state
curl.exe "http://127.0.0.1:8000/v1/paper-trading/status"
curl.exe "http://127.0.0.1:8000/v1/paper-trading/positions?status=open"
curl.exe "http://127.0.0.1:8000/v1/paper-trading/performance"
curl.exe "http://127.0.0.1:8000/v1/paper-trading/journal?date=2026-05-06"
```

### API

Backend prefix: `/v1/paper-trading` (frontend-facing URL via the dev proxy: `/api/v1/paper-trading`).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/config` | Current bot config (single row). |
| POST | `/config` | Patch any subset of config keys. |
| GET | `/status` | Equity, today's P&L, trades remaining, kill-switch status. |
| POST | `/run-selection?date=YYYY-MM-DD` | Adapt screener output → decision engine → write `paper_trade_signals` + open PENDING positions. |
| POST | `/simulate-day?date=YYYY-MM-DD` | Fill pendings, walk open positions for stops/targets, mark-to-market, upsert daily perf. |
| POST | `/replay?start=&end=` | Day-by-day historical replay using cached CSVs (no look-ahead). |
| GET | `/signals?date&decision&symbol` | Selected and skipped signals (with `skip_reason`). |
| GET | `/orders?status&symbol` | Simulated orders. |
| GET | `/positions?status=open\|closed&symbol` | Open or closed positions. |
| GET | `/ledger?from&to&symbol` | Immutable event log. |
| GET | `/performance?from&to` | Aggregate metrics + per-setup breakdown + equity curve. |
| GET | `/journal?date` | LLM/template-generated daily journal. |
| POST | `/reset?confirm=YES` | Wipe paper state (config retained). |

### Config keys (`paper_bot_config`)

| Key | Default | Purpose |
| --- | --- | --- |
| `virtual_capital` | `100000` | Starting paper capital. |
| `max_trades_per_day` | `5` | Hard cap on new entries per simulated day. |
| `max_open_positions` | `5` | Pauses new entries when reached. |
| `max_risk_per_trade_percent` | `0.5` | Max % of capital risked per trade (entry − stop). |
| `max_daily_loss_percent` | `2.0` | Daily loss kill switch. |
| `min_score` | `75` | Lowest screener score the decision engine accepts. |
| `min_risk_reward` | `2.0` | Lowest acceptable R:R. |
| `partial_exit_percent` | `50` | Quantity exited at Target 1. |
| `trailing_stop_enabled` | `true` | Move stop to entry after T1 hit. |
| `same_candle_policy` | `conservative` | One of `conservative` (stop wins), `optimistic` (target wins), `ohlc_approx` (close direction wins). |

### Kill-switch states

| Status | Triggered when |
| --- | --- |
| `ACTIVE` | All guards pass; bot can take new entries. |
| `DAILY_LIMIT_REACHED` | `trades_today >= max_trades_per_day`. |
| `DAILY_LOSS_LIMIT_HIT` | `realised_loss_today_pct >= max_daily_loss_percent`. |
| `MAX_OPEN_POSITIONS_REACHED` | `open_positions >= max_open_positions`. |
| `PAUSED` | 3+ consecutive losses, or market regime turned `Bearish`. |
| `NO_QUALITY_SETUP` | Zero candidates cleared the rules today. |
| `ERROR` | Unexpected exception (logged). |

### Frontend dashboard

The React frontend now includes a dedicated **Paper Trading** page at [`/paper-trading`](http://localhost:5173/paper-trading) with:

- **Account summary** card — virtual capital, equity, total P&L (with %), realized today, unrealized total, win rate, profit factor, expectancy, max drawdown.
- **Bot status** card — live `ACTIVE / PAUSED / DAILY_LIMIT_REACHED / ...` with reason, trades-taken-today vs cap, open positions, daily-loss limit.
- **Actions toolbar** — `Run Selection`, `Simulate Day`, date-range `Replay`, `Config`, and `Reset` (with two-step confirm).
- **Today's trade candidates** table — selected and skipped, ranked by automation score, with skip reasons.
- **Open positions** table — mark-to-market against latest cached close, with `BE` indicator after T1 trail.
- **Performance charts** (Recharts) — equity curve, daily P&L bar, win/loss donut, per-setup P&L bar.
- **Closed trades** table — entry/exit dates, holding days, realized P&L, exit reason.
- **AI journal panel** — daily summary from the configured LLM provider (or template fallback).
- **Config modal** — edit virtual capital, max trades/day, max open positions, risk %, daily-loss cap, min score, min R:R, partial-exit %, same-candle policy, trailing stop.

All paper-trading queries auto-refresh every 30s via TanStack Query and invalidate after every action.

### What is NOT in this delivery

- **End-to-end backtest validation suite** (Phase 6): broader integration tests beyond the unit tests below — deferred.
- **Real broker integration**: not implemented and never will be in this codebase.

---

## Index Analysis + Paper-Index-Bot

A parallel layer for index option-buying. Tracks **^NSEI (Nifty 50)**,
**^NSEBANK (Bank Nifty)**, and **^BSESN (Sensex)** with daily + intraday
OHLCV, NSE option-chain snapshots (yfinance fallback if NSE blocks), and
six index-specific signal categories.

> **Disclaimer:** Paper trading simulation only. Index option P&L is
> approximated from a fixed delta and does **not** include theta decay,
> IV crush, slippage, or broker fees. Not financial advice.

### What it does

1. **Daily refresh** (cron: 5 minutes after the stock refresh) — fetches
 5y daily OHLCV per index, computes the same indicator pack (EMA / RSI /
 MACD / ADX / ATR / Bollinger), classifies regime, and runs six signal
 rules: `TREND_CONTINUATION`, `BREAKOUT_RETEST`, `PULLBACK_TO_EMA`
 (LONG / CE) and `TREND_BREAKDOWN`, `BREAKDOWN_RETEST`,
 `RALLY_TO_RESISTANCE` (SHORT / PE).
2. **Option-chain analytics** — fetches the current/next weekly expiry
 from NSE for Nifty / Bank Nifty (Sensex falls back to yfinance) and
 derives PCR, PCR-volume, max-pain, IV-skew, and a bullish/bearish/neutral
 chain bias with a 0–1 strength score. The bias adjusts signal scores
 (±15 points × strength) and acts as a hard veto in the paper bot
 (no LONG when chain is bearish; no SHORT when bullish).
3. **Intraday refresh** (cron: every 15 minutes Mon–Fri, 09–15 IST) —
 lightweight: pulls 5-minute bars, synthesises a today-candle, and
 re-runs signals using the latest cached chain summary.
4. **Live prices** (`/indices/prices`, 30s TTL cache) — feeds the dashboard
 and detail pages with 60-second-resolution updates.
5. **Paper-Index-Bot** — same architecture as the stock paper bot:
 decision engine → lot-aware option sizing → simulator → ledger → daily
 performance → AI journal. Differences:
 - **Trades buy-side options only** — ATM/ITM/OTM CE for LONG setups,
 PE for SHORT, picked by `option_moneyness` config (`ATM` / `ITM1` /
 `OTM1`).
 - **Premium P&L is delta-approximated** — every candle's spot range is
 mapped to a premium range using a fixed delta estimate (default 0.5).
 Stops, T1/T2, and trailing stops are stored as premium prices.
 - **Lot-aware sizing** — Nifty lot 75, Bank Nifty 35, Sensex 20.
 Risk-per-trade buys whole lots; rejects if not enough capital for one
 lot at the configured premium-stop fraction.
 - **Hard cap of 5 trades/day** (`max_trades_per_day` default 5),
 independent of the stock bot.
 - **Tight time-frame** — index options have a 5-day weekly lifecycle
 (Nifty: Tue, Bank Nifty: Wed, Sensex: Thu) so defaults are deliberately
 short: `entry_order_expiry_days=1`, `max_holding_days=3`,
 `intraday_horizon_days=1`. Intraday refresh runs every 5 min while
 09:00-15:00 IST so signals reflect live price action.

### Architecture

```
yfinance (daily + 5m) ──▶ index_csv_store ──▶ index_pipeline ──┐
NSE option-chain (yf fallback) ──▶ option_chain.py ────────────┤
                                                                ▼
                  index_signals + option_chain_metrics ──▶ index_repository
                                                                │
                                                                ▼
        IndexSignal+IndexSnapshot ──▶ adapter ──▶ IndexScreenerSignal
                                                                │
                                                                ▼
                              PaperIndexTradingService
                                                  │
              ┌───────────────────────────────────┼─────────────┐
              ▼                                   ▼             ▼
       decision (chain-bias              sizing (lot/lots)   simulator
       bonus + hard veto)                                   (premium P&L)
                                                  │
                                                  ▼
                    paper_index_positions / orders / ledger / daily_perf
                                                  │
                                                  ▼
                                    journal (LLM/template)
```

Five new index tables and six new paper-index tables are created on
startup — no migration tool needed.

### Daily flow

```powershell
# 1. Refresh indices (daily OHLCV + option chain snapshots).
curl.exe -X POST "http://127.0.0.1:8000/admin/refresh-indices"

# 2. Run paper-index-bot selection.
curl.exe -X POST "http://127.0.0.1:8000/v1/paper-index-trading/run-selection"

# 3. Simulate today's fills, stops, targets.
curl.exe -X POST "http://127.0.0.1:8000/v1/paper-index-trading/simulate-day"

# 4. Read state.
curl.exe "http://127.0.0.1:8000/v1/paper-index-trading/status"
curl.exe "http://127.0.0.1:8000/v1/paper-index-trading/positions?status=open"
curl.exe "http://127.0.0.1:8000/v1/paper-index-trading/performance"

# 5. Inspect option chain directly.
curl.exe "http://127.0.0.1:8000/indices/%5ENSEI/option-chain"
```

### API

Backend prefixes: `/indices/*` and `/v1/paper-index-trading/*`. The
frontend hits `/api/...` and the Vite proxy strips `/api`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/indices` | List all configured indices. |
| GET | `/indices/dashboard` | Compact rows for the Indices home page. |
| GET | `/indices/prices?symbols=^NSEI,^NSEBANK` | 30s-cached live spots. |
| GET | `/indices/{symbol}` | Detail: instrument + snapshot + recent signals. |
| GET | `/indices/{symbol}/history?range=1y` | OHLCV time series. |
| GET | `/indices/{symbol}/option-chain` | Full chain + summary (PCR / max pain / bias). |
| POST | `/admin/refresh-indices` | Manual daily refresh (sync). |
| POST | `/admin/refresh-indices-async` | Same but in the background. |
| POST | `/admin/refresh-indices-intraday` | Manual intraday refresh. |
| GET | `/admin/index-cache-status` | Diagnostic: cached daily CSV per index. |
| GET | `/v1/paper-index-trading/config` (+ POST patch) | Bot config. |
| GET | `/v1/paper-index-trading/status` | Equity, today's P&L, kill switch. |
| POST | `/v1/paper-index-trading/run-selection` | Decide + open PENDING positions. |
| POST | `/v1/paper-index-trading/simulate-day` | Fill + walk stops/targets. |
| POST | `/v1/paper-index-trading/replay?start&end` | Day-by-day replay. |
| GET | `/v1/paper-index-trading/signals\|orders\|positions\|ledger` | Listings. |
| GET | `/v1/paper-index-trading/performance` | Aggregates + equity curve. |
| GET | `/v1/paper-index-trading/journal` | Daily summary. |
| POST | `/v1/paper-index-trading/reset?confirm=YES` | Wipe paper-index state. |

### Frontend

Two new pages live alongside the existing dashboard:

- **`/indices`** — three index cards with live spot, regime, latest signal,
 PCR / max-pain / bias badges. Click a card to open detail.
- **`/indices/:symbol`** — full snapshot (RSI / ADX / ATR% / MACD /
 returns / EMAs), option-chain bias panel, recent signals table, and an
 ATM-windowed CE/PE option-chain table that auto-refreshes every 60s.
- **`/paper-index-trading`** — paper-index dashboard mirroring the stock
 paper bot: account summary, kill switch, today's candidates with strike /
 lots / premium / chain bias, open positions (option contract +
 unrealized), closed trades, ledger, performance, and AI journal.

### Known simplifications

- **Premium model is delta-only.** No theta, no vega, no IV crush. Good
 enough to validate setup discipline, **not** to estimate real option P&L.
 Reduce `option_delta_estimate` for far-OTM strikes; the simulator caps
 premium at `max(0, …)` so theoretical losses cannot exceed entry.
- **Replay reuses today's chain bias.** Index option-chain history is not
 stored, so historical replay uses the latest snapshot's bias for older
 dates. The simulator side is fully look-ahead-free.
- **NSE option chain is unofficial.** `data/option_chain.py` warms a
 cookie session and uses browser headers. If NSE rate-limits or blocks
 us, it falls back to `yfinance.Ticker.option_chain()`. Both paths return
 the same `OptionChainPayload` dataclass.

---

## Tests

```powershell
cd backend
pytest
```

Tests use deterministic synthetic OHLCV fixtures so they run with no network access. **144 tests today; that count should only go up.**

Stock layer:
- `tests/test_indicators.py`, `tests/test_signals.py`, `tests/test_regime.py`, `tests/test_risk.py`.

Paper-stock layer:
- `tests/test_paper_decision.py` — filtering rules, automation_score ranking, daily-limit overflow, allowed setups.
- `tests/test_paper_sizing.py` — base formula + four reduction adjustments + every rejection condition.
- `tests/test_paper_simulator.py` — entry fill, expiry, stop, T1 partial + breakeven trail, T2 closeout, time exit, all three same-candle conflict policies.
- `tests/test_paper_performance.py` — win rate, profit factor, expectancy, max drawdown, per-setup breakdown.

Index + paper-index layer:
- `tests/test_option_chain_metrics.py` — PCR, max pain, IV skew, bias derivation, strike picker.
- `tests/test_index_signals.py` — uptrend → LONG, downtrend → SHORT, chain bias boost / penalty.
- `tests/test_paper_index_decision.py` — filtering rules + chain-bias hard vetoes + duplicate-direction rule.
- `tests/test_paper_index_sizing.py` — lot-aware sizing, premium estimator, premium-level stop / T1 / T2 derivation, capital limits.
- `tests/test_paper_index_simulator.py` — entry fill, premium stop, T1+T2 partial + trail, SHORT (PE) targets, intraday time exit, same-candle policies.

---

## Operational notes

- **First refresh after install** takes ~60–90s — yfinance fetches 5y for each of the 50 symbols and the pipeline persists them as CSVs.
- **Subsequent refreshes** complete in ~30–40s. Most of that is yfinance's per-call latency + a deliberate 0.30s pacing between calls. The incremental fetch only asks Yahoo for the last few days per symbol, so the network payload is tiny.
- **Yahoo blocks plain `requests` sessions.** yfinance >=1.3 uses an internal `curl_cffi` browser-impersonation session and explicitly rejects external `requests-cache` sessions. We therefore pace at the application layer instead.
- **CSV is the canonical store.** SQLite is a fast indexed mirror used by the API; `backend/data/ohlcv/*.csv` is the source of truth and is safe to commit, copy, or back up.
- **Corporate actions** (splits, dividends): the 5-day overlap on incremental fetches keeps recent adjusted prices accurate. For older bars, run `POST /admin/refresh?full=true` (or simply delete the affected CSVs) once a quarter to refresh adjusted history.
- **Nifty 50 changes semi-annually.** Update [`backend/app/core/universe.py`](backend/app/core/universe.py) using the official factsheet at niftyindices.com when constituents change.
- **Two known flaky tickers** at the time of writing: `LTIM.NS` and `TATAMOTORS.NS` periodically return Yahoo's "possibly delisted" error. The pipeline isolates these failures and continues — the other 48 symbols are unaffected.
- **Daily candles only.** yfinance imposes tight history windows on intraday intervals — the `INTRADAY_WATCH_TOMORROW` category is derived from end-of-day signals, not from intraday bars.

---

## Upgrade path to production

The codebase is structured so that the following swaps are configuration-only:

| Swap | What changes |
| --- | --- |
| **SQLite → PostgreSQL** | Set `DB_URL=postgresql+psycopg://...`. SQLAlchemy + Alembic will work unmodified except for replacing the `sqlite_insert` upsert calls with `postgresql.insert`. |
| **APScheduler → Celery** | Replace `core/scheduler.py` with a Celery beat schedule pointing at `run_full_refresh`. The pipeline functions are already pure. |
| **requests-cache SQLite → Redis** | `RedisCache` backend in `data/yf_client.py`; add a Redis-backed query cache layer in `data/repository.py`. |
| **Containerisation** | Add a Dockerfile per service + `docker-compose.yml` with `backend`, `frontend`, `redis`, `postgres`, `worker`. |

---

## Project layout

```
ai-stock-screener/
├── backend/
│   ├── app/
│   │   ├── api/             # admin, screener, stocks, explain, paper_trading,
│   │   │                    # indices, paper_index_trading
│   │   ├── ai/              # Pluggable LLM providers
│   │   ├── analysis/        # indicators, patterns, regime, signals, risk,
│   │   │                    # index_signals, option_chain_metrics
│   │   ├── core/            # universe, index_universe, scheduler, pipeline
│   │   ├── data/            # yf_client, fetcher, csv_store, repository,
│   │   │                    # index_fetcher, index_csv_store, option_chain,
│   │   │                    # index_repository
│   │   ├── paper/           # Paper-stock-trading layer
│   │   ├── paper_index/     # Paper-index-trading layer (parallel to paper/)
│   │   ├── models/          # orm, schemas, paper_orm, paper_schemas,
│   │   │                    # index_orm, paper_index_orm, index_schemas
│   │   ├── config.py / db.py / main.py / seed.py
│   ├── tests/
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── api/             # types.ts, client.ts (api / paperApi /
│   │   │                    # indicesApi / paperIndexApi)
│   │   ├── components/      # Layout, Badge, charts, cards, AI panel
│   │   │   ├── paper/       # Paper-stock widgets
│   │   │   └── indices/     # IndexCard, OptionChainTable
│   │   ├── pages/           # Dashboard, Screener, StockDetail, PaperTrading,
│   │   │                    # IndexAnalysis, PaperIndexTrading
│   │   └── lib/             # formatters
│   ├── package.json
│   ├── tailwind.config.ts
│   └── vite.config.ts
└── README.md
```
