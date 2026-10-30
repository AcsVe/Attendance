@echo off
chcp 65001 >nul
title Page protection OFF
cd /d "%~dp0"
net session >nul 2>nul || (echo [X] Right-click this file and choose "Run as administrator". & pause & exit /b 1)
call scripts\find_python.bat
REM Turns OFF: page encryption + developer-tools detection + right-click blocking
"%PY%" ops\setenv.py PAGE_SHIELD 0 >nul
schtasks /end /tn "ATTENDANCE Website" >nul 2>nul
"%SystemRoot%\System32\timeout.exe" /t 2 >nul
schtasks /run /tn "ATTENDANCE Website" >nul 2>nul
echo.
echo   Page protection is OFF (source visible, right-click and developer tools allowed).
echo   To turn it back on: protection_on.bat (as administrator)
echo.
pause
