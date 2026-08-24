@echo off
REM ===========================================================================
REM Live Market - daily start
REM
REM Frees ports 8001 (FastAPI) and 5174 (Vite), then launches both processes
REM in their own windows. The 1-minute APScheduler tick wires up automatically
REM in the FastAPI lifespan hook; nothing else to click.
REM
REM Re-runs are safe - the kill-by-port snippets short-circuit when the port
REM is already free. Runs side-by-side with the parent app on :8000 / :5173.
REM ===========================================================================

setlocal enableextensions
cd /d "%~dp0"

echo [live-market] Freeing ports 8001 and 5174 if anything is bound...
powershell -NoProfile -Command "$p=Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue; if($p){Stop-Process -Id $p.OwningProcess -Force; Write-Host '[live-market] killed PID' $p.OwningProcess 'on :8001'}"
powershell -NoProfile -Command "$p=Get-NetTCPConnection -LocalPort 5174 -State Listen -ErrorAction SilentlyContinue; if($p){Stop-Process -Id $p.OwningProcess -Force; Write-Host '[live-market] killed PID' $p.OwningProcess 'on :5174'}"

REM We share the parent app's venv to avoid a second 1GB+ install. The
REM live-market service deps are a strict subset of the parent's, so any
REM working backend\.venv satisfies live-market's requirements as well.
if not exist "backend\.venv\Scripts\python.exe" (
  echo [live-market] ERROR: backend\.venv not found. Run "python -m venv backend\.venv" first.
  echo                See START.readme.md for the full first-time setup.
  exit /b 1
)

if not exist "live-market\frontend\node_modules" (
  echo [live-market] ERROR: live-market\frontend\node_modules not found.
  echo                Run "cd live-market\frontend && npm install" first.
  exit /b 1
)

REM Force the Program Files Node ahead of any stale npm shims in
REM %APPDATA%\npm (leftovers from older Node installs that the Node 22+
REM installer does not clean up). Without this, the child cmd windows
REM inherit PATH with the old npm 6 shim first and Vite refuses to start.
set "NODE_DIR=C:\Program Files\nodejs"
if exist "%NODE_DIR%\node.exe" set "PATH=%NODE_DIR%;%PATH%"

echo [live-market] Launching backend (FastAPI + APScheduler) on :8001 in a new window...
start "Live Market Backend" cmd /k "cd /d %~dp0live-market\backend && ..\..\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001"

echo [live-market] Launching frontend (Vite dev server) on :5174 in a new window...
start "Live Market Frontend" cmd /k "cd /d %~dp0live-market\frontend && npm run dev"

echo [live-market] Waiting 5 seconds for the backend to come up...
timeout /t 5 /nobreak > nul

echo [live-market] Opening http://localhost:5174 ...
start "" "http://localhost:5174"

echo.
echo [live-market] Done. Two new windows are running the backend + frontend.
echo               Use stop-live-market.bat to shut both down.
echo.
endlocal
