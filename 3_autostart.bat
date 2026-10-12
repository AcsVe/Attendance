@echo off
chcp 65001 >nul
title ATTENDANCE - Start with Windows + hourly backup + watchdog
cd /d "%~dp0"
net session >nul 2>nul || (echo [X] Right-click this file and choose "Run as administrator". & pause & exit /b 1)
call scripts\find_python.bat
if not exist .env (echo [X] Run 1_setup.bat first & pause & exit /b 1)
"%PY%" -c "import sys; print(sys.executable)" > "%TEMP%\attendance_py.txt"
set /p PYFULL=<"%TEMP%\attendance_py.txt"
set "SITE=%~dp0"
set "SITE=%SITE:~0,-1%"
schtasks /end /tn "ATTENDANCE Website" >nul 2>nul
schtasks /create /f /tn "ATTENDANCE Website" /sc onstart /ru SYSTEM /rl highest /tr "\"%PYFULL%\" \"%SITE%\serve.py\"" || (echo [X] Could not create the startup task & pause & exit /b 1)
schtasks /create /f /tn "ATTENDANCE Hourly Backup" /sc hourly /mo 1 /ru SYSTEM /rl highest /tr "\"%PYFULL%\" \"%SITE%\ops\backup.py\"" >nul || echo [!] Could not create the backup task
schtasks /create /f /tn "ATTENDANCE Failover Watchdog" /sc minute /mo 5 /ru SYSTEM /rl highest /tr "\"%PYFULL%\" \"%SITE%\ops\cf.py\" auto" >nul || echo [!] Could not create the watchdog task
powercfg /change standby-timeout-ac 0 >nul 2>nul
schtasks /run /tn "ATTENDANCE Website" >nul
echo.
echo   Done. ATTENDANCE starts with Windows (port 8003), backs up every hour,
echo   and the watchdog checks every 5 minutes. Log: logs\server.log
timeout /t 5 >nul
start "" http://localhost:8003/
pause
