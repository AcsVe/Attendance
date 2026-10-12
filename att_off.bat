@echo off
chcp 65001 >nul
title ATTENDANCE - Turn the attendance system OFF
net session >nul 2>nul || (echo [X] Right-click this file and choose "Run as administrator". & pause & exit /b 1)
REM Stops 3.iajaward.org only - the award website (iajaward.org) keeps running
schtasks /end /tn "ATTENDANCE Website" >nul 2>nul
schtasks /change /tn "ATTENDANCE Website" /disable >nul 2>nul
echo.
echo   3.iajaward.org (attendance) is OFF (also after restarting the PC).
echo   iajaward.org is still running.
echo   To turn it back on: att_on.bat (as administrator)
echo.
pause
