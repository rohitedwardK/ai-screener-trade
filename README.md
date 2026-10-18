# AI Stock Screener — Nifty 50

A production-quality, **research-only** AI-powered stock screener for the
Nifty 50 universe, with a parallel index-analysis layer for Nifty 50 / Bank
Nifty / Sensex and an optional Upstox-backed Live Analysis mode.

> **Disclaimer:** This project is for research and decision-support only. It
> is **not financial advice**. Every signal carries an invalidation level and
> a confidence score — respect them.

> **About the 2026 cleanup:** the paper-trading bots (stock + index) were
> removed to keep the app light. There is no autonomous trade management,
> no decision engine, no order simulator, no ledger. The app is read-only
> analysis: screener + index analysis + live verification + live observation.

> **Live Market child app.** A standalone FastAPI + React service in
> [`live-market/`](live-market/README.md) runs on ports `:8001` / `:5174`
> and emits 5-15 min scalp setups when an index is RANGE_BOUND or 2-3 day
> swing setups when it is TRENDING. Same hard rules apply (read-only,
> invalidation level on every plan, disclaimer verbatim). Boot with
> `start-live-market.bat` / shut down with `stop-live-market.bat`.

---

## Features

- **Research opportunities (Agents page).** Choose stocks or indices and a
  swing/intraday horizon, then click **Research opportunities**. The agent
  inspects cached candidates and selects up to three evidence-backed ideas.
  Numerical levels remain deterministic, with mandatory invalidation and
  directional level checks. Each saved run includes its tool history,
  indicators, limitations, data timestamps, and dated briefing context.
  Restart the backend once after updating to create the `research_runs` table.
  This does not refresh market data; use the existing refresh controls first.
  Stock swing and index swing/intraday research are supported. Stock intraday
  and commodity research are withheld pending timestamped-cache and contract/
  proxy validation respectively. Index ideas are spot-level research only.
  Daily research uses completed bars no older than four calendar days;
  intraday uses complete 15-minute groups from the 5-minute index cache,
  with the last group ending no more than 30 minutes ago. These conservative
  limits can abstain during market closures. Source labels identify the local
  cache; upstream vendor provenance is not yet retained by this research flow.
  Ollama uses the existing `AGENTIC_LLM_*` settings, with at most four actions
  and an eight-second timeout per call. Disable **Agent investigation** for
  deterministic ranking; unavailable/invalid model responses fall back with
  an explicit label. Saved cards remain historical observations, not live
  trigger confirmation. Endpoints: `POST /v1/agents/research` and
  `GET /v1/agents/research/history` (schemas and limits in Swagger).
  Research and decision-support only. Not financial advice.

- **Daily refresh pipeline.** yfinance per-symbol fetch with **CSV cache +
  incremental updates** → SQLite → indicators → snapshots → signals.
- **CSV-cached historical data.** 5y of daily OHLCV is fetched once and
  persisted as one CSV per symbol in `backend/data/ohlcv/`. Subsequent runs
  only fetch days after the cached last date (with a 5-day overlap so
  split / dividend adjustments propagate). Each symbol's CSV is committed
  immediately, so a partial network failure never loses progress. The CSV
  directories are env-configurable (`STOCK_DATA_DIR`,
  `INDEX_DATA_DIR`, `INDEX_INTRADAY_DATA_DIR`) so cloud deploys can point
  at a persistent volume.
- **9 stock signal categories** (Momentum Leaders, Fresh Breakouts, Pullback
  Entries, Oversold Recovering, Overbought – Avoid, Weak – Avoid, High Risk,
  Swing Next Week, Intraday Watch Tomorrow).
- **ATR-based trade plans** — every actionable signal includes `entry`,
  `stop_loss`, `target_1`, `target_2`, `invalidation`, and a `confidence`
  score.
- **Pluggable AI explanation layer** — defaults to a deterministic template;
  flip a single env var to use Ollama (local LLM) or any OpenAI-compatible
  API (OpenAI, Gemini, Groq, etc.).
- **Index analysis** — daily + intraday OHLCV for Nifty 50 / Bank Nifty /
  Sensex, NSE option chain (yfinance fallback) with PCR, max-pain, IV-skew,
  and bias analytics. Six index-specific signal categories
  (`TREND_CONTINUATION`, `BREAKOUT_RETEST`, `PULLBACK_TO_EMA` for LONG;
  `TREND_BREAKDOWN`, `BREAKDOWN_RETEST`, `RALLY_TO_RESISTANCE` for SHORT).
