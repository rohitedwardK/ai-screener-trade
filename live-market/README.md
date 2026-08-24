# Live Market

Standalone FastAPI + React service that polls Upstox every 1 minute on
the three Indian indices (`^NSEI`, `^NSEBANK`, `^BSESN`), classifies
each as **TRENDING_UP / TRENDING_DOWN / RANGE_BOUND / CHOPPY**, and
emits read-only trade plans:

* **Scalps** (5-15 min holds) when the regime is **RANGE_BOUND**
* **Swings** (2-3 day holds) when the regime is **TRENDING_UP** /
  **TRENDING_DOWN**

Each plan is sized in spot terms first (entry / stop / T1 / T2 /
invalidation) and then translated into an ATM CE/PE option plan with
premium targets via a 0.5-delta heuristic. Sensex is spot-only because
Upstox's `/option/chain` does not currently cover SENSEX on BSE F&O.

> **Hard rules.** This service is read-only analysis. There is no order
> placement, no autonomous trading bot, no broker SDK beyond the Upstox
> read REST client. Every plan carries an invalidation level. Every
> response surfaces:
>
> *Research and decision-support only. Not financial advice.*

---

## Layout

```
live-market/
|-- backend/                      FastAPI + APScheduler (port 8001)
|   |-- requirements.txt          minimal subset of parent's deps
|   |-- pytest.ini
|   |-- data/                     SQLite -> live_market.db
|   `-- app/
|       |-- main.py               FastAPI factory + lifespan
|       |-- config.py             Pydantic settings (reads parent .env)
|       |-- db.py                 own engine, own DB
|       |-- data/                 COPIED Upstox clients + intraday wrapper
|       |-- analysis/             regime + range + scalp + swing + strike
|       |-- core/                 intraday store, pipeline, scheduler, verifier
|       |-- models/               ORM + Pydantic schemas
|       |-- api/                  market, setups, chart, admin routers
|       `-- tests/                deterministic synthetic OHLCV
`-- frontend/                     Vite + React + Tailwind (port 5174)
    `-- src/
        |-- pages/                LiveMarketDashboard, IndexDetail
        `-- components/           RegimeBanner, ScalpCard, SwingCard,
                                  PlanRow, IntradayChart, IndexCardCompact
```

## Ports

| Service | Port | URL |
| ------- | ---- | --- |
| Backend (FastAPI) | 8001 | http://127.0.0.1:8001/docs |
| Frontend (Vite)   | 5174 | http://localhost:5174 |

The Vite dev server proxies `/api/*` to `http://127.0.0.1:8001` so the
frontend code can stay environment-agnostic. Both ports are deliberately
different from the parent app's `:8000` / `:5173` so the two services
run side-by-side.

## Configuration (`.env` at repo root, shared with parent app)

Required:

```
UPSTOX_API_KEY=<your key>
UPSTOX_ACCESS_TOKEN=<rotated daily ~03:30 IST>
```

Optional (defaults in `app/config.py`):

```
DB_URL=sqlite:///./data/live_market.db
INDEX_DATA_DIR=../../backend/data/ohlcv-indices

LIVE_MARKET_ENABLED=true
LIVE_MARKET_POLL_MIN=1
LIVE_MARKET_BAR_HISTORY=375
LIVE_MARKET_HYDRATE_ON_BOOT=true

SCALP_TARGET_SPOT_PCT=0.005     # 0.5% spot target
SCALP_STOP_SPOT_PCT=0.003       # 0.3% spot stop
SCALP_EXPIRY_MIN=20             # auto-EXPIRED if not entered

SWING_TARGET_ATR_MULT=2.0
SWING_STOP_ATR_MULT=1.0
SWING_T1_ATR_MULT=1.2
SWING_HORIZON_DAYS=3

REGIME_TREND_ADX_MIN=22.0
REGIME_RANGE_ADX_MAX=20.0
REGIME_TREND_EMA_SPREAD_PCT=0.0010
REGIME_RANGE_BB_SQUEEZE=0.6

CORS_ORIGINS=http://localhost:5174,http://127.0.0.1:5174
```

## First-time setup

The Live Market backend reuses the parent's Python venv and dependency
list (its requirements are a strict subset). The frontend has its own
`node_modules`.

```powershell
# 1. Parent app venv (skip if already done for the parent)
cd "C:\rohit\workspace\New folder (2)\backend"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Live Market frontend
cd ..\live-market\frontend
npm install
```

## Daily start / stop

```powershell
# from repo root
.\start-live-market.bat
.\stop-live-market.bat
```

`start-live-market.bat` frees ports 8001 and 5174, launches both
processes in their own windows, and opens
http://localhost:5174 in the browser. Idempotent.

## Daily token rotation

Upstox access tokens expire at ~03:30 IST. Update `UPSTOX_ACCESS_TOKEN`
in the repo-root `.env`, then either:

* call `POST /v1/admin/hydrate` to repopulate the rolling 1-min buffer
  immediately, or
* let the scheduler fill in bar by bar over the next ~30 minutes.

The dashboard's `upstox` chip flips to `dead` when a 401 latches the
token; rotate and run `start-live-market.bat` (or just restart the
backend window) to pick up the new value.

## Testing

```powershell
cd live-market\backend
..\..\backend\.venv\Scripts\python.exe -m pytest -q
```

Frontend type-check / build:

```powershell
cd live-market\frontend
npx tsc --noEmit
npm run build
```

## Key endpoints

| Method | Path | Purpose |
| ------ | ---- | ------- |
| GET    | `/health`                              | liveness |
| GET    | `/v1/market/dashboard`                 | three index cards |
| GET    | `/v1/market/regime/{symbol}`           | last 60 regime snapshots |
| GET    | `/v1/setups/scalps/active?symbol=`     | currently active scalps |
| GET    | `/v1/setups/swings/active?symbol=`     | currently active swings |
| GET    | `/v1/setups/scalps/history?symbol=`    | resolved scalps |
| GET    | `/v1/setups/swings/history?symbol=`    | resolved swings |
| GET    | `/v1/chart/{symbol}?lookback=180`      | OHLCV + setups + regimes for index page |
| POST   | `/v1/admin/tick`                       | run one tick out of band |
| POST   | `/v1/admin/hydrate`                    | bulk-load today's 1-min bars |
| GET    | `/v1/admin/health`                     | upstox token state, bar counts |

## Out of scope

* Equities (Nifty 50 stocks) - intentionally indices-only.
* WebSocket / sub-minute ticks - intentionally REST 1-min.
* Order placement / paper-trading simulator / position management - banned.
* LLM explanations - the deterministic `reasons[]` array is sufficient
  for v1.
