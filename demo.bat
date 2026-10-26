@echo off
rem Demo mode from scratch: backup of the current DB -> clean DB -> categories -> cache -> real price list
rem -> demo stores -> Gshop archive -> servers -> browser on the catalog. No live AI requests.
rem "demo.bat live" - the files of samples\demo are parsed by the real AI during the show (no cache for them).
cd /d "%~dp0"

if not exist "backend\.venv\Scripts\python.exe" (
    echo Backend venv not found. See the run section in CLAUDE.md
    pause
    exit /b 1
)

echo Stopping servers...
call "%~dp0stop.bat" >nul

set LIVE=
if /i "%~1"=="live" set LIVE=--live
set PYTHONIOENCODING=utf8
pushd backend
.venv\Scripts\python.exe scripts\demo_reset.py %LIVE% > "%TEMP%\pc_market_demo.log" 2>&1
if errorlevel 1 (
    popd
    type "%TEMP%\pc_market_demo.log"
    echo Demo data were not prepared, see the log above.
    pause
    exit /b 1
)
popd
findstr /b /c:"backup" /c:"price list" /c:"{" /c:"Gshop" /c:"demo data" "%TEMP%\pc_market_demo.log"

call "%~dp0start.bat"
