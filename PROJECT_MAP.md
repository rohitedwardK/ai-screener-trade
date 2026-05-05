# PROJECT_MAP.md — repository tour

A directory-by-directory map of the codebase. Pair this with
[AGENTS.md](AGENTS.md) (project primer) and [README.md](README.md) (user docs).

```
├── AGENTS.md             ← AI assistant primer (start here)
├── PROJECT_MAP.md        ← this file
├── README.md             ← user-facing project overview
├── START.readme.md       ← manual start guide & troubleshooting
├── .cursor/rules/        ← scoped Cursor rules (.mdc)
├── backend/              ← FastAPI service (Python 3.12)
└── frontend/             ← React 18 dashboard (Vite + TS)
```

---

## backend/

```
backend/
├── pytest.ini
├── requirements.txt
├── data/                  ← runtime artifacts (gitignored)
│   ├── csv/               ← per-symbol stock CSV cache
│   ├── ohlcv-indices/             ← per-index daily OHLCV cache
│   ├── ohlcv-indices-intraday/    ← per-index intraday cache
│   └── stock.db           ← SQLite mirror, paper + paper-index state
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
    │   └── scheduler.py       ← APScheduler: daily stock + daily index + index intraday */5 + paper live-tick */1 + paper auto-selection @ 09:16 IST (mon-fri)
    │
    ├── data/
    │   ├── yf_client.py            ← yfinance wrapper with pacing
    │   ├── fetcher.py              ← Per-stock fetch
    │   ├── csv_store.py            ← Stock CSV cache
    │   ├── live_quotes.py          ← Shared yfinance 1-min live-price cache (TTL 30s)
    │   ├── index_fetcher.py        ← Per-index daily + intraday fetch
    │   ├── index_csv_store.py      ← Index daily/intraday CSV cache
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
    │   └── option_chain_metrics.py   ← PCR, PCR-vol, max pain (+ distance %), IV skew, bias, strike picker
    │
    ├── ai/                ← Pluggable explanation layer (template/ollama/openai)
    │
    ├── models/            ← ORM + Pydantic schemas
    │   ├── orm.py                ← Stock, Candle, Snapshot, Signal (stocks)
    │   ├── schemas.py            ← Stock screener DTOs
    │   ├── paper_orm.py          ← 6 paper_* tables
    │   ├── paper_schemas.py      ← Paper-stock DTOs
    │   ├── index_orm.py          ← IndexInstrument/Candle/Snapshot/Signal/OptionSnapshot
    │   ├── paper_index_orm.py    ← 6 paper_index_* tables (option-aware)
    │   └── index_schemas.py      ← All index + paper-index DTOs (incl. OptionChain*)
    │
    ├── api/               ← FastAPI routers
    │   ├── screener.py             ← /screener/*
    │   ├── stocks.py               ← /stocks/*
    │   ├── explain.py              ← /explain/*
    │   ├── admin.py                ← /admin/* (stock refresh + index refresh)
    │   ├── paper_trading.py        ← /v1/paper-trading/*
    │   ├── indices.py              ← /indices/* (list, dashboard, detail, history, option-chain)
    │   └── paper_index_trading.py  ← /v1/paper-index-trading/*
    │
    ├── paper/             ← Paper-stock-bot layer
    │   ├── adapter.py / regime.py / config.py
    │   ├── decision.py / sizing.py / simulator.py
    │   ├── live_engine.py ← Pure live-tick evaluator (entry/SL/T1/T2 from one price)
    │   ├── positions.py / ledger.py / kill_switch.py
    │   ├── backtest.py / performance.py / journal.py
    │   └── service.py     ← run_selection / simulate_day / replay / process_live_tick / status
    │
    ├── paper_index/       ← Paper-INDEX-bot layer (parallel to paper/)
    │   ├── adapter.py     ← IndexSignal+Snapshot → IndexScreenerSignal
    │   ├── regime.py      ← Aggregate index market regime
    │   ├── config.py      ← PaperIndexBotConfig (max 5/day default, option_moneyness, delta, live_trading_enabled)
    │   ├── decision.py    ← Filter + rank with chain-bias bonus
    │   ├── sizing.py      ← Lot-aware option sizing, premium-stop fraction
    │   ├── simulator.py   ← Spot→premium delta map; STOP/T1/T2/TRAIL/TIME_EXIT events
    │   ├── live_engine.py ← Pure spot→premium tick evaluator (manages OPEN, never opens new)
    │   ├── positions.py   ← Position lifecycle, MTM via delta-implied premium
    │   ├── ledger.py      ← DAO for paper_index_* tables
    │   ├── kill_switch.py ← Daily limit, loss limit, max open
    │   ├── performance.py ← Aggregate metrics, equity curve, daily upsert
    │   ├── journal.py     ← AI/template daily journal
    │   ├── index_pipeline.py ← Orchestrate daily + intraday refresh (chain → signals)
    │   └── service.py     ← run_selection / simulate_day / replay / reset / status / process_live_tick
    │
    └── tests/             ← pytest, deterministic synthetic OHLCV
        ├── conftest.py
        ├── test_indicators.py / test_signals.py / test_regime.py / test_risk.py
        ├── test_index_pivots.py
        ├── test_paper_decision.py / test_paper_sizing.py / test_paper_simulator.py / test_paper_performance.py
        ├── test_paper_live_engine.py
        ├── test_option_chain_metrics.py
        ├── test_index_signals.py
        ├── test_paper_index_decision.py
        ├── test_paper_index_sizing.py
        ├── test_paper_index_simulator.py
        └── test_paper_index_live_engine.py
```

