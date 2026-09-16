@echo off
title WhatsApp Camp Bot - Stop All Processes
color 0c
echo ========================================================
echo   WhatsApp AI Camp Assistant - Stopping All Processes
echo ========================================================
echo.

echo [1/3] Terminating Node.js WhatsApp Bridge processes...
taskkill /F /IM node.exe >nul 2>&1

echo [2/3] Terminating Python/Uvicorn Backend processes...
taskkill /F /IM uvicorn.exe >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq WhatsApp Camp Assistant - Backend*" >nul 2>&1

echo [3/3] Terminating background Chromium/Puppeteer processes...
taskkill /F /IM chrome.exe /FI "STATUS eq RUNNING" /FI "MEMUSAGE gt 50000" >nul 2>&1

echo.
echo ========================================================
echo   All background processes have been terminated.
echo ========================================================
echo.
pause