- **Live signal verification.** A scheduler job projects each persisted EOD
  signal against the current LTP every 15 minutes during NSE hours and
  writes a `CONFIRMED / WEAKENING / INVALIDATED / STRENGTHENED` status used
  by the dashboard pills.
- **Live Analysis mode (optional).** Upstox-backed real-time observation +
  decision tracking. Switch the app into Live mode and an APScheduler tick
  polls top movers every `LIVE_ANALYSIS_POLL_MIN` minutes during NSE hours,
  builds 3-minute observation windows, scores them, and persists
  `LiveDecision` rows for review. Read-only.
- **Modern dark dashboard** in React + Vite + Tailwind: category cards,
  sortable / filterable screener table, full stock detail with EMA-overlaid
  price chart, indicator panel, AI panel, indices dashboard, live panel.
- **Unit tests** for indicators, signal logic, regime classification, risk
  math, option-chain analytics, live-quote cache, live verifier, and the
  live-analysis engine pieces.

---

## Architecture

```
React (Vite) ──HTTP──▶ FastAPI ──▶ Repository (SQLAlchemy) ──▶ SQLite (snapshots, signals)
                          │                  ▲
                          ├── APScheduler:
                          │     · daily stock + index refresh
                          │     · index intraday */5 (mon-fri 09-15 IST)
                          │     · live-analysis */N (mon-fri 09-15 IST)
                          │     · live-verification */15 (mon-fri 09-15 IST)
                          ├── Analysis Engine (indicators / patterns / regime / signals)
                          ├── AI Explanation (template | ollama | openai-compat)
                          └── Live Analysis engine (Upstox quotes + scoring)
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

1. **First run**: each Nifty 50 symbol is fetched with `period=5y`,
   normalised, and saved to `backend/data/ohlcv/{SYMBOL}.csv` (~110 KB × 50
   = ~5.5 MB total).
2. **Subsequent runs**: the fetcher reads each CSV's last date, requests
   only `[last_date - 5 days, today]` from Yahoo, and merges (overlap days
   replace existing rows so splits / dividends propagate).
3. **Stale cache** (>7 days): triggers a full re-fetch automatically.
4. **Force full**: `POST /admin/refresh?full=true` ignores the cache for
   every symbol.
5. The full enriched DataFrame is upserted into SQLite for fast indexed
   queries; only **new** rows are upserted on incremental runs.

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

The Vite dev server proxies `/api/*` → `http://127.0.0.1:8000`, so no CORS
pain locally.

---

## Configuration (`backend/.env`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `DB_URL` | `sqlite:///./screener.db` | SQLAlchemy DSN. Swap to Postgres later. |
| `HISTORY_PERIOD` | `5y` | yfinance period (`3y`, `5y`, `10y`, `max`...). |
| `INTERVAL` | `1d` | Daily candles only. |
| `STOCK_DATA_DIR` | `data/ohlcv` | Per-symbol OHLCV CSV cache directory. |
| `INDEX_DATA_DIR` | `data/ohlcv-indices` | Per-index daily CSV cache. |
| `INDEX_INTRADAY_DATA_DIR` | `data/ohlcv-indices-intraday` | Per-index intraday CSV cache. |
| `REFRESH_CRON_HOUR` | `18` | IST hour for daily refresh. |
| `REFRESH_CRON_MINUTE` | `30` | IST minute for daily refresh. |
| `ENABLE_SCHEDULER` | `true` | Disable to run API without background jobs. |
| `LLM_PROVIDER` | `template` | `template` \| `ollama` \| `openai`. |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama daemon URL. |
| `OLLAMA_MODEL` | `llama3.1` | Model tag. |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible endpoint. |
| `OPENAI_API_KEY` | _empty_ | Required when `LLM_PROVIDER=openai`. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Chat completion model. |
| `CORS_ORIGINS` | `http://localhost:5173,...,capacitor://localhost,...` | Comma-separated list (Capacitor APK origins included by default). |
| `UPSTOX_API_KEY` / `UPSTOX_ACCESS_TOKEN` | _empty_ | Required for true real-time live quotes. |
| `LIVE_ANALYSIS_ENABLED` | `true` | Master toggle for the live engine. |
| `LIVE_ANALYSIS_POLL_MIN` | `3` | Cron cadence for the live tick (Mon-Fri 09-15 IST). |

### Switching the AI provider

- **Template (default, free, no setup):** `LLM_PROVIDER=template`
- **Ollama (free, local):** install [ollama](https://ollama.ai/),
  `ollama pull llama3.1`, then set `LLM_PROVIDER=ollama`.
- **OpenAI:** set `LLM_PROVIDER=openai`, `OPENAI_API_KEY=sk-...`. Works with
  any OpenAI-compatible API by changing `OPENAI_BASE_URL`.

If a remote LLM call fails, the backend silently falls back to the template
explanation.

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
| `GET /indices` · `GET /indices/dashboard` | Index list + compact rows. |
| `GET /indices/{symbol}` · `/history` · `/option-chain` | Detail, history, option chain. |
| `POST /admin/refresh-indices` · `/refresh-indices-async` · `/refresh-indices-intraday` | Index data refreshes. |
| `POST /v1/live-verification/run` · `GET /summary` · `GET /signals` | Live screener verification. |
| `GET /v1/live-analysis/dashboard` · `/observations` · `/decisions` · `POST /tick` | Live Analysis mode. |
| `GET /health` | Liveness probe. |

---

## How the signals work

### Indicators (daily, 5y history)
EMA(20/50/200), RSI(14), MACD(12,26,9), ADX(14), ATR(14), Bollinger(20,2),
OBV, 20/50-day volume averages, 5/20/60-day returns, distance from 52-week
high / low, classical floor-trader pivots.

### Regime classification
Each stock is labelled one of `STRONG_UPTREND`, `UPTREND`, `RANGE`,
`DOWNTREND`, `STRONG_DOWNTREND`, `VOLATILE` based on EMA stack, ADX
strength, and ATR%.

### Patterns
20-day breakout (with volume surge), pullback to EMA20 / 50 in uptrend,
oversold bounce (RSI<30 then turning up), bearish reversal (lower-highs +
RSI rolling over), bullish / bearish engulfing, hammer.

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

Q10 (trend / momentum / risk / entry / stop / target per stock) is answered
on every Stock Detail page.

### Risk, scoring and confidence

- **Score (0–100):** count of supporting rules ÷ category cap × 100.
- **Confidence (0–1):** min(1, supporting_rules ÷ required_minimum).
- **Stops:** ATR-based — 2.0× ATR for momentum holds, 1.5× ATR for swing,
  1.0× ATR for intraday.
- **Targets:** R:R of 1.5× and 3.0× the stop distance (1.0× / 2.0× for
  intraday).
- **Invalidation:** equal to the stop loss; surfaced prominently in the
  Stock Detail card and AI panel.

---

## Index Analysis

Tracks **^NSEI (Nifty 50)**, **^NSEBANK (Bank Nifty)**, and **^BSESN
(Sensex)** with daily + intraday OHLCV, NSE option-chain snapshots
(yfinance fallback if NSE blocks), and six index-specific signal
categories.

```
yfinance (daily + 5m) ──▶ index_csv_store ──▶ core/index_pipeline ──┐
NSE option-chain (yf fallback) ──▶ option_chain.py ─────────────────┤
                                                                     ▼
                  index_signals + option_chain_metrics ──▶ index_repository
                                                                     │
                                                                     ▼
                                                            /indices/* API
```

Cron: daily refresh 5 minutes after the stock refresh. Intraday refresh
every 5 minutes Mon-Fri 09-15 IST. The intraday job is lightweight — it
pulls 5-minute bars, synthesises a today-candle, and re-runs signals using
the latest cached chain summary.

The frontend includes:

- **`/indices`** — three index cards with live spot, regime, latest signal,
  PCR / max-pain / bias badges. Click a card to open detail.
- **`/indices/:symbol`** — full snapshot (RSI / ADX / ATR% / MACD /
  returns / EMAs), option-chain bias panel, recent signals table, and an
  ATM-windowed CE/PE option-chain table that auto-refreshes every 60s.

### Known simplification

NSE option chain history is not stored — only the latest snapshot. The
chain bias used for older signal rows is the current snapshot's value.
This is acceptable because the app is analysis-only; there is no
historical replay of intraday option pricing.

---

## Live Analysis mode

Toggle the app between **Historical** and **Live** in the top-right corner.
In Live mode:

- The scheduler runs `intraday-live-analysis-tick` every
  `LIVE_ANALYSIS_POLL_MIN` minutes during NSE hours.
- The engine pulls Upstox quotes for the Nifty 50 + indices (yfinance
  fallback if Upstox isn't configured), classifies the market regime,
  ranks top movers, opens 3-minute observation windows for the highest
  ranked, scores each window, and writes one `LiveDecision` row when an
  observation completes.
- The Live Dashboard page shows the regime banner, top-movers ladder,
  active observation cards, and a recent decisions feed.

**Read-only.** No orders, no positions, no auto-trade management. The
decisions are persisted for review and journaling only.

---

## Tests

```powershell
cd backend
pytest
```

Tests use deterministic synthetic OHLCV fixtures so they run with no
network access.

Coverage:

- `tests/test_indicators.py`, `test_signals.py`, `test_regime.py`,
  `test_risk.py` — stock screener foundations.
- `test_index_pivots.py`, `test_index_signals.py`,
  `test_option_chain_metrics.py` — index analysis layer.
- `test_live_quotes.py` — shared Upstox + yfinance quote cache.
- `test_live_verifier.py` — EOD signal verification status transitions.
- `test_live_movers.py`, `test_live_observer.py`, `test_live_strategy.py`,
  `test_live_regime.py` — Live Analysis engine pieces.

---

## Operational notes

- **First refresh after install** takes ~60–90s — yfinance fetches 5y for
  each of the 50 symbols and the pipeline persists them as CSVs.
- **Subsequent refreshes** complete in ~30–40s. Most of that is yfinance's
  per-call latency + a deliberate 0.30s pacing between calls.
- **Yahoo blocks plain `requests` sessions.** yfinance >=1.3 uses an
  internal `curl_cffi` browser-impersonation session and explicitly rejects
  external `requests-cache` sessions. We therefore pace at the application
  layer instead.
- **CSV is the canonical store.** SQLite is a fast indexed mirror used by
  the API; the CSVs in `STOCK_DATA_DIR` / `INDEX_DATA_DIR` are the source
  of truth and are safe to commit, copy, or back up.
- **Corporate actions** (splits, dividends): the 5-day overlap on
  incremental fetches keeps recent adjusted prices accurate. For older
  bars, run `POST /admin/refresh?full=true` (or simply delete the affected
  CSVs) once a quarter to refresh adjusted history.
- **Nifty 50 changes semi-annually.** Update
  [`backend/app/core/universe.py`](backend/app/core/universe.py) using the
  official factsheet at niftyindices.com when constituents change.
- **Two known flaky tickers** at the time of writing: `LTM.NS` and
  `TMPV.NS` periodically return Yahoo's "possibly delisted" error.
  The pipeline isolates these failures and continues — the other 48
  symbols are unaffected.
- **Daily candles only** for the screener. yfinance imposes tight history
  windows on intraday intervals. The `INTRADAY_WATCH_TOMORROW` category is
  derived from end-of-day signals, not from intraday bars.

---

## Cloud deploy

`render.yaml` at the repo root is a Render Blueprint that creates a
single-instance Docker web service with a 1 GB persistent disk mounted at
`/data`. `STOCK_DATA_DIR` / `INDEX_DATA_DIR` / `DB_URL` are pre-wired to
that disk in the blueprint's env vars.

```
Render Blueprint ──▶ Docker (backend/Dockerfile) ──▶ /data (1 GB)
                              │
                              ▼
              uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Single-instance only — `core/scheduler.py` runs APScheduler in-process. Do
not auto-scale horizontally without first migrating jobs to an external
scheduler.

---

## Project layout

```
ai-stock-screener/
├── backend/
│   ├── app/
│   │   ├── api/             # admin, screener, stocks, explain,
│   │   │                    # indices, live_analysis, live_verification
│   │   ├── ai/              # Pluggable LLM providers
│   │   ├── analysis/        # indicators, patterns, regime, signals, risk,
│   │   │                    # index_signals, option_chain_metrics, live_verifier
│   │   ├── core/            # universe, index_universe, scheduler, pipeline,
│   │   │                    # index_pipeline, live_verification
│   │   ├── data/            # yf_client, upstox_client, fetcher, csv_store,
│   │   │                    # repository, index_fetcher, index_csv_store,
│   │   │                    # option_chain, index_repository, live_quotes
│   │   ├── live_analysis/   # Real-time observation engine (read-only)
│   │   ├── models/          # orm, schemas, index_orm, index_schemas,
│   │   │                    # live_analysis_orm
│   │   ├── config.py / db.py / main.py / seed.py
│   ├── tests/
│   ├── requirements.txt
│   ├── Dockerfile / .dockerignore
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── api/             # types.ts, client.ts (api / liveVerificationApi /
│   │   │                    # indicesApi / liveApi)
│   │   ├── components/      # Layout, Badge, charts, cards, AI panel
│   │   │   ├── indices/     # IndexCard, OptionChainTable
│   │   │   └── live/        # DecisionsFeed, MarketRegimeBanner, ObservationCard, TopMoversLadder
│   │   ├── pages/           # Dashboard, Screener, StockDetail,
│   │   │                    # IndexAnalysis, LiveAnalysis
│   │   └── lib/             # formatters, appMode, useLiveVerificationPoller
│   ├── package.json
│   ├── tailwind.config.ts
│   └── vite.config.ts
├── render.yaml
└── README.md
```
# Trade-quality research scores

The Screener's **Train quality model** action trains a local calibrated Random
Forest using the selected source: recorded stock signals/live verification
observations, or weekly EOD setups reconstructed from the five-year price caches.
The Screener defaults to historical reconstruction; the API defaults to recorded
observations for compatibility. The separate
**Quality %** column estimates whether Target 1 will be touched before the stop
or invalidation during the next five complete trading sessions after the
observation date. It does not predict fills or net returns. If both levels are
touched on one daily candle, the label is failure; if neither is touched within
five sessions, the label is also failure. Incomplete horizons are excluded.

Samples survive routine signal deletion. The first observation for each
symbol/category/signal-date/observation-day and observation kind is retained;
existing retained signals and latest verifications are imported at training time.
Previously deleted history cannot be recovered. Daily indicators are recomputed
on a timestamp-bounded CSV slice, with the current day's candle excluded from
intraday verification features. Historical CSV revisions remain a data limitation.

Historical reconstruction recomputes the rules and indicators on each date's
price slice after indicator warmup, and labels only the next five complete
sessions. It does not insert reconstructed examples into the live archive or
invent historical verification states. Model metadata identifies the source.
It uses today's configured universe, so survivorship bias remains; evaluation
is not an index-wide point-in-time constituent backtest. Training replaces the
current quality artifact only after fitting succeeds.

The Screener shows per-stock cache date spans, row counts, stale/invalid-data
checks, and the distinct dates in the recorded archive. Five years of prices
does not mean five years of archived signal observations. The momentum research
shortlist links current leaders to their daily forecast and price-history view;
today's shortlist does not determine the historical training universe.

Training requires at least 100 mature samples over 30 observation dates and five
examples of each outcome in each partition. Dates are split 60/20/20 into train,
sigmoid calibration and test, with crossing outcome windows purged. Holdout AUC,
Brier score and base-rate Brier are shown beside training status. Scores remain
unavailable unless holdout Brier improves on the training base-rate prediction.
Historical samples, unsupported categories/statuses, stale observations and
invalid plans receive no probability. Repeated retraining against the same test
dates is not independent evidence of future performance.

Swagger documents `POST /method-analysis/quality/train?source=archive|historical` and
`GET /method-analysis/quality/status`; screener rows include `trade_quality`.
The artifact is `backend/data/models/trade_quality_rf.pkl`. Method Analysis uses
Random Forest alongside a rule-based baseline. Only Random Forest is enabled for
ML inference and weekly retraining; GBM and LSTM controls and API methods are
disabled. Their source modules and saved artifacts are retained for possible
future use. The Random Forest method-comparison artifact retains its original
five-session price-return label, separate from setup quality.
Training is manual and does not place or manage trades.

Research and decision-support only. Not financial advice.
