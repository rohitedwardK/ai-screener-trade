@echo off
REM ===========================================================================
REM Live Market - daily stop
REM
REM Kills whatever is bound to ports 8001 and 5174. Safe to re-run; no
REM error if nothing is bound. Leaves the parent app on :8000 / :5173
REM untouched.
REM ===========================================================================

setlocal enableextensions

echo [live-market stop] Stopping backend on :8001 ...
powershell -NoProfile -Command "$p=Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue; if($p){Stop-Process -Id $p.OwningProcess -Force; Write-Host '[live-market stop] killed PID' $p.OwningProcess 'on :8001'} else { Write-Host '[live-market stop] :8001 already free' }"

echo [live-market stop] Stopping frontend on :5174 ...
powershell -NoProfile -Command "$p=Get-NetTCPConnection -LocalPort 5174 -State Listen -ErrorAction SilentlyContinue; if($p){Stop-Process -Id $p.OwningProcess -Force; Write-Host '[live-market stop] killed PID' $p.OwningProcess 'on :5174'} else { Write-Host '[live-market stop] :5174 already free' }"

echo.
echo [live-market stop] Done.
echo.
endlocal
