@echo off
setlocal EnableDelayedExpansion
title NeuConX Installer
color 0B
cls

echo.
echo  =====================================================
echo   NeuConX - AI Platform Installer
echo   Multiple minds. One truth. Always free.
echo  =====================================================
echo.

:: ── Step 1: Check Python ──────────────────────────────────────────────────────
echo [1/6] Checking Python installation...

python --version >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=2" %%V in ('python --version 2^>^&1') do set PYVER=%%V
    echo       Found Python !PYVER!
) else (
    echo       Python not found. Opening download page...
    echo       Please install Python 3.10+ and tick "Add Python to PATH"
    start https://www.python.org/downloads/
    echo.
    echo       After installing Python, close this window and run install.bat again.
    pause
    exit /b 1
)

:: Check version is 3.10+
python -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo       Python 3.10+ required. Please upgrade at python.org/downloads
    pause
    exit /b 1
)

:: ── Step 2: Upgrade pip ───────────────────────────────────────────────────────
echo.
echo [2/6] Upgrading pip...
python -m pip install --upgrade pip --quiet --break-system-packages 2>nul
python -m pip install --upgrade pip --quiet 2>nul
echo       Done.

:: ── Step 3: Install core dependencies ────────────────────────────────────────
echo.
echo [3/6] Installing core dependencies...
echo       This may take 1-2 minutes on first run.

pip install Flask==3.0.3 Werkzeug==3.0.3 Flask-Limiter==3.7.0 bleach==6.1.0 python-dotenv==1.0.1 google-generativeai==0.8.3 requests==2.32.3 urllib3==2.2.2 --break-system-packages --quiet 2>nul
pip install Flask==3.0.3 Werkzeug==3.0.3 Flask-Limiter==3.7.0 bleach==6.1.0 python-dotenv==1.0.1 google-generativeai==0.8.3 requests==2.32.3 urllib3==2.2.2 --quiet 2>nul

if %errorlevel% neq 0 (
    echo       Failed to install dependencies. Check your internet connection.
    pause
    exit /b 1
)
echo       Core dependencies installed.

:: ── Step 4: Optional - ChromaDB for semantic memory ──────────────────────────
echo.
echo [4/6] Installing optional semantic memory (ChromaDB)...
echo       This downloads ~500MB model on first use. Skip with N.
echo.
set /p CHROMA="       Install ChromaDB for semantic search? [Y/N]: "
if /i "!CHROMA!"=="Y" (
    pip install chromadb==0.6.3 sentence-transformers==3.2.1 --break-system-packages --quiet 2>nul
    pip install chromadb==0.6.3 sentence-transformers==3.2.1 --quiet 2>nul
    echo       ChromaDB installed. First run will download ~80MB embedding model.
) else (
    echo       Skipped. You can install later: pip install chromadb sentence-transformers
)

:: ── Step 5: Create .env file ─────────────────────────────────────────────────
echo.
echo [5/6] Setting up configuration...

if exist ".env" (
    echo       .env already exists - keeping your existing keys.
) else (
    echo       Creating .env from template...
    copy ".env.example" ".env" >nul 2>&1
    if not exist ".env" (
        :: Create minimal .env if no example exists
        python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))" > .env
        echo GEMINI_API_KEY= >> .env
        echo GROQ_API_KEY= >> .env
        echo CEREBRAS_API_KEY= >> .env
        echo NVIDIA_API_KEY= >> .env
        echo OPENROUTER_API_KEY= >> .env
        echo OLLAMA_MODEL= >> .env
        echo OLLAMA_BASE_URL=http://localhost:11434 >> .env
    ) else (
        :: Add SECRET_KEY to .env if missing
        findstr /C:"SECRET_KEY" .env >nul 2>&1
        if %errorlevel% neq 0 (
            python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))" >> .env
        )
    )
    echo       .env created. Add your API keys before starting.
)

:: Create data directories
if not exist "data" mkdir data
if not exist "data\conversations" mkdir data\conversations

:: ── Step 6: Done ──────────────────────────────────────────────────────────────
echo.
echo [6/6] Installation complete!
echo.
echo  =====================================================
echo   NEXT STEPS:
echo  =====================================================
echo.
echo   1. Add at least one API key to your .env file:
echo        notepad .env
echo.
echo      Recommended (free):
echo        GROQ_API_KEY=gsk_...    (console.groq.com)
echo        GEMINI_API_KEY=AIza...  (aistudio.google.com)
echo.
echo   2. Start NeuConX:
echo        start.bat
echo.
echo   3. Open in browser:
echo        http://localhost:5050
echo.
echo   For Ollama (local AI, no API key needed):
echo     - Download: https://ollama.com/download
echo     - Run: ollama pull llama3.2
echo  =====================================================
echo.
pause
