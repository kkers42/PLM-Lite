@echo off
title PLM Lite Agent — %USERNAME%@%COMPUTERNAME%
cd /d "%~dp0"

echo ============================================================
echo  PLM Lite Local Agent
echo  User   : %USERNAME%
echo  Machine: %COMPUTERNAME%
echo  Port   : 127.0.0.1:9090  (localhost only)
echo ============================================================
echo.
echo  This agent allows PLM Lite to open files in YOUR Windows session.
echo  Keep this window open while using PLM Lite.
echo  Press Ctrl+C to stop.
echo.

python "%~dp0src\plmlite\agent.py"

pause
