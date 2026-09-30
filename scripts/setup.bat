@echo off
REM Double-click me: installs Samwaad (Python venv, packages, models), creates shortcuts, opens the app.
cd /d "%~dp0\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_windows.ps1" %*
if errorlevel 1 (
  echo.
  echo Setup hit a problem - see the message above. Re-run after fixing it.
  pause
)
