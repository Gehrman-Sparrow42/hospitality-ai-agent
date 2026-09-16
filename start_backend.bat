@echo off
title WhatsApp AI Camp Assistant - Backend Server (Port 8000)
echo ===================================================
echo   Starting WhatsApp AI Camp Assistant Backend...
echo ===================================================
cd /d "%~dp0backend"
if exist "%~dp0..\.venv\Scripts\activate.bat" (
    call "%~dp0..\.venv\Scripts\activate.bat"
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo [INFO] Creating Python virtual environment...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
)
echo [INFO] Backend is running on http://localhost:8000
start http://localhost:8000
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
pause
