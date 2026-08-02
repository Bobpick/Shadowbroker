@echo off
REM Compatibility wrapper — scripts\operator\quick_restart.bat
call "%~dp0scripts\operator\quick_restart.bat" %*
exit /b %ERRORLEVEL%
