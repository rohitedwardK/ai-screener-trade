@echo off
REM ===========================================================================
REM AI Stock Screener - daily stop
REM
REM Kills whatever is bound to ports 8000 and 5173. The two cmd windows
REM opened by start.bat will close on their own once their child process
REM exits. Safe to re-run; no error if nothing is bound.
REM ===========================================================================

setlocal enableextensions

echo [stop] Stopping backend on :8000 ...
powershell -NoProfile -Command "$p=Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue; if($p){Stop-Process -Id $p.OwningProcess -Force; Write-Host '[stop] killed PID' $p.OwningProcess 'on :8000'} else { Write-Host '[stop] :8000 already free' }"

echo [stop] Stopping frontend on :5173 ...
powershell -NoProfile -Command "$p=Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue; if($p){Stop-Process -Id $p.OwningProcess -Force; Write-Host '[stop] killed PID' $p.OwningProcess 'on :5173'} else { Write-Host '[stop] :5173 already free' }"

echo.
echo [stop] Done.
echo.
endlocal
