# Manual Start Guide

How to start the AI Stock Screener + Paper Trading app on Windows (PowerShell).

> Run each block in its **own** PowerShell window. The backend and frontend
> are long-running processes; both must stay open while you use the app.

---

## URLs

| Service | URL |
| --- | --- |
| Frontend (dashboard / screener / paper-trading / indices / index bot) | http://localhost:5173 |
| Backend Swagger / OpenAPI | http://127.0.0.1:8000/docs |
| Backend health check | http://127.0.0.1:8000/health |
| Backend paper-trading status | http://127.0.0.1:8000/v1/paper-trading/status |
| Backend paper-index-trading status | http://127.0.0.1:8000/v1/paper-index-trading/status |
| Backend indices dashboard | http://127.0.0.1:8000/indices/dashboard |

---

## 1. Backend (FastAPI + Uvicorn)

### First time only

```powershell
cd "c:\rohit\workspace\New folder (2)\backend"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# .env (only needed if you want to override defaults)
copy .env.example .env

# Optional one-time seed: 5y of OHLCV for all 50 symbols (~30-90s).
.\.venv\Scripts\python.exe -m app.seed
```

### Every time

```powershell
cd "c:\rohit\workspace\New folder (2)\backend"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

You should see:

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Stop with `Ctrl+C`.

### Run pytest

```powershell
cd "c:\rohit\workspace\New folder (2)\backend"
.\.venv\Scripts\python.exe -m pytest -q
```

---

## 2. Frontend (Vite + React)

### First time only

```powershell
cd "c:\rohit\workspace\New folder (2)\frontend"
copy .env.example .env
npm install
```

### Every time

```powershell
cd "c:\rohit\workspace\New folder (2)\frontend"
npm run dev
```

You should see:

```
VITE v6.4.2  ready in 2413 ms
➜  Local:   http://localhost:5173/
```

Open http://localhost:5173 — pages: `/` (Dashboard), `/screener`,
`/paper-trading`, `/indices`, `/indices/:symbol`, `/paper-index-trading`.

Stop with `Ctrl+C`.

### Production build

```powershell
cd "c:\rohit\workspace\New folder (2)\frontend"
npm run build
npm run preview
```

---

## 3. Stopping a stuck process / port

If `Address already in use` on port 8000 (backend) or 5173 (frontend):

```powershell
# Replace 8000 with 5173 for the frontend port
$conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($conn) {
  Stop-Process -Id $conn.OwningProcess -Force
  Write-Host "Killed PID $($conn.OwningProcess)"
} else {
  Write-Host "Port 8000 is free"
}
```

Or use Task Manager → Details → end any orphan `python.exe` (uvicorn) or `node.exe` (vite).

---

## 4. Common workflows

### Refresh screener data (incremental)

```powershell
curl.exe -X POST "http://127.0.0.1:8000/admin/refresh"
```

Pass `?full=true` to force a full 5y re-download.

### Run the paper-trading bot for today

```powershell
# 1. Generate paper-trade signals from the latest screener run
curl.exe -X POST "http://127.0.0.1:8000/v1/paper-trading/run-selection"

# 2. Simulate fills, stops, and targets for a target date
curl.exe -X POST "http://127.0.0.1:8000/v1/paper-trading/simulate-day?date=2026-05-06"

# 3. Read state
curl.exe "http://127.0.0.1:8000/v1/paper-trading/status"
curl.exe "http://127.0.0.1:8000/v1/paper-trading/positions?status=open"
curl.exe "http://127.0.0.1:8000/v1/paper-trading/performance"
curl.exe "http://127.0.0.1:8000/v1/paper-trading/journal?date=2026-05-06"
```

Or do all of this from the UI under **Paper Trading** → toolbar buttons.

### Replay a historical date range

```powershell
curl.exe -X POST "http://127.0.0.1:8000/v1/paper-trading/replay?start=2026-04-01&end=2026-05-01"
```

### Live-tick mode (autonomous paper trading)

When `live_trading_enabled` is on, two scheduler jobs run automatically
during NSE market hours (Mon-Fri 09:15-15:30 IST):

1. **`auto-paper-selection`** (09:16 IST) calls Run Selection for you so
   PENDING positions are ready before live ticks start. Idempotent — if
   you already pressed Run Selection earlier in the morning, it skips.
2. **`intraday-paper-tick`** (every minute) fetches live yfinance prices
   for symbols of all PENDING/OPEN positions and applies fills, stops,
   target-1 partials, target-2 final exits, and breakeven trailing.

To enable:

1. Open the Paper Trading page → **Config** → set **Live trading
   (auto fills/exits)** to *Enabled* and **Save**.
2. **Restart the backend** so APScheduler picks up the new live-tick and
   auto-selection jobs (a one-time step the first time you upgrade).
3. Done. The bot status card shows a `Live: ON / OFF` badge and the
   timestamp of the most recent tick.

If nothing seems to happen, expand the **Live Diagnostics** panel on
the Paper Trading page. It walks through every gate the live engine
must clear (live toggle, scheduler heartbeat, market hours, screener
freshness, presence of PENDING/OPEN positions) and tells you exactly
which one is blocked, plus the live distance from each pending entry
to its planned price.

```powershell
# Manual one-shot live tick (e.g. outside market hours, for testing):
curl.exe -X POST "http://127.0.0.1:8000/v1/paper-trading/process-live-tick"

