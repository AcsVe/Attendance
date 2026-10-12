@echo off
chcp 65001 >nul
title Link backups to Neon (second cloud copy)
cd /d "%~dp0"
call scripts\find_python.bat
set PYTHONUTF8=1
"%PY%" -m pip install -q --disable-pip-version-check pg8000==1.31.5 >nul 2>nul
REM Saves the Neon link in .env, tests it, then runs a backup (uploads the first copy to Neon)
"%PY%" ops\neon_link.py ops\backup.py
echo.
echo   From now on every hourly backup also goes to Neon (only when the data changed).
pause
