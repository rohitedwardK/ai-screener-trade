@echo off
REM ===========================================================================
REM AI Stock Screener - daily start
REM
REM Frees ports 8000 (FastAPI) and 5173 (Vite), then launches both processes
REM in their own windows. The agentic boot cycle fires automatically from the
REM FastAPI lifespan hook so you do not need to click anything after this.
REM
REM Re-runs are safe; the kill-by-port snippets short-circuit when the port
REM is already free.
REM ===========================================================================

setlocal enableextensions
cd /d "%~dp0"

echo [start] Freeing ports 8000 and 5173 if anything is bound...
powershell -NoProfile -Command "$p=Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue; if($p){Stop-Process -Id $p.OwningProcess -Force; Write-Host '[start] killed PID' $p.OwningProcess 'on :8000'}"
powershell -NoProfile -Command "$p=Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue; if($p){Stop-Process -Id $p.OwningProcess -Force; Write-Host '[start] killed PID' $p.OwningProcess 'on :5173'}"

if not exist "backend\.venv\Scripts\python.exe" (
  echo [start] ERROR: backend\.venv not found. Run "python -m venv backend\.venv" first.
  echo         See START.readme.md section 1 for the full first-time setup.
  exit /b 1
)

echo [start] Launching backend (FastAPI + APScheduler) in a new window...
start "AI Screener Backend" cmd /k "cd /d %~dp0backend && .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

echo [start] Launching frontend (Vite dev server) in a new window...
start "AI Screener Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

REM Give the backend ~5 seconds to bind before opening the browser. The agentic
REM boot cycle runs in a daemon thread so /docs comes up immediately even if
REM the boot cycle is still building the briefing.
echo [start] Waiting 5 seconds for the backend to come up...
timeout /t 5 /nobreak > nul

echo [start] Opening http://localhost:5173 ...
start "" "http://localhost:5173"

echo.
echo [start] Done. Two new windows are running the backend + frontend.
echo         Use stop.bat to shut both down. Logs live in those windows.
echo.
endlocal
