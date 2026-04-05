@echo off
title PLM Lite v2.2 — %USERNAME%
cd /d "%~dp0"

:: Allow optional port override: start_server.bat 8081
set PORT=%1
if "%PORT%"=="" set PORT=8080

echo ============================================================
echo  PLM Lite v2.2
echo  User   : %USERNAME%
echo  Machine: %COMPUTERNAME%
echo  Port   : %PORT%
echo ============================================================
echo.
echo  Starting server...
echo  Press Ctrl+C to stop.
echo.

:: Kill any existing process on the same port
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%PORT% " ^| findstr LISTENING') do (
    echo  Killing previous process on port %PORT% (PID %%a)...
    taskkill /PID %%a /F >nul 2>&1
)

:: Open browser after 3 second delay (in background)
start "" /B cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:%PORT%"

python "%~dp0run_server.py" %PORT%

pause
