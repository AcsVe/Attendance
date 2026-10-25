@echo off
chcp 65001 >nul
title ATTENDANCE - Android app keys
cd /d "%~dp0"
REM Copies the 4 GitHub secrets (one at a time, to the clipboard) and creates the new app key once. Safe to run again.
call scripts\find_python.bat
set PYTHONUTF8=1
if errorlevel 1 goto :end
"%PY%" ops\app_key.py %*
:end
echo.
pause
