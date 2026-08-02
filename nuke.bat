@echo off
REM Compatibility wrapper — scripts\operator\nuke.bat
call "%~dp0scripts\operator\nuke.bat" %*
exit /b %ERRORLEVEL%