### Backend module dependency rules

```
analysis ──┐
           ├──> signals ──> api/* ──> main
data ──────┘
core/pipeline ── orchestrates: data + analysis + repository
ai/* ── consumed by api/explain and paper/journal only
paper/* ── orchestrated by api/paper_trading via paper/service
```

- `analysis/*` has **no** DB or network imports.
- `paper/{decision,sizing,simulator,kill_switch,performance,backtest}` are
  pure functions; `paper/{service,ledger,positions,journal,config}` touch
  the DB.
- API routers must not call yfinance directly; they go through
  `core/pipeline.py` or `data/fetcher.py`.

---

## frontend/

```
frontend/
├── package.json
├── vite.config.ts         ← '@'→src alias, /api proxy → http://127.0.0.1:8000
├── tailwind.config.ts     ← design tokens (bg/fg/accent palette)
├── tsconfig.json
└── src/
    ├── main.tsx           ← React root, QueryClient, router
    ├── App.tsx            ← Route table (/, /screener, /paper-trading, /stock/:s)
    ├── index.css          ← Tailwind layers + reusable component classes
    ├── vite-env.d.ts      ← Vite ImportMetaEnv typing
    │
    ├── api/
    │   ├── types.ts       ← All API DTOs (screener + paper + tone maps)
    │   └── client.ts      ← axios + screenerApi + paperApi
    │
    ├── lib/
    │   └── format.ts      ← inr / num / pct / signed helpers (single source)
    │
    ├── pages/
    │   ├── Dashboard.tsx           ← Top-pick cards & regime summary
    │   ├── Screener.tsx            ← Big table + category filters + live prices
    │   ├── StockDetail.tsx         ← Indicators / chart / AI explain
    │   ├── PaperTrading.tsx        ← Composite page using components/paper/*
    │   ├── IndexAnalysis.tsx       ← Indices list + per-index detail (snapshot + chain)
    │   └── PaperIndexTrading.tsx   ← Paper-index bot dashboard (single-file with sub-components)
    │
    └── components/
        ├── Layout.tsx        ← Top nav (Dashboard / Screener / Paper / Indices / Index Bot)
        ├── Badge.tsx
        ├── ScreenerTable.tsx
        ├── StockCard.tsx
        ├── IndicatorPanel.tsx
        ├── PriceChart.tsx
        ├── AIExplain.tsx
        ├── paper/            ← Paper-stock-trading widgets
        │   └── (AccountSummary, BotStatus, ActionsToolbar, TradeCandidatesTable, …)
        └── indices/          ← Index analysis widgets
            ├── IndexCard.tsx          ← Dashboard card for one index
            └── OptionChainTable.tsx   ← ATM-windowed CE/PE table + summary
```

