# PROJECT_MAP.md — repository tour

A directory-by-directory map of the codebase. Pair this with
[AGENTS.md](AGENTS.md) (project primer) and [README.md](README.md) (user docs).

```
├── AGENTS.md             ← AI assistant primer (start here)
├── PROJECT_MAP.md        ← this file
├── README.md             ← user-facing project overview
├── START.readme.md       ← manual start guide & troubleshooting
├── render.yaml           ← Render Blueprint (cloud deploy)
├── .cursor/rules/        ← scoped Cursor rules (.mdc)
├── start.bat / stop.bat  ← daily start/stop for the parent app
├── start-live-market.bat / stop-live-market.bat  ← daily start/stop for the Live Market child app
├── backend/              ← FastAPI service (Python 3.12)
├── frontend/             ← React 18 dashboard (Vite + TS)
└── live-market/          ← Live Market child app (FastAPI :8001 + React :5174)
                            see live-market/README.md for the full layout
```

---

## backend/

```
backend/
├── pytest.ini
├── requirements.txt
├── Dockerfile             ← cloud deploy image
├── .dockerignore
├── data/                  ← runtime artifacts (gitignored)
│   ├── ohlcv/                     ← per-symbol stock CSV cache
│   ├── ohlcv-indices/             ← per-index daily OHLCV cache
│   ├── ohlcv-indices-intraday/    ← per-index intraday cache
│   └── screener.db                ← SQLite mirror
└── app/
    ├── main.py            ← FastAPI factory + lifespan (router mount, scheduler)
    ├── config.py          ← Pydantic settings (env-driven)
    ├── db.py              ← SQLAlchemy engine/session, init_db()
    ├── seed.py            ← CLI to bootstrap data/ from yfinance
    │
    ├── core/
    │   ├── universe.py        ← Nifty 50 constituents
    │   ├── index_universe.py  ← Indices (Nifty 50 / Bank Nifty / Sensex) with lot/strike step
    │   ├── pipeline.py        ← Stock refresh orchestration
    │   ├── index_pipeline.py  ← Daily + intraday index refresh (OHLCV + chain + signals)
    │   ├── live_verification.py ← Cross-check persisted signals vs live LTPs
    │   └── scheduler.py       ← APScheduler: daily stock + daily index + index intraday */5 + live-analysis */N + live-verification */15 (mon-fri)
    │
    ├── data/
    │   ├── yf_client.py            ← yfinance wrapper with pacing
    │   ├── upstox_client.py        ← Upstox v2 quote client (Live mode)
    │   ├── fetcher.py              ← Per-stock fetch
    │   ├── csv_store.py            ← Stock CSV cache (env-configurable dir)
    │   ├── live_quotes.py          ← Shared live-price cache (Upstox primary, yfinance fallback, TTL 30s)
    │   ├── index_fetcher.py        ← Per-index daily + intraday fetch
    │   ├── index_csv_store.py      ← Index daily/intraday CSV cache (env-configurable dirs)
    │   ├── option_chain.py         ← NSE option-chain fetcher (yfinance fallback) + 60s memo cache
    │   ├── repository.py           ← Stock DAO
    │   └── index_repository.py     ← Index DAO (instruments, candles, snapshots, signals, option snapshots)
    │
    ├── analysis/          ← Pure, deterministic
    │   ├── indicators.py             ← EMA/SMA/RSI/MACD/ATR/ADX/Bollinger + classical pivots
    │   ├── pivots.py                 ← Classical floor-trader P/R1-R3/S1-S3 (vectorised, no look-ahead)
    │   ├── patterns.py               ← Candlestick & price-action detectors
    │   ├── regime.py                 ← Per-instrument trend classifier
    │   ├── risk.py                   ← ATR%, volume, gap labels
    │   ├── signals.py                ← 9-category stock screener signals
    │   ├── index_signals.py          ← Index trend / breakout / pullback (LONG + SHORT)
    │   ├── option_chain_metrics.py   ← PCR, PCR-vol, max pain (+ distance %), IV skew, bias, strike picker
    │   └── live_verifier.py          ← Project EOD signals onto live LTPs (CONFIRMED/WEAKENING/...)
    │
    ├── ai/                ← Pluggable explanation layer (template/ollama/openai)
    │
    ├── models/            ← ORM + Pydantic schemas
    │   ├── orm.py                ← Stock, Candle, Snapshot, Signal (stocks)
    │   ├── schemas.py            ← Stock screener DTOs
    │   ├── index_orm.py          ← IndexInstrument/Candle/Snapshot/Signal/OptionSnapshot
    │   ├── index_schemas.py      ← Index DTOs (incl. OptionChain*)
    │   └── live_analysis_orm.py  ← Live observation/decision tables
    │
    ├── api/               ← FastAPI routers
    │   ├── screener.py             ← /screener/*
    │   ├── stocks.py               ← /stocks/*
    │   ├── explain.py              ← /explain/*
    │   ├── admin.py                ← /admin/* (stock refresh + index refresh + cache diagnostics)
    │   ├── indices.py              ← /indices/* (list, dashboard, detail, history, option-chain)
    │   ├── live_analysis.py        ← /v1/live-analysis/* (mode, config, dashboard, observations, decisions, tick)
    │   └── live_verification.py    ← /v1/live-verification/* (run, summary, signals)
    │
    ├── live_analysis/     ← Real-time observation engine (read-only)
    │   ├── config.py / engine.py / service.py / regime.py / scoring.py / observer.py
    │
    └── tests/             ← pytest, deterministic synthetic OHLCV
        ├── conftest.py
        ├── test_indicators.py / test_signals.py / test_regime.py / test_risk.py
        ├── test_index_pivots.py / test_index_signals.py
        ├── test_option_chain_metrics.py
        ├── test_live_quotes.py / test_live_verifier.py
        ├── test_live_movers.py / test_live_observer.py
        ├── test_live_regime.py / test_live_strategy.py
```

