@echo off
chcp 65001 >nul
title ATTENDANCE - Turn the attendance system ON
net session >nul 2>nul || (echo [X] Right-click this file and choose "Run as administrator". & pause & exit /b 1)
schtasks /change /tn "ATTENDANCE Website" /enable >nul 2>nul || (echo [X] The startup task is missing - run 3_autostart.bat as administrator & pause & exit /b 1)
schtasks /run /tn "ATTENDANCE Website" >nul
echo.
echo   3.iajaward.org (attendance) is ON again (starts with Windows as before).
echo.
pause
