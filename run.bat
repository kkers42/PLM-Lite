@echo off
title PLM Lite v1.0

:: ── Check Python ────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ and try again.
    pause
    exit /b 1
)

:: ── Install dependencies if needed ──────────────────────────────────
if not exist "%~dp0.venv\Scripts\activate.bat" (
    echo First run: creating virtual environment...
    python -m venv "%~dp0.venv"
    call "%~dp0.venv\Scripts\activate.bat"
    echo Installing dependencies...
    pip install -r "%~dp0requirements.txt"
) else (
    call "%~dp0.venv\Scripts\activate.bat"
)

:: ── Create default .env if missing ──────────────────────────────────
if not exist "%~dp0.env" (
    echo Creating default .env for local mode...
    (
        echo AUTH_MODE=local
        echo SECRET_KEY=plm-local-secret-change-me
        echo APP_BASE_URL=http://localhost:8080
        echo FILES_ROOT=%~dp0data\files
        echo DB_PATH=%~dp0data\plm.db
        echo MAX_FILE_VERSIONS=3
    ) > "%~dp0.env"
)

:: ── Create data directories ──────────────────────────────────────────
if not exist "%~dp0data\files" mkdir "%~dp0data\files"

:: ── Start server ────────────────────────────────────────────────────
echo.
echo  PLM Lite v1.0 - Local Server
echo  URL:   http://localhost:8080
echo  DB:    %~dp0data\plm.db
echo  Files: %~dp0data\files
echo  Press Ctrl+C to stop
echo.

cd /d "%~dp0"
start "" "http://localhost:8080/login"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080

pause