# Same diagnostic the UI panel shows:
curl.exe "http://127.0.0.1:8000/v1/paper-trading/live-debug"
```

> Yahoo Finance publishes NSE 1-minute bars with a roughly 15-minute
> delay; this is acceptable because paper trading is a simulation. No
> real broker is contacted and no real orders are placed.

### Reset paper-trading state

```powershell
curl.exe -X POST "http://127.0.0.1:8000/v1/paper-trading/reset?confirm=YES"
```

This wipes all paper signals / orders / positions / ledger / daily-perf rows. The bot config row is **preserved**.

### Refresh the index layer (Nifty / Bank Nifty / Sensex)

```powershell
# Daily refresh: OHLCV + option-chain snapshots + signals.
curl.exe -X POST "http://127.0.0.1:8000/admin/refresh-indices"

# Intraday refresh (Mon-Fri 09:00-15:00 IST): pulls 5m bars, regenerates signals.
curl.exe -X POST "http://127.0.0.1:8000/admin/refresh-indices-intraday"

# Diagnostics
curl.exe "http://127.0.0.1:8000/admin/index-cache-status"
```

### Run the paper-index-bot for today

```powershell
curl.exe -X POST "http://127.0.0.1:8000/v1/paper-index-trading/run-selection"
curl.exe -X POST "http://127.0.0.1:8000/v1/paper-index-trading/simulate-day"

curl.exe "http://127.0.0.1:8000/v1/paper-index-trading/status"
curl.exe "http://127.0.0.1:8000/v1/paper-index-trading/positions?status=open"
curl.exe "http://127.0.0.1:8000/v1/paper-index-trading/performance"
```

Or use the **Index Bot** page in the UI (`/paper-index-trading`).

### Reset paper-index-trading state

```powershell
curl.exe -X POST "http://127.0.0.1:8000/v1/paper-index-trading/reset?confirm=YES"
```

---

## 5. Troubleshooting

| Symptom | Cause / Fix |
| --- | --- |
| Frontend shows "Backend unreachable" | Backend is not running, or running on a different port. Start step 1. |
| `404` on `/api/v1/paper-trading/...` from the UI | The Vite proxy strips `/api`, so the backend prefix is `/v1/paper-trading`. Both already match — this only breaks if you edited `vite.config.ts` or the backend prefix. |
| `ModuleNotFoundError: No module named 'pytest'` | The venv is not active or the package isn't installed. Activate venv and rerun `pip install -r requirements.txt`. |
| `yfinance` 429 / "possibly delisted" on a few symbols | Yahoo rate limiting. Two known flaky tickers: `LTIM.NS`, `TATAMOTORS.NS`. The pipeline isolates these — others continue. |
| Frontend port already in use | See section 3 above. |
| Daily refresh didn't run at 18:30 IST | The scheduler runs only when the backend is running. Check `app.core.scheduler` log lines on startup. |
| `/indices/{symbol}/option-chain` returns 503 | NSE rate-limiting / cookie-warming failed AND yfinance fallback returned no data. Wait 1–2 minutes and retry; the chain is also memo-cached for 60s in-process. |
| Index dashboard is empty | No index refresh has run yet. Trigger `POST /admin/refresh-indices`. |

---

> **Disclaimer**
> This project is for research and decision-support only. Paper trading is a
> simulation only — no real broker, no real money. Not financial advice.