### Backend module dependency rules

```
analysis ──┐
           ├──> signals ──> api/* ──> main
data ──────┘
core/pipeline       ── orchestrates: data + analysis + repository  (stocks)
core/index_pipeline ── orchestrates: data + analysis + repository  (indices)
ai/*                ── consumed by api/explain only
live_analysis/*     ── orchestrated by api/live_analysis via service
```

- `analysis/*` has **no** DB or network imports.
- API routers must not call yfinance directly; they go through
  `core/pipeline.py`, `core/index_pipeline.py`, or `data/fetcher.py`.
- Removed in 2026 cleanup: `app/paper/` (stock paper bot) and
  `app/paper_index/` (index paper bot). Do not reintroduce.

---

## frontend/

```
frontend/
├── package.json
├── vite.config.ts         ← '@'→src alias, /api proxy → http://127.0.0.1:8000
├── tailwind.config.ts     ← design tokens (bg/fg/accent palette)
├── tsconfig.json
├── .env.example / .env.production  ← VITE_API_BASE_URL plumbing
└── src/
    ├── main.tsx           ← React root, QueryClient, router
    ├── App.tsx            ← Route table (/, /screener, /stock/:s, /indices, /indices/:s, /live)
    ├── index.css          ← Tailwind layers + reusable component classes
    ├── vite-env.d.ts      ← Vite ImportMetaEnv typing
    │
    ├── api/
    │   ├── types.ts       ← All API DTOs (screener + live verification + index + live analysis + tone maps)
    │   └── client.ts      ← axios + api / liveVerificationApi / indicesApi / liveApi
    │
    ├── lib/
    │   ├── format.ts                 ← inr / num / pct / signed helpers (single source)
    │   ├── appMode.ts                ← Historical/Live mode store (zustand)
    │   └── useLiveVerificationPoller.ts ← 15-min auto-refresh of live verifier
    │
    ├── pages/
    │   ├── Dashboard.tsx           ← Top-pick cards & regime summary
    │   ├── Screener.tsx            ← Big table + category filters + live prices
    │   ├── StockDetail.tsx         ← Indicators / chart / AI explain
    │   ├── IndexAnalysis.tsx       ← Indices list + per-index detail (snapshot + chain)
    │   └── LiveAnalysis.tsx        ← Live mode dashboard (regime, top movers, observations, decisions)
    │
    └── components/
        ├── Layout.tsx        ← Top nav (Dashboard / Screener / Indices / + Live Dashboard in Live mode)
        ├── Badge.tsx
        ├── ScreenerTable.tsx
        ├── StockCard.tsx
        ├── IndicatorPanel.tsx
        ├── PriceChart.tsx
        ├── AIExplain.tsx
        ├── indices/          ← Index analysis widgets
        │   ├── IndexCard.tsx          ← Dashboard card for one index
        │   └── OptionChainTable.tsx   ← ATM-windowed CE/PE table + summary
        └── live/             ← Live Analysis widgets
            ├── DecisionsFeed.tsx
            ├── MarketRegimeBanner.tsx
            ├── ObservationCard.tsx
            └── TopMoversLadder.tsx
```

