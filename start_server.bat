@echo off
title PLM Lite v2.1 — Web Server
cd /d "%~dp0"

echo ============================================================
echo  PLM Lite v2.1  —  Web Interface
echo ============================================================
echo.
echo  Starting server at http://localhost:8080
echo  Open your browser to: http://localhost:8080
echo.
echo  Press Ctrl+C to stop.
echo ============================================================
echo.

set PYTHONPATH=src
python -m uvicorn plmlite.server:app --host 0.0.0.0 --port 8080

pause
