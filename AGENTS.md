# AGENTS.md — AI assistant primer

> **Read this file first.** It is the canonical entry-point for any AI editor or
> agent (Cursor, Copilot, Codex, Continue.dev, Aider, etc.) working on this
> repository. It tells you what the project is, where to look for things, and
> what conventions to follow.

For a deeper directory map see [PROJECT_MAP.md](PROJECT_MAP.md). For repeatable
build/run commands see [START.readme.md](START.readme.md). For human-facing
overview see [README.md](README.md).

---

## 1. What this project is

**AI Stock Screener + Paper Trading bot for the Indian Nifty 50, plus a
parallel Index Analysis + Paper-Index-Bot layer for Nifty / Bank Nifty /
Sensex.** Four layers:

1. **Stock Screener.** Daily yfinance pull → CSV cache → SQLite mirror →
 indicators → 9 rule-based signal categories → trade plans (entry /
 stop / target / invalidation) → AI explanation. Lives in
 `backend/app/{analysis,data,core,api,ai}` and
 `frontend/src/{pages,components}` (Dashboard, Screener, Stock detail).
2. **Paper Stock-Trading bot (simulation only).** Reads screener output,
 applies disciplined rules (decision engine → sizing → simulated
 order/position lifecycle → ledger → kill switch → daily performance →
 AI journal). Lives in `backend/app/paper/` +
 `backend/app/api/paper_trading.py` +
 `frontend/src/pages/PaperTrading.tsx` + `frontend/src/components/paper/`.
 Optional **live-tick mode**: when the operator turns on
 `live_trading_enabled` in the config, an APScheduler job polls
 yfinance 1-min prices every minute during NSE hours (09:15–15:30 IST,
 Mon–Fri) and applies fills, stops, targets, and breakeven trailing
 to PENDING/OPEN paper positions via `paper/live_engine.py` and
 `service.process_live_tick`. Still simulation only — no broker SDK,
 no real orders. yfinance NSE 1-min bars are roughly 15 minutes delayed.
3. **Index Analysis.** Daily + intraday OHLCV for ^NSEI / ^NSEBANK / ^BSESN
 + NSE option chain (yfinance fallback) → indicators → trend / breakout
 / pullback signals + chain bias for Nifty/BankNifty. Lives in
 `backend/app/{analysis/{index_signals,option_chain_metrics}.py,
 data/{index_fetcher,index_csv_store,option_chain,index_repository}.py,
 core/index_universe.py, api/indices.py}` and
 `frontend/src/pages/IndexAnalysis.tsx` +
 `frontend/src/components/indices/`.
4. **Paper-Index-Bot (simulation only, options-aware).** Mirrors the stock
 paper bot but trades index options (buy ATM/ITM/OTM CE or PE based on
 setup direction). Premium P&L is approximated from a fixed delta. Lives
 in `backend/app/paper_index/` + `backend/app/api/paper_index_trading.py`
 + `frontend/src/pages/PaperIndexTrading.tsx`. Default cap: **5 trades
 per day**, independent of the stock bot. Optional **live trade-management
 agent**: when `live_trading_enabled` is ON in the bot config, an
 APScheduler job polls yfinance spot prices every minute during NSE hours
 (09:15–15:30 IST, Mon–Fri) and walks OPEN/PARTIAL_EXIT positions through
 `paper_index/live_engine.py` for SL / T1-partial / T2 / breakeven trail.
 Mirrors the stock-bot live engine. **Does not open new positions
 intraday**; PENDING entries still fill via the daily `simulate_day` pass.
 Still simulation only — no broker SDK.

> ## Hard rules — never violate
> - **No real broker integration. No live order placement. No real money.**
>   The paper-trading layer is simulation only. Anything that even hints at
>   live trading must be rejected.
> - Every signal/trade has an **invalidation level**. UI surfaces it; backend
>   never returns a plan without one.
> - Every model output ends with: *"Research and decision-support only. Not
>   financial advice."*
> - **No look-ahead bias** in backtests. `BacktestRunner` slices each symbol's
>   CSV to `df[: as_of]` and re-runs `compute_all` on that slice.

---

## 2. Tech stack at a glance

| Layer | Tech |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.x, Pydantic v2, APScheduler |
| Data | yfinance 1.3 (curl_cffi), pandas, numpy. CSV cache canonical, SQLite mirror. |
| Indicators | Hand-rolled in `backend/app/analysis/indicators.py` (deterministic). |
| AI layer | Pluggable: `template` (default) / `ollama` / `openai`. See `backend/app/ai/`. |
| Frontend | React 18, Vite 6, TypeScript 5, Tailwind 3, TanStack Query 5, Recharts 2, axios. |
| State | Per-page TanStack Query (no Redux). Zustand is installed but unused. |
| Tests | pytest (deterministic synthetic OHLCV, no network). |

