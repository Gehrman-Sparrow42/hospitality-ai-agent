@echo off
title WhatsApp AI Camp Assistant - WhatsApp Bridge
echo ===================================================
echo   Starting WhatsApp Web Bridge & QR Manager...
echo ===================================================
cd /d "%~dp0bridge"
if not exist "node_modules" (
    echo [INFO] Installing Node.js dependencies...
    npm install
)
node index.js
pause
