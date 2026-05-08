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

**AI Stock Screener + Live signal verification + Index Analysis for the Indian
Nifty 50, Bank Nifty, and Sensex.** Three layers, all read-only / analysis only:

1. **Stock Screener.** Daily yfinance pull → CSV cache → SQLite mirror →
   indicators → 9 rule-based signal categories → trade plans (entry /
   stop / target / invalidation) → AI explanation. Lives in
   `backend/app/{analysis,data,core,api,ai}` and
   `frontend/src/{pages,components}` (Dashboard, Screener, Stock detail).
2. **Index Analysis.** Daily + intraday OHLCV for ^NSEI / ^NSEBANK / ^BSESN
   + NSE option chain (yfinance fallback) → indicators → trend / breakout
   / pullback signals + chain bias for Nifty/BankNifty. Lives in
   `backend/app/{analysis/{index_signals,option_chain_metrics}.py,
   data/{index_fetcher,index_csv_store,option_chain,index_repository}.py,
   core/{index_universe,index_pipeline}.py, api/indices.py}` and
   `frontend/src/pages/IndexAnalysis.tsx` +
   `frontend/src/components/indices/`.
3. **Live Analysis (Upstox-backed).** Optional real-time observation +
   decision-tracking layer. When the operator flips the app into LIVE
   mode, an APScheduler tick polls Upstox (or yfinance fallback) every
   `LIVE_ANALYSIS_POLL_MIN` minutes during NSE hours, builds 3-minute
   observation windows for top movers, scores them, and persists
   `LiveDecision` rows for review. **Read-only.** No orders, no
   simulated positions, no automated trade management. Lives in
   `backend/app/live_analysis/` + `backend/app/api/live_analysis.py`
   + `frontend/src/pages/LiveAnalysis.tsx`.

A separate **Live Signal Verification** job runs every 15 min during
market hours, projecting each persisted EOD signal forward against the
current LTP and writing a `CONFIRMED / WEAKENING / INVALIDATED /
STRENGTHENED` row used by the dashboard pills. Lives in
`backend/app/analysis/live_verifier.py`,
`backend/app/core/live_verification.py`,
`backend/app/api/live_verification.py`.

4. **Agentic layer (head + worker agents).** A head agent delegates work
   to five specialists (Data, Analysis, Market Context, Informant,
   Monitoring) and produces a daily briefing the dashboard renders. The
   deep cycle (refresh → score across all 4 methods → context → events →
   synthesis) repeats every `AGENTIC_DEEP_CYCLE_MIN` (default 15 min)
   during NSE hours; a deterministic 60-sec fast monitor wakes the deep
   cycle on invalidation breaches or new top movers. The InformantAgent
   scans the next `AGENTIC_INFORMANT_DAYS_AHEAD` days (default 5) for
   earnings, ex-dividends, F&O monthly expiries, and macro events
   (RBI MPC, Fed FOMC, monthly auto sales) — affected stocks get tagged
   on the briefing's top-picks table so the operator knows where higher
   volatility is expected. The head agent's only LLM-touched task is
   writing the markdown briefing — everything structured (top picks,
   sector rotation, events, etc.) is built by deterministic Python and
   is therefore always trustworthy. LLM is local Ollama
   (`llama3.2:latest` by default), called via plain httpx to keep the
   dependency surface minimal. Lives in
   `backend/app/agents/{tools,data_agent,analysis_agent,context_agent,
   informant_agent,monitoring_agent,orchestrator,scheduler_jobs,llm}.py`,
   `backend/app/data/event_calendar.py`, `backend/app/api/agents.py`,
   `backend/app/models/agent_orm.py`, and
   `frontend/src/{pages/Agents.tsx,components/agents/*}`. Configured by
   `AGENTIC_*` + `INDIA_VIX_*` + `NEWS_RSS_FEEDS` in `.env`.

### Daily start / stop (Windows)

`start.bat` and `stop.bat` at the repo root are the recommended way to
boot/shut the app. `start.bat` frees ports 8000 + 5173, launches both
processes in their own windows, and opens the browser. The agentic boot
cycle runs automatically inside the backend's lifespan, so no manual
trigger is needed. Both scripts are idempotent.

