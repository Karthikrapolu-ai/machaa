@echo off
cd /d "%~dp0"
if not exist data\companion.token exit /b 0
set /p MACHAA_COMPANION_TOKEN=<data\companion.token
set MACHAA_DOCUMENTS_DIR=%USERPROFILE%\Documents\Machaa
set MACHAA_COMPANION_PORT=8788
set MACHAA_COMPANION_DOCKER=1
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8788/health', timeout=1).read()" 1>nul 2>nul
  if not errorlevel 1 exit /b 0
  py -3 -m machaa.companion
  exit /b 0
)
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
  "%LocalAppData%\Programs\Python\Python312\python.exe" -m machaa.companion
)
exit /b 0