### Frontend data-flow rules

- Server state: **TanStack Query** (`useQuery` / `useMutation`). Stable
  query keys per page. Mutations call `queryClient.invalidateQueries`.
- Polling: `Dashboard` & `Screener` poll `stocksApi.getPrices` every
  60 s. `PaperTrading` polls status / open positions every 30 s.
- Forms: local `useState`, not React-Hook-Form. The only form-heavy surface
  today is `paper/ConfigPanel.tsx`.
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

### Paper-stock-trading endpoints (`/v1/paper-trading/`)
- `GET  /config` · `POST /config` · `GET /status`
- `POST /run-selection` · `POST /simulate-day` · `POST /replay`
- `POST /process-live-tick`  ← apply one yfinance live-price tick to all PENDING/OPEN paper positions
- `GET  /live-debug`         ← per-gate diagnostic: explains why the live engine is/isn't trading
- `GET  /signals` · `/orders` · `/positions` · `/ledger`
- `GET  /performance` · `GET /journal` · `POST /reset`

### Paper-index-trading endpoints (`/v1/paper-index-trading/`)
Same shape as paper-stock-trading but option-aware (strike/lot/premium fields
on signals, orders, positions, ledger). Default `max_trades_per_day=5`.
- `POST /process-live-tick`  ← apply one yfinance live spot tick to all
  OPEN/PARTIAL_EXIT paper-index positions through the `live_engine`
  (SL / T1 / T2 / breakeven trail). Never opens new positions intraday.
  Default `live_trading_enabled=False`; toggle ON in Bot config to let the
  Mon–Fri 09–15 IST scheduler job (`intraday-paper-index-tick`) run it
  every minute.

The frontend hits `/api/...` and Vite's dev proxy strips `/api` before
forwarding to the backend.

---

## Database schema (SQLite, single file at `backend/data/stock.db`)

Stock-screener tables (`models/orm.py`):
- `stocks` · `candles` · `snapshots` · `signals`

Paper-stock-trading tables (`models/paper_orm.py`):
- `paper_bot_config` (singleton)
- `paper_trade_signals` · `paper_orders` · `paper_positions`
- `paper_ledger` (append-only) · `paper_daily_performance`

Index-analysis tables (`models/index_orm.py`):
- `indices` (instruments) · `index_candles` · `index_snapshots`
- `index_signals` · `index_option_snapshots` (per-strike/expiry chain rows)

Paper-index-trading tables (`models/paper_index_orm.py`):
- `paper_index_bot_config` (singleton)
- `paper_index_trade_signals` · `paper_index_orders` · `paper_index_positions`
- `paper_index_ledger` · `paper_index_daily_performance`

`init_db()` calls `Base.metadata.create_all` and imports all four ORM
modules so every table is registered automatically. There is
intentionally no Alembic — schema changes are forward-only via dropping
`backend/data/stock.db` during development.

---

## Generated / runtime artifacts (do not commit)

```
backend/data/csv/*.csv     ← per-symbol OHLCV cache (yfinance output)
backend/data/stock.db      ← SQLite database
backend/.venv/             ← Python virtualenv
backend/app/__pycache__/   ← bytecode
frontend/node_modules/     ← npm packages
frontend/dist/             ← production build output
```

These are listed in `.gitignore`. If you see edits to anything inside
`__pycache__/`, `node_modules/`, `data/csv/`, or `dist/`, treat it as a
mistake and revert.
