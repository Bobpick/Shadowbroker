@echo off
REM Windows launcher for quick_restart.sh (Git Bash / WSL)
setlocal
cd /d "%~dp0"
where bash >nul 2>&1
if %ERRORLEVEL%==0 (
  bash "%~dp0quick_restart.sh" %*
  exit /b %ERRORLEVEL%
)
where wsl >nul 2>&1
if %ERRORLEVEL%==0 (
  wsl -e bash "%~dp0quick_restart.sh" %*
  exit /b %ERRORLEVEL%
)
echo Install Git Bash or WSL, or run: docker compose restart
exit /b 1
