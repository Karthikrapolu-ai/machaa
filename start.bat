@echo off
cd /d "%~dp0"
echo Machaa will be at http://127.0.0.1:8787
echo Leave this window open. Press Ctrl+C to stop.
echo Word documents and social posts need GEMINI_API_KEY in a file named .env in this folder.
echo For Notepad, Calculator, and voice on Windows, double-click start-machaa-windows.bat instead.
echo Get a free key at https://aistudio.google.com/apikey
echo.
docker compose up --build
if errorlevel 1 (
  echo.
  echo Docker did not start. Install Docker Desktop, open it, and double-click this file again.
  echo https://www.docker.com/products/docker-desktop/
  pause
)
