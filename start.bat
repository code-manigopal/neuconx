@echo off
setlocal EnableDelayedExpansion
title NeuConX
color 0B
cls

echo.
echo  Welcome to NeuConX - Starting...
echo.

:: ── Find Python ───────────────────────────────────────────────────────────────
set PYTHON_CMD=

python --version >nul 2>&1
if %errorlevel% equ 0 ( set PYTHON_CMD=python & goto :check )

python3 --version >nul 2>&1
if %errorlevel% equ 0 ( set PYTHON_CMD=python3 & goto :check )

py --version >nul 2>&1
if %errorlevel% equ 0 ( set PYTHON_CMD=py & goto :check )

color 0C
echo  ERROR: Python not found.
echo  Please run install.bat first.
pause
exit /b 1

:: ── Check Flask installed ─────────────────────────────────────────────────────
:check
%PYTHON_CMD% -c "import flask" >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo  ERROR: NeuConX dependencies are not installed.
    echo  Please run install.bat first, then try again.
    echo.
    pause
    exit /b 1
)

:: ── Check .env exists ─────────────────────────────────────────────────────────
if not exist ".env" (
    color 0E
    echo  WARNING: No .env file found.
    echo  Please run install.bat to complete setup.
    echo.
    pause
    exit /b 1
)

:: ── Launch ────────────────────────────────────────────────────────────────────
echo  Running on http://localhost:5050
echo  Press Ctrl+C to stop.
echo.

start /b cmd /c "timeout /t 2 >nul && start http://localhost:5050"

%PYTHON_CMD% app.py

pause