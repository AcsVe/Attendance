@echo off
cd /d "%~dp0"
net session >nul 2>nul || (echo [X] Run as administrator. & pause & exit /b 1)
schtasks /end /tn "ATTENDANCE Website" >nul 2>nul
schtasks /delete /f /tn "ATTENDANCE Website" >nul 2>nul
schtasks /delete /f /tn "ATTENDANCE Hourly Backup" >nul 2>nul
schtasks /delete /f /tn "ATTENDANCE Failover Watchdog" >nul 2>nul
echo Stopped and removed the ATTENDANCE tasks.
pause