---

## 3. Daily workflow & key commands

```powershell
# Backend (port 8000)
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Frontend (port 5173)
cd frontend
npm run dev

# Tests
cd backend
.\.venv\Scripts\python.exe -m pytest -q

# Type-check + production build
cd frontend
npx tsc --noEmit
npm run build
```

Full guide with troubleshooting is in [START.readme.md](START.readme.md).

URLs:
- UI: http://localhost:5173 (`/`, `/screener`, `/paper-trading`,
 `/stock/:symbol`, `/indices`, `/indices/:symbol`,
 `/paper-index-trading`)
- Swagger: http://127.0.0.1:8000/docs
- Paper-trading prefix on backend: `/v1/paper-trading/*` (incl. `POST /process-live-tick`)
- Paper-index-trading prefix on backend: `/v1/paper-index-trading/*` (incl. `POST /process-live-tick`)
- Index analysis prefix on backend: `/indices/*`
- Frontend hits `/api/...` and the Vite proxy strips `/api`.

---

## 4. Code conventions (universal)

- **Comments explain *why*, not *what*.** Don't narrate code. No "// Import
  the module" / "// Increment counter" lines.
- **No new top-level files** unless absolutely necessary. Prefer editing
  existing modules.
- **Disclaimers stay verbatim** — never paraphrase the standard "Research and
  decision-support only. Not financial advice." line.
- **Numbers in logs and UI** use the project formatters (`fmt.inr`, `fmt.num`,
  etc. on the frontend; f-strings with `:.2f` style on the backend).
- **Run lints / type-checks after substantive edits.** Use `ReadLints` (Cursor)
  or `npx tsc --noEmit` / `pytest`.

### Backend Python

- Pure functions where possible (every module in `backend/app/paper/` except
  `service.py`, `ledger.py`, and `journal.py` is pure / testable in isolation).
- Indicators are **hand-rolled** in `backend/app/analysis/indicators.py` so
  unit tests are deterministic — do not introduce `pandas-ta` calls.
- Database access goes through the repository pattern in
  `backend/app/data/repository.py` and `backend/app/paper/ledger.py`. Don't
  scatter raw SQL across the codebase.
- All new ORM models share the single `Base` from
  `backend/app/models/orm.py` so `init_db()` picks them up automatically.
- Pydantic v2 schemas use `ConfigDict(from_attributes=True)` for ORM->JSON
  conversion (see `backend/app/models/paper_schemas.py`).

### Frontend TypeScript / React

- Functional components only, hooks at the top of the file.
- Path alias `@` → `frontend/src` (configured in `vite.config.ts`).
- Tailwind utility classes; project tokens (`bg`, `bg-surface`, `bg-elevated`,
  `border`, `border-strong`, `fg`, `fg-muted`, `fg-subtle`,
  `accent-{green,red,amber,blue,violet,cyan}`) are defined in
  `frontend/tailwind.config.ts`. Use those, not raw hex.
- Pre-built classes in `frontend/src/index.css`: `.card`, `.badge`,
  `.badge-{tone}`, `.btn`, `.btn-primary`, `.input`, `.chip`, `.chip-active`,
  `.num` (tabular numerals).
- Numbers always go through `frontend/src/lib/format.ts` helpers.
- Server state uses **TanStack Query** with stable query keys
  (`["paper-status"]`, `["paper-positions-open"]`, etc.). Mutations invalidate
  by key.
- Live polling pattern: `refetchInterval: PRICE_REFRESH_INTERVAL` constant +
  countdown UI (see `Dashboard.tsx` and `Screener.tsx`).

### Paper-trading layer specifics

- Decision engine, sizing, simulator, performance, kill-switch are **all
  pure functions**. They take immutable inputs (`PaperConfigSnapshot`,
  `ScreenerSignal`, `SimPosition`) and return data (`Decision`, `SizingResult`,
  `SimEvent`, `BotState`, `AggregateMetrics`). DB writes happen only in
  `service.py`, `ledger.py`, and `positions.py`.
- The simulator emits a stream of `SimEvent`s; the position manager applies
  them. Don't shortcut and write directly into ORM positions from `simulator.py`.
- Same-candle conflicts have three policies (`conservative`, `optimistic`,
  `ohlc_approx`); default is `conservative` (stop wins).
- New entries respect every kill-switch reason (see `kill_switch.evaluate`).
  Don't add bypass flags.

### Tests

