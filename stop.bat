@echo off
rem Stops backend (uvicorn) and frontend (vite). uvicorn --reload spawns worker processes
rem that can outlive the parent, so processes are matched by command line and ports, a few passes.
powershell -NoProfile -Command "for ($i = 0; $i -lt 3; $i++) { Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|node)\.exe$' -and ($_.CommandLine -match 'uvicorn main:app' -or $_.CommandLine -match 'spawn_main' -or $_.CommandLine -match 'diplom.frontend') } | ForEach-Object { taskkill /pid $_.ProcessId /t /f 2>$null | Out-Null }; foreach ($p in 8000,5173) { Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | ForEach-Object { taskkill /pid $_.OwningProcess /t /f 2>$null | Out-Null } }; Start-Sleep -Milliseconds 700 }"
taskkill /fi "WINDOWTITLE eq pc_market backend*" /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq pc_market frontend*" /f >nul 2>&1
echo Servers stopped.
ping -n 3 127.0.0.1 >nul
