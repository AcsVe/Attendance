@echo off
chcp 65001 >nul
title ATTENDANCE - Update from GitHub
cd /d "%~dp0"
REM Pulls the latest code from GitHub - data (.env, data, backups) is never touched
where git >nul 2>nul || (echo [X] Git is not installed. & pause & exit /b 1)
call scripts\find_python.bat
set PYTHONUTF8=1
if not exist .git (
  git init -q
  git remote add origin https://github.com/AcsVe/attendance.git
  git fetch -q origin main || (echo [X] Could not reach GitHub & pause & exit /b 1)
  git reset -q --hard origin/main
  git branch -q -M main
  git branch -q --set-upstream-to=origin/main main
) else (
  echo Downloading the latest version...
  git fetch -q origin main || (echo [X] Could not reach GitHub & pause & exit /b 1)
  git reset -q --hard origin/main
)
echo Now at:
git log -1 --oneline
"%PY%" -m pip install -q --disable-pip-version-check -r requirements.txt
schtasks /query /tn "ATTENDANCE Website" >nul 2>nul
if errorlevel 1 goto manual
net session >nul 2>nul || (echo. & echo [!] To restart automatically, run this file as administrator. Or restart the PC. & pause & exit /b 0)
schtasks /end /tn "ATTENDANCE Website" >nul 2>nul
timeout /t 2 >nul
schtasks /run /tn "ATTENDANCE Website" >nul 2>nul
if errorlevel 1 (
  echo.
  echo Code updated, but the attendance system is switched OFF ^(att_off.bat was used^).
  echo To turn it on: run att_on.bat as administrator.
  pause
  exit /b 0
)
echo.
echo Done. ATTENDANCE was restarted with the new version.
pause
exit /b 0
:manual
echo.
echo Done. Close 2_start.bat and open it again to use the new version.
pause
