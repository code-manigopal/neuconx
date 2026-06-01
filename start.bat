@echo off
title MultiMind — AI Platform
color 0A

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║          MultiMind AI Platform           ║
echo  ║       Your Personal AI. Always Free.     ║
echo  ╚══════════════════════════════════════════╝
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Install from python.org
    pause
    exit /b 1
)

:: Create .env if missing
if not exist .env (
    echo  [INFO] Creating .env from template...
    copy .env.example .env >nul
    echo  [INFO] Open .env and add your API keys, then restart.
)

:: Install dependencies
echo  [INFO] Checking dependencies...
pip install -r requirements.txt --quiet --break-system-packages

echo.
echo  [READY] Opening http://localhost:5050
echo  [INFO]  Press Ctrl+C to stop.
echo.

:: Open browser after 2 seconds
start /b cmd /c "timeout /t 2 >nul && start http://localhost:5050"

:: Launch Flask
python app.py

pause