> ## Hard rules — never violate
> - **No autonomous trading bots.** Paper-trading bots (stock + index)
>   were removed from this app. Do not reintroduce decision engines,
>   sizing, simulators, position managers, ledgers, kill switches, or
>   any scheduler-driven trade management. The app is intentionally
>   read-only analysis.
> - **No real broker integration. No live order placement. No real money.**
>   Even adding a broker SDK package name is a red flag.
> - Every signal carries an **invalidation level**. UI surfaces it; backend
>   never returns a plan without one.
> - Every model output ends with: *"Research and decision-support only. Not
>   financial advice."*
> - **No look-ahead bias** in any historical re-evaluation. Slice each
>   symbol's CSV to `df[: as_of]` and re-run `compute_all` on that slice.

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
- UI: http://localhost:5173 (`/`, `/screener`, `/stock/:symbol`,
  `/indices`, `/indices/:symbol`, `/live`)
- Swagger: http://127.0.0.1:8000/docs
- Index analysis prefix on backend: `/indices/*`
- Live analysis prefix on backend: `/v1/live-analysis/*`
- Live signal verification prefix: `/v1/live-verification/*`
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

- Pure functions where possible.
- Indicators are **hand-rolled** in `backend/app/analysis/indicators.py` so
  unit tests are deterministic — do not introduce `pandas-ta` calls.
- Database access goes through the repository pattern in
  `backend/app/data/repository.py` and `backend/app/data/index_repository.py`.
  Don't scatter raw SQL across the codebase.
- All new ORM models share the single `Base` from
  `backend/app/models/orm.py` so `init_db()` picks them up automatically.
- Pydantic v2 schemas use `ConfigDict(from_attributes=True)` for ORM->JSON
  conversion.

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
  (`["screener"]`, `["indices-dashboard"]`, `["live-verification-summary"]`,
  etc.). Mutations invalidate by key.
- Live polling pattern: `refetchInterval: PRICE_REFRESH_INTERVAL` constant +
  countdown UI (see `Dashboard.tsx` and `Screener.tsx`).

### Tests

- All tests under `backend/tests/` use **deterministic synthetic OHLCV**
  fixtures (see `conftest.py`). No network access.
- Run `pytest -q` before claiming a change is done.

---

## 5. Where to add things — quick decision tree

| You want to... | Touch... |
| --- | --- |
| Add a new technical indicator | `backend/app/analysis/indicators.py` (+ test in `tests/test_indicators.py`) |
| Add/change pivot-level math | `backend/app/analysis/pivots.py` (+ test in `tests/test_index_pivots.py`); `compute_all` already calls it |
| Add a new screener signal category | `backend/app/analysis/signals.py` and `frontend/src/api/types.ts` (`CATEGORY_LABELS`, `CATEGORY_TONE`) |
| Add a new index | `backend/app/core/index_universe.py` (and run `/admin/refresh-indices`) |
| Add a new index signal type | `backend/app/analysis/index_signals.py` (+ `tests/test_index_signals.py`) |
| Add an option-chain metric | `backend/app/analysis/option_chain_metrics.py` (+ tests) |
| Add a chart on existing pages | Reuse `recharts` patterns from `frontend/src/components/indices/*` |
| Change DB schema | Edit relevant ORM file (`models/orm.py`, `index_orm.py`, or `live_analysis_orm.py`); `init_db()` calls `_sync_sqlite_columns` so new tables AND new columns on existing tables are picked up automatically. SQLite-only project — no Alembic. Renames/drops still need a manual SQL migration. |
| Add a Nifty 50 constituent change | `backend/app/core/universe.py` |

---

## 6. Things to avoid

- **Don't introduce broker SDKs.** Even adding the package name is a red flag.
- **Don't reintroduce auto-trading bots.** Decision engines, position
  sizing, order simulators, ledgers, kill switches, scheduler-driven
  trade-management — all explicitly removed and not coming back.
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
- `.cursor/rules/testing.mdc` — applies inside `backend/tests/`.

---

## 8. Disclaimer (always include in user-facing output)

> Research and decision-support only. Not financial advice.
