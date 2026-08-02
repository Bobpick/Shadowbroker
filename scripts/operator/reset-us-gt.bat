@echo off
REM Windows wrapper for US Game Theory full reset (requires Git Bash or WSL).
REM Prefer running from WSL/Git Bash:  bash reset-us-gt.sh
REM
REM This batch file calls the shell script when bash is available.

setlocal
cd /d "%~dp0"

where bash >nul 2>&1
if %ERRORLEVEL%==0 (
  bash "./reset-us-gt.sh" %*
  exit /b %ERRORLEVEL%
)

where wsl >nul 2>&1
if %ERRORLEVEL%==0 (
  wsl -e bash "./reset-us-gt.sh" %*
  exit /b %ERRORLEVEL%
)

echo [!] No bash/WSL found. On Windows install Git Bash or WSL, then run:
echo     bash reset-us-gt.sh
echo     bash reset-us-gt.sh --wipe-data
exit /b 1
