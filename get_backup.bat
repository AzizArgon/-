@echo off
rem Downloads the newest database backup of the public site to F:\claudy\backups\server\ (docs/deploy.md).
cd /d "%~dp0"
set BASH=%ProgramFiles%\Git\usr\bin\bash.exe
if not exist "%BASH%" set BASH=%ProgramFiles%\Git\bin\bash.exe
"%BASH%" -lc "cd \"$(cygpath '%~dp0')\" && bash deploy/get_backup.sh"
pause
