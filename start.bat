@echo off
title PLM Lite Server

REM Check if .env exists, if not copy from .env.example
if not exist "%~dp0.env" (
    if exist "%~dp0.env.example" (
        copy "%~dp0.env.example" "%~dp0.env" >nul
        echo Created .env from .env.example
    )
)

echo.
echo  ==========================================
echo   PLM Lite - Starting server...
echo  ==========================================
echo.
echo  Opening browser in 3 seconds...
echo  Press Ctrl+C in this window to stop.
echo.

REM Open browser after a short delay
start /b cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8080"

REM Run the server
"%~dp0plmlite-server.exe"
set EXIT_CODE=%ERRORLEVEL%

echo.
if %EXIT_CODE% neq 0 (
    echo  *** SERVER CRASHED with exit code %EXIT_CODE% ***
    echo  *** Check above for the error message ***
    echo  *** Screenshot this window and report the error ***
) else (
    echo  Server stopped.
)
echo  Press any key to close.
pause >nul
