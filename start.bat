@echo off
rem Starts backend and frontend in two windows and opens the site
cd /d "%~dp0"

if not exist "backend\.venv\Scripts\python.exe" (
    echo Backend venv not found. See the run section in CLAUDE.md
    pause
    exit /b 1
)
if not exist "frontend\node_modules" (
    echo Installing frontend packages, first run only...
    call npm install --prefix frontend
)

start "pc_market backend" /d "%~dp0backend" cmd /k ".venv\Scripts\python.exe -m uvicorn main:app --reload"
start "pc_market frontend" /d "%~dp0frontend" cmd /k "npm run dev"

timeout /t 5 /nobreak >nul
start http://localhost:5173
