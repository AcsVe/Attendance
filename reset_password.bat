@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ATTENDANCE - Reset a user password
call scripts\find_python.bat
set PYTHONUTF8=1
"%PY%" ops\reset_password.py
echo.
pause
