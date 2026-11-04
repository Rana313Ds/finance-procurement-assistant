@echo off
rem Stops the Finance Procurement Assistant servers (ports 8000 and 5173).
for %%p in (8000 5173) do (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":%%p .*LISTENING"') do taskkill /T /F /PID %%a >nul 2>&1
)
taskkill /F /FI "WINDOWTITLE eq Finance Assistant - Backend*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Finance Assistant - Frontend*" >nul 2>&1
echo Finance Assistant stopped.
timeout /t 2 /nobreak >nul
