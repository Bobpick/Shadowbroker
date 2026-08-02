@echo off
REM Windows launcher for nuke.sh (Git Bash / WSL)
setlocal
cd /d "%~dp0"
where bash >nul 2>&1
if %ERRORLEVEL%==0 (
  bash "%~dp0nuke.sh" %*
  exit /b %ERRORLEVEL%
)
where wsl >nul 2>&1
if %ERRORLEVEL%==0 (
  wsl -e bash "%~dp0nuke.sh" %*
  exit /b %ERRORLEVEL%
)
echo Install Git Bash or WSL to run nuke.sh
exit /b 1
