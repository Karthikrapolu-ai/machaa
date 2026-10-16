@echo off
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
  echo Python was not found.
  echo Install Python from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  echo Then double-click START-MACHAA.bat again.
  echo Search can still start from start.bat after Docker Desktop is open.
  pause
  exit /b 1
)
py -3 -c "import machaa" 1>nul 2>nul
if errorlevel 1 (
  echo Machaa was not found in this folder.
  echo Unzip the official Machaa download, copy your .env file into this folder, and double-click START-MACHAA.bat again.
  pause
  exit /b 1
)
py -3 -m machaa.launcher start
if errorlevel 1 pause
