@echo off
cd /d "%~dp0"
echo.
echo Machaa on Windows
echo.
echo The first time you hold Talk, Windows asks for the microphone. Choose Allow.
echo Leave User Account Control on. Machaa will not click a Windows security box.
echo In the Machaa page, turn Desktop control on before you ask it to open Notepad.
echo You can always type. Voice is optional.
echo If Talk says the voice program is missing, search still works. To add voice later:
echo     py -3 -m pip install faster-whisper
echo.
py -3 -c "import machaa" 1>nul 2>nul
if errorlevel 1 (
  echo Python is not installed, or this folder is not the Machaa folder.
  echo Install Python once from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  echo Search still works if you double-click start.bat instead.
  echo Notepad and Calculator need this Python step.
  pause
  exit /b 1
)
if not exist data mkdir data
if not exist "%USERPROFILE%\Documents\Machaa" mkdir "%USERPROFILE%\Documents\Machaa"
if not exist data\companion.token (
  py -3 -c "import secrets, pathlib; pathlib.Path('data/companion.token').write_text(secrets.token_urlsafe(32), encoding='utf-8')"
)
set /p MACHAA_COMPANION_TOKEN=<data\companion.token
set MACHAA_COMPANION_URL=http://host.docker.internal:8788
set MACHAA_DOCUMENTS_DIR=%USERPROFILE%\Documents\Machaa
set MACHAA_COMPANION_PORT=8788
echo Starting the Windows Companion. Leave that window open.
start "Machaa Companion" /D "%CD%" py -3 -m machaa.companion
echo.
echo Machaa will be at http://127.0.0.1:8787
echo Leave this window open too. Press Ctrl+C to stop the dashboard.
echo Your .env file stays as it is, including GEMINI_API_KEY.
echo.
docker compose up --build
if errorlevel 1 (
  echo.
  echo Docker did not start. Install Docker Desktop, open it, and double-click this file again.
  echo https://www.docker.com/products/docker-desktop/
  pause
)
