@echo off
rem Starts the Finance Procurement Assistant: backend (port 8000) + frontend (port 5173), then opens the app.
set "ROOT=%~dp0"
set "URL=http://localhost:5173"

if not exist "%ROOT%backend\.venv\Scripts\python.exe" (
  echo Setting up backend virtual environment...
  python -m venv "%ROOT%backend\.venv" || (echo Python not found & pause & exit /b 1)
  "%ROOT%backend\.venv\Scripts\python.exe" -m pip install -r "%ROOT%backend\requirements.txt" || (pause & exit /b 1)
)
if not exist "%ROOT%frontend\node_modules" (
  echo Installing frontend dependencies...
  pushd "%ROOT%frontend" & call npm install || (popd & pause & exit /b 1)
  popd
)

rem Only start a server if it is not already running, so a second click just reopens the app.
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul || (
  start "Finance Assistant - Backend" /min /D "%ROOT%backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
)
netstat -ano | findstr /R /C:":5173 .*LISTENING" >nul || (
  start "Finance Assistant - Frontend" /min /D "%ROOT%frontend" cmd /k "npm run dev"
)

rem Wait until the app answers (up to ~30 seconds).
for /L %%i in (1,1,30) do (
  powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing %URL%/api/summary -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1 && goto open
  timeout /t 1 /nobreak >nul
)

:open
rem Open as a clean app window (no tabs or address bar) if Edge is available, else the default browser.
set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" set "EDGE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if exist "%EDGE%" (
  start "" "%EDGE%" --app=%URL% --start-maximized
) else (
  start "" %URL%
)
