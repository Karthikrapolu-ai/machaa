@echo off
setlocal EnableExtensions
cd /d "%~dp0"

call :find_python
if not defined PYBIN (
  echo Python was not found. Machaa will try to install Python 3.12 now.
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  set "PATH=%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts;%PATH%"
  call :find_python
)
if not defined PYBIN (
  echo Python is still missing. Install Python 3.12, tick Add python.exe to PATH, then double-click START-MACHAA.bat again.
  pause
  exit /b 1
)

"%PYBIN%" -c "import machaa" 1>nul 2>nul
if errorlevel 1 (
  echo Machaa was not found in this folder.
  echo Unzip the official Machaa download, copy your .env file into this folder, and double-click START-MACHAA.bat again.
  pause
  exit /b 1
)

if not exist data mkdir data
if not exist "%USERPROFILE%\Documents\Machaa" mkdir "%USERPROFILE%\Documents\Machaa"
if not exist data\companion.token (
  "%PYBIN%" -c "import secrets, pathlib; pathlib.Path('data/companion.token').write_text(secrets.token_urlsafe(32), encoding='utf-8')"
)
if not exist data\companion.ready (
  echo Installing the Companion requirements. This happens once.
  "%PYBIN%" -m pip install -r requirements-companion.txt
  if not errorlevel 1 echo ready>data\companion.ready
)

set /p MACHAA_COMPANION_TOKEN=<data\companion.token
set MACHAA_COMPANION_URL=http://host.docker.internal:8788
set MACHAA_DOCUMENTS_DIR=%USERPROFILE%\Documents\Machaa
set MACHAA_COMPANION_PORT=8788
set MACHAA_COMPANION_DOCKER=1

"%PYBIN%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8788/health', timeout=1).read()" 1>nul 2>nul
if errorlevel 1 goto launch_companion
goto companion_ready

:launch_companion
echo Starting the Windows Companion. Leave that window open.
start "Machaa Companion" /D "%CD%" "%PYBIN%" -m machaa.companion
set /a TRIES=0

:wait_companion
"%PYBIN%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8788/health', timeout=1).read()" 1>nul 2>nul
if not errorlevel 1 goto companion_ready
set /a TRIES+=1
if %TRIES% GEQ 30 goto companion_failed
timeout /t 1 /nobreak >nul
goto wait_companion

:companion_failed
echo The Windows Companion did not answer on this computer.
echo Leave the Machaa Companion window open, then double-click START-MACHAA.bat again.
pause
exit /b 1

:companion_ready
echo.
echo Machaa will also start the Companion when you sign in to Windows, so Notepad and Word can open.
echo A shortcut named Machaa Companion is in your Startup folder. Delete that shortcut if you do not want this.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$shell=New-Object -ComObject WScript.Shell; $link=$shell.CreateShortcut([Environment]::GetFolderPath('Startup')+'\Machaa Companion.lnk'); $link.TargetPath='%CD%\companion-login.bat'; $link.WorkingDirectory='%CD%'; $link.WindowStyle=7; $link.Save()"
echo.
"%PYBIN%" -m machaa.launcher start
if errorlevel 1 pause
exit /b %ERRORLEVEL%

:find_python
set "PYBIN="
where py >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYBIN=%%P"
)
if defined PYBIN exit /b 0
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PYBIN=%LocalAppData%\Programs\Python\Python312\python.exe"
if defined PYBIN exit /b 0
if exist "%ProgramFiles%\Python312\python.exe" set "PYBIN=%ProgramFiles%\Python312\python.exe"
if defined PYBIN exit /b 0
where python >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYBIN=%%P"
)
exit /b 0
