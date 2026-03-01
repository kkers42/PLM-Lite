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

echo.
echo  Server stopped. Press any key to close.
pause >nul
