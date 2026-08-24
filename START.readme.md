# Manual Start Guide

How to start the AI Stock Screener app on Windows (PowerShell).

> **TL;DR** — once everything is set up, just double-click `start.bat` in
> the repo root. It launches backend + frontend in two windows and opens
> the dashboard in your default browser. Use `stop.bat` to shut down.
> Both scripts are idempotent (safe to re-run) and free the ports first.

> Run each block in its **own** PowerShell window. The backend and frontend
> are long-running processes; both must stay open while you use the app.

> **Note:** the paper-trading bots (stock + index) were removed in the 2026
> cleanup to keep the app light. There is no auto-fill, no auto-exit, no
> ledger, no kill switch. The app is read-only analysis: screener + index
> analysis + live verification + live observation.

---

## URLs

| Service | URL |
| --- | --- |
| Frontend (dashboard / screener / indices / live / agents) | http://localhost:5173 |
| Backend Swagger / OpenAPI | http://127.0.0.1:8000/docs |
| Backend health check | http://127.0.0.1:8000/health |
| Backend indices dashboard | http://127.0.0.1:8000/indices/dashboard |
| Backend live-analysis dashboard | http://127.0.0.1:8000/v1/live-analysis/dashboard |
| Backend agents status / latest briefing | http://127.0.0.1:8000/v1/agents/status |

---

## 0. One-button start / stop (recommended)

After the first-time setup in section 1 + 2, daily operation is just:

```powershell
# from the repo root
.\start.bat   # frees :8000 + :5173, launches backend & frontend, opens browser
.\stop.bat    # kills whatever is bound to :8000 + :5173
```

Both scripts are idempotent — re-running `start.bat` is safe and will
restart cleanly. The agentic boot cycle (Data → Analysis → Context → Head
synthesis) fires automatically inside the backend's startup hook, so the
dashboard's briefing panel populates within ~30-90s of `start.bat`
completing. No further commands are needed for daily use.

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
-> Local:   http://localhost:5173/
```

Open http://localhost:5173 — pages: `/` (Dashboard), `/screener`,
`/stock/:symbol`, `/indices`, `/indices/:symbol`, `/live`.

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

Or use Task Manager → Details → end any orphan `python.exe` (uvicorn) or
`node.exe` (vite).

---

## 4. Common workflows

### Refresh screener data (incremental)

```powershell
curl.exe -X POST "http://127.0.0.1:8000/admin/refresh"
```

Pass `?full=true` to force a full 5y re-download.

### Refresh the index layer (Nifty / Bank Nifty / Sensex)

```powershell
# Daily refresh: OHLCV + option-chain snapshots + signals.
curl.exe -X POST "http://127.0.0.1:8000/admin/refresh-indices"

# Intraday refresh (Mon-Fri 09:00-15:00 IST): pulls 5m bars, regenerates signals.
curl.exe -X POST "http://127.0.0.1:8000/admin/refresh-indices-intraday"

# Diagnostics
curl.exe "http://127.0.0.1:8000/admin/index-cache-status"
```

### Run a live signal verification pass

```powershell
curl.exe -X POST "http://127.0.0.1:8000/v1/live-verification/run"
curl.exe "http://127.0.0.1:8000/v1/live-verification/summary"
```

The scheduler runs this every 15 min during market hours automatically;
this manual call is mostly for outside-hours testing.

### Switch into Live Analysis mode

```powershell
# From the UI: top-right toggle in the header (Historical | Live).
# From the API:
curl.exe -X POST "http://127.0.0.1:8000/v1/live-analysis/mode" -H "Content-Type: application/json" -d '{\"mode\":\"LIVE\"}'

# Manual one-shot tick (for testing outside market hours):
curl.exe -X POST "http://127.0.0.1:8000/v1/live-analysis/tick"

# Read state:
curl.exe "http://127.0.0.1:8000/v1/live-analysis/dashboard"
curl.exe "http://127.0.0.1:8000/v1/live-analysis/observations?only_active=true"
curl.exe "http://127.0.0.1:8000/v1/live-analysis/decisions?limit=20"
```

> Live Analysis is **read-only**. It tracks observations and emits
> `LiveDecision` rows for review. There is no automated trade management.

---

## 5. Troubleshooting

| Symptom | Cause / Fix |
| --- | --- |
| Frontend shows "Backend unreachable" | Backend is not running, or running on a different port. Start step 1. |
| `ModuleNotFoundError: No module named 'pytest'` | The venv is not active or the package isn't installed. Activate venv and rerun `pip install -r requirements.txt`. |
| `yfinance` 429 / "possibly delisted" on a few symbols | Yahoo rate limiting. Two known flaky tickers: `LTM.NS`, `TMPV.NS`. The pipeline isolates these — others continue. |
| Frontend port already in use | See section 3 above. |
| Daily refresh didn't run at 18:30 IST | The scheduler runs only when the backend is running. Check `app.core.scheduler` log lines on startup. |
| `/indices/{symbol}/option-chain` returns 503 | NSE rate-limiting / cookie-warming failed AND yfinance fallback returned no data. Wait 1-2 minutes and retry; the chain is also memo-cached for 60s in-process. |
| Index dashboard is empty | No index refresh has run yet. Trigger `POST /admin/refresh-indices`. |
| Live Analysis tab shows nothing | App isn't in LIVE mode, or `LIVE_ANALYSIS_ENABLED=false`, or the scheduler isn't running. |

---

> **Disclaimer**
> This project is for research and decision-support only. Not financial advice.