- All tests under `backend/tests/` use **deterministic synthetic OHLCV**
  fixtures (see `conftest.py`). No network access.
- New paper-trading logic should add corresponding test cases in
  `test_paper_decision.py` / `test_paper_sizing.py` / `test_paper_simulator.py`
  / `test_paper_performance.py`.
- Run `pytest -q` before claiming a change is done. There are 144 tests today;
 that count should only go up.

---

## 5. Where to add things — quick decision tree

| You want to... | Touch... |
| --- | --- |
| Add a new technical indicator | `backend/app/analysis/indicators.py` (+ test in `tests/test_indicators.py`) |
| Add/change pivot-level math | `backend/app/analysis/pivots.py` (+ test in `tests/test_index_pivots.py`); `compute_all` already calls it |
| Add a new screener signal category | `backend/app/analysis/signals.py` and `frontend/src/api/types.ts` (`CATEGORY_LABELS`, `CATEGORY_TONE`) |
| Add/change a paper-stock rule | `backend/app/paper/decision.py` or `sizing.py` (+ test) |
| New paper-stock order behaviour | `backend/app/paper/simulator.py` (+ test) |
| New paper-stock endpoint | `backend/app/api/paper_trading.py` |
| New paper-stock widget | `frontend/src/components/paper/` and `pages/PaperTrading.tsx` |
| Add a new index | `backend/app/core/index_universe.py` (and run `/admin/refresh-indices`) |
| Add a new index signal type | `backend/app/analysis/index_signals.py` (+ `tests/test_index_signals.py`) |
| Add an option-chain metric | `backend/app/analysis/option_chain_metrics.py` (+ tests) |
| Add/change a paper-index rule | `backend/app/paper_index/decision.py` / `sizing.py` (+ tests) |
| New paper-index order behaviour | `backend/app/paper_index/simulator.py` (+ test) |
| New paper-index live-tick logic | `backend/app/paper_index/live_engine.py` (pure spot→premium evaluator) (+ `tests/test_paper_index_live_engine.py`) |
| New paper-index endpoint | `backend/app/api/paper_index_trading.py` |
| New paper-index widget | `frontend/src/pages/PaperIndexTrading.tsx` (single-file page with sub-components) or `frontend/src/components/indices/` |
| New chart on existing pages | Reuse `recharts` patterns from `frontend/src/components/paper/PerformanceCharts.tsx` |
| Change DB schema | Edit relevant ORM file (`models/orm.py`, `paper_orm.py`, `index_orm.py`, or `paper_index_orm.py`); `init_db()` calls `_sync_sqlite_columns` so new tables AND new columns on existing tables are picked up automatically. SQLite-only project — no Alembic. Renames/drops still need a manual SQL migration. |
| Add a Nifty 50 constituent change | `backend/app/core/universe.py` |

---

## 6. Things to avoid

- **Don't introduce broker SDKs.** Even adding the package name is a red flag.
- **Don't bypass the kill switch** to "test" something. The simulators must
 always go through `paper.service.simulate_day` or
 `paper_index.service.simulate_day`.
- **Don't skip stop-losses.** A `PaperPosition` / `PaperIndexPosition` row
 without a stop is invalid; both ORMs enforce
 `stop_loss = Column(Float, nullable=False)`.
- **Don't add live broker option-chain hooks.** The NSE option-chain client
 in `data/option_chain.py` is read-only and used purely for analysis and
 simulation. Do not extend it to place orders.
- **Don't add comments that narrate code.** ("# now we calculate the RSI",
  "// fetch the prices") — useless noise.
- **Don't widen the public API surface area** without updating the OpenAPI
  spec / Swagger description.
- **Don't add new dependencies** without a clear necessity. The existing list
  is intentionally minimal.

---

## 7. Subdirectory READMEs and rules

The repository ships several focused docs / rules. Pick the one that
matches what you're touching:

- [README.md](README.md) — user-facing overview, features, configuration.
- [PROJECT_MAP.md](PROJECT_MAP.md) — directory tree with per-file purpose.
- [START.readme.md](START.readme.md) — manual start commands & troubleshooting.
- `.cursor/rules/core-conventions.mdc` — applies to every conversation.
- `.cursor/rules/backend-python.mdc` — applies when editing `backend/**/*.py`.
- `.cursor/rules/frontend-react.mdc` — applies when editing `frontend/**/*.{ts,tsx}`.
- `.cursor/rules/paper-trading.mdc` — applies inside the paper-trading layer.
- `.cursor/rules/testing.mdc` — applies inside `backend/tests/`.

---

## 8. Disclaimer (always include in user-facing output)

> Research and decision-support only. Paper trading is a simulation. Not
> financial advice.
