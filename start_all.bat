@echo off
title WhatsApp AI Camp Assistant - Master Launcher
echo ===================================================
echo   Starting WhatsApp AI Camp Assistant System...
echo ===================================================

echo [INFO] Temizleme yapiliyor (onceki uvicorn ve node arka plan surecleri sonlandiriliyor)...
taskkill /F /IM uvicorn.exe >nul 2>&1
taskkill /F /IM node.exe >nul 2>&1
timeout /t 1 /nobreak >nul

echo [1/2] Starting Python FastAPI Backend (Port 8000)...
start "WhatsApp AI - Backend (Port 8000)" cmd /k "%~dp0start_backend.bat"

timeout /t 2 /nobreak >nul

echo [2/2] Starting Node.js WhatsApp Bridge (Port 3001)...
start "WhatsApp AI - Bridge (Port 3001)" cmd /k "%~dp0start_bridge.bat"

echo.
echo ===================================================
echo   All services launched! 
echo   Dashboard: http://localhost:8000
echo ===================================================
