@echo off
rem Updates the public site pcmarket.khudoberdi.uz: push, server update, frontend build, restart, check.
rem Details - docs/deploy.md. Needs Git for Windows (bash, ssh) and the SSH key of the server.
cd /d "%~dp0"
set BASH=%ProgramFiles%\Git\usr\bin\bash.exe
if not exist "%BASH%" set BASH=%ProgramFiles%\Git\bin\bash.exe
if not exist "%BASH%" (
    echo Git for Windows not found
    pause
    exit /b 1
)
"%BASH%" -lc "cd \"$(cygpath '%~dp0')\" && bash deploy/deploy.sh"
if errorlevel 1 (
    echo Deploy failed, see the messages above.
    pause
    exit /b 1
)
pause
