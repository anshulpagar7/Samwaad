@echo off
REM Launches Samwaad: starts the local server (127.0.0.1 only) and opens the app window in Edge.
title Samwaad
cd /d "%~dp0\.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m samwaad app
) else if exist "Samwaad.exe" (
  "Samwaad.exe"
) else (
  echo Samwaad is not installed yet - run scripts\setup.bat first.
  pause
)