### Frontend data-flow rules

- Server state: **TanStack Query** (`useQuery` / `useMutation`). Stable
  query keys per page. Mutations call `queryClient.invalidateQueries`.
- Polling: `Dashboard` & `Screener` poll prices every 60 s. Live Analysis
  page polls every `poll_interval_min` while in Live mode.
- Forms: local `useState`, not React-Hook-Form.
- All number rendering goes through `lib/format.ts` so locale and tabular
  numerals stay consistent.

---

## API surface (current)

### Screener / data endpoints
- `GET  /health`
- `GET  /stocks` · `GET /stocks/{symbol}` · `GET /stocks/prices?symbols=...`
- `GET  /screener` · `GET /screener/categories`
- `POST /explain/{symbol}` (uses configured LLM provider)
- `POST /admin/refresh` · `POST /admin/refresh-async` · `GET /admin/cache-status`

### Index analysis endpoints (`/indices/`)
- `GET  /indices` (list) · `GET /indices/dashboard` (compact rows)
- `GET  /indices/prices?symbols=...` (60s TTL cache)
- `GET  /indices/{symbol}` (detail: instrument + snapshot + recent signals)
- `GET  /indices/{symbol}/history?range=1y`
- `GET  /indices/{symbol}/option-chain` (NSE primary, yfinance fallback)
- `POST /admin/refresh-indices` · `/refresh-indices-async` · `/refresh-indices-intraday` · `GET /admin/index-cache-status`

### Live Analysis endpoints (`/v1/live-analysis/`)
- `GET  /mode` · `POST /mode` (HISTORICAL ↔ LIVE)
- `GET  /config` · `POST /config`
- `GET  /dashboard` (regime + top movers + active observations + recent decisions)
- `GET  /decisions?limit=` · `GET /observations?only_active=`
- `POST /tick` (manual tick)

### Live Signal Verification endpoints (`/v1/live-verification/`)
- `POST /run?background=` · `GET /summary` · `GET /signals`

The frontend hits `/api/...` and Vite's dev proxy strips `/api` before
forwarding to the backend.

---

## Database schema (SQLite, single file at `backend/data/screener.db`)

Stock-screener tables (`models/orm.py`):
- `stocks` · `candles` · `snapshots` · `signals`

Index-analysis tables (`models/index_orm.py`):
- `indices` (instruments) · `index_candles` · `index_snapshots`
- `index_signals` · `index_option_snapshots` (per-strike/expiry chain rows)
- `live_signal_verification` (per-signal CONFIRMED/WEAKENING/... rows)

Live-analysis tables (`models/live_analysis_orm.py`):
- `live_analysis_config` (singleton)
- `live_market_snapshots` · `live_observations` · `live_decisions`

`init_db()` calls `Base.metadata.create_all` and imports each side-effect
ORM module so every table is registered automatically. There is
intentionally no Alembic — schema changes are forward-only via dropping
`backend/data/screener.db` during development.

---

## Generated / runtime artifacts (do not commit)

```
backend/data/ohlcv/*.csv             ← per-symbol OHLCV cache (yfinance output)
backend/data/ohlcv-indices/*.csv     ← per-index daily OHLCV
backend/data/ohlcv-indices-intraday/*.csv ← per-index intraday OHLCV
backend/data/screener.db             ← SQLite database
backend/.venv/                       ← Python virtualenv
backend/app/__pycache__/             ← bytecode
frontend/node_modules/               ← npm packages
frontend/dist/                       ← production build output
```

These are listed in `.gitignore`. If you see edits to anything inside
`__pycache__/`, `node_modules/`, `data/ohlcv*/`, or `dist/`, treat it as a
mistake and revert.
