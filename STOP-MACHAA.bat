@echo off
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
  echo Python was not found, so Machaa could not be stopped from here.
  echo Close the Machaa window, or press Ctrl+C in it.
  pause
  exit /b 1
)
py -3 -m machaa.launcher stop
if errorlevel 1 pause
