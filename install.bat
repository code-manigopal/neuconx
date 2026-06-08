@echo off
setlocal EnableDelayedExpansion
title NeuConX Installer
color 0A
cls

echo.
echo  =====================================================
echo   NeuConX - First Time Setup
echo   Multiple minds. One truth. Always free.
echo  =====================================================
echo.
echo  Welcome! This installer sets up everything NeuConX
echo  needs to run. It only needs to run ONCE.
echo.
echo  What this installer does:
echo    1. Checks that Python is installed
echo    2. Installs all required Python packages
echo    3. Optionally installs AI memory (ChromaDB)
echo    4. Creates your personal settings file (.env)
echo    5. Guides you to get your first free API key
echo.
echo  Time needed: 3-5 minutes
echo  Internet connection: required
echo.
pause

:: ================================================================
echo.
echo  -------------------------------------------------------
echo   STEP 1 of 6 - Checking Python
echo  -------------------------------------------------------
echo.
echo  Python is the language NeuConX is built on.
echo  We need version 3.10 or newer.
echo.

set PYTHON_CMD=

python --version >nul 2>&1
if %errorlevel% equ 0 ( set PYTHON_CMD=python & goto :python_found )

python3 --version >nul 2>&1
if %errorlevel% equ 0 ( set PYTHON_CMD=python3 & goto :python_found )

py --version >nul 2>&1
if %errorlevel% equ 0 ( set PYTHON_CMD=py & goto :python_found )

color 0C
echo  [ERROR] Python was not found on your computer.
echo.
echo  How to install Python (takes about 2 minutes):
echo.
echo    1. We will open the download page now.
echo    2. Click the yellow "Download Python" button.
echo    3. Run the downloaded installer.
echo    4. IMPORTANT: On the first screen, tick the box
echo       that says "Add Python to PATH" before clicking Install.
echo    5. Once done, close this window and run install.bat again.
echo.
echo  Opening python.org/downloads now...
start https://www.python.org/downloads/
echo.
pause
exit /b 1

:python_found
color 0A
for /f "tokens=*" %%V in ('%PYTHON_CMD% --version 2^>^&1') do set PYVER=%%V
echo  [OK] Found: !PYVER!

%PYTHON_CMD% -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  [ERROR] Your Python is too old. Version 3.10+ is required.
    echo  Please download the latest from python.org and run this again.
    start https://www.python.org/downloads/
    pause
    exit /b 1
)

:: ================================================================
echo.
echo  -------------------------------------------------------
echo   STEP 2 of 6 - Setting Up Package Installer (pip)
echo  -------------------------------------------------------
echo.
echo  pip downloads and installs Python packages.
echo  Think of it like an app store for Python libraries.
echo.

%PYTHON_CMD% -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  pip not found - installing it now...
    %PYTHON_CMD% -m ensurepip --upgrade >nul 2>&1
)

echo  Upgrading pip to the latest version...
%PYTHON_CMD% -m pip install --upgrade pip --quiet 2>nul
echo  [OK] pip is ready.

:: ================================================================
echo.
echo  -------------------------------------------------------
echo   STEP 3 of 6 - Installing NeuConX Packages
echo  -------------------------------------------------------
echo.
echo  Installing the following packages:
echo.
echo    Flask           - runs the local web server
echo    Flask-Limiter   - protects against overuse
echo    bleach          - keeps your input safe
echo    python-dotenv   - reads your API keys from .env
echo    requests        - makes calls to AI providers
echo    google-generativeai - connects to Google Gemini
echo.
echo  Downloading and installing... (may take 1-2 minutes)
echo.

%PYTHON_CMD% -m pip install ^
    Flask==3.0.3 ^
    Werkzeug==3.0.3 ^
    Flask-Limiter==3.7.0 ^
    bleach==6.1.0 ^
    python-dotenv==1.0.1 ^
    google-generativeai==0.8.3 ^
    requests==2.32.3 ^
    urllib3==2.2.2

if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  [ERROR] Package installation failed.
    echo.
    echo  Common causes:
    echo    - No internet connection
    echo    - Firewall or antivirus blocking pip
    echo.
    echo  Try running this command manually in a new window:
    echo    %PYTHON_CMD% -m pip install Flask Flask-Limiter bleach python-dotenv requests google-generativeai
    echo.
    pause
    exit /b 1
)

echo.
echo  Verifying installation...
%PYTHON_CMD% -c "import flask; import flask_limiter; import bleach; import dotenv; import requests; import google.generativeai" >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  [ERROR] Some packages did not install correctly:
    echo.
    %PYTHON_CMD% -c "import flask" >nul 2>&1          || echo    FAILED: Flask
    %PYTHON_CMD% -c "import flask_limiter" >nul 2>&1  || echo    FAILED: Flask-Limiter
    %PYTHON_CMD% -c "import bleach" >nul 2>&1         || echo    FAILED: bleach
    %PYTHON_CMD% -c "import dotenv" >nul 2>&1         || echo    FAILED: python-dotenv
    %PYTHON_CMD% -c "import requests" >nul 2>&1       || echo    FAILED: requests
    %PYTHON_CMD% -c "import google.generativeai" >nul 2>&1 || echo    FAILED: google-generativeai
    echo.
    echo  Please share the above errors when asking for help.
    pause
    exit /b 1
)
echo  [OK] All packages installed and verified.

:: ================================================================
echo.
echo  -------------------------------------------------------
echo   STEP 4 of 6 - Smart Memory Feature (Optional)
echo  -------------------------------------------------------
echo.
echo  NeuConX can remember things across conversations.
echo  This lets you search your entire chat history by
echo  meaning - not just keywords.
echo.
echo  Example: search "Python project I worked on last week"
echo  and it finds the right conversation even if you used
echo  different words when you chatted.
echo.
echo  This is OPTIONAL. NeuConX works fine without it.
echo  Note: First use downloads an 80MB model to your PC.
echo  After that it works fully offline.
echo.
set /p CHROMA="  Install this feature? [Y/N]: "
echo.
if /i "!CHROMA!"=="Y" (
    echo  Installing... (may take 3-5 minutes)
    echo.
    %PYTHON_CMD% -m pip install chromadb==1.5.9 sentence-transformers==5.5.1

    %PYTHON_CMD% -c "import chromadb" >nul 2>&1
    if %errorlevel% equ 0 (
        echo.
        echo  [OK] Smart memory installed.
        echo       The 80MB model will download on first use.
    ) else (
        echo.
        echo  [WARNING] ChromaDB had issues. NeuConX will still work -
        echo  smart memory just won't be available right now.
        echo  You can try again later with:
        echo    %PYTHON_CMD% -m pip install chromadb sentence-transformers
    )
) else (
    echo  Skipped. Install later with:
    echo    %PYTHON_CMD% -m pip install chromadb sentence-transformers
)

:: ================================================================
echo.
echo  -------------------------------------------------------
echo   STEP 5 of 6 - Creating Your Settings File
echo  -------------------------------------------------------
echo.

if exist ".env" (
    echo  [OK] Settings file already exists - keeping it as-is.
    goto :env_done
)

echo  Creating your .env file...
echo.
echo  This file stores your API keys. It lives only on your
echo  computer and is never uploaded or shared anywhere.
echo.

if exist ".env.example" (
    copy ".env.example" ".env" >nul
) else (
    %PYTHON_CMD% -c "import secrets; open('.env','w').write('SECRET_KEY='+secrets.token_hex(32)+'\nGEMINI_API_KEY=\nGROQ_API_KEY=\nCEREBRAS_API_KEY=\nNVIDIA_API_KEY=\nOPENROUTER_API_KEY=\nOLLAMA_MODEL=\nOLLAMA_BASE_URL=http://localhost:11434\n')"
)

findstr /C:"SECRET_KEY" .env >nul 2>&1
if %errorlevel% neq 0 (
    %PYTHON_CMD% -c "import secrets; open('.env','a').write('\nSECRET_KEY='+secrets.token_hex(32))"
)

if not exist "data" mkdir data
if not exist "data\conversations" mkdir data\conversations

echo  [OK] Settings file created.

:env_done

:: ================================================================
echo.
echo  -------------------------------------------------------
echo   STEP 6 of 6 - Getting Your First API Key
echo  -------------------------------------------------------
echo.
echo  NeuConX connects to free AI services online.
echo  You need at least one API key to start chatting.
echo.
echo  We recommend GROQ - completely free, fastest,
echo  and takes under 2 minutes to set up.
echo.
echo  How to get a free Groq key:
echo    1. Go to console.groq.com and create a free account
echo    2. Click "API Keys" in the left menu
echo    3. Click "Create API Key" - copy the key it shows
echo    4. Open your .env file and paste it next to GROQ_API_KEY=
echo    5. Save the file
echo.
set /p GETKEY="  Open console.groq.com now? [Y/N]: "
if /i "!GETKEY!"=="Y" (
    start https://console.groq.com
    echo.
    echo  Browser opened. After copying your key:
    echo.
    set /p OPENDOTENV="  Open .env to paste your key now? [Y/N]: "
    if /i "!OPENDOTENV!"=="Y" notepad .env
) else (
    echo.
    echo  No problem. You can add keys later via the
    echo  Settings button inside the NeuConX app.
    echo.
    echo  Other free providers:
    echo    Gemini:   aistudio.google.com
    echo    Cerebras: cloud.cerebras.ai
    echo    NVIDIA:   build.nvidia.com
)

:: ================================================================
echo.
color 0B
echo  =====================================================
echo   Setup Complete! NeuConX is ready.
echo  =====================================================
echo.
echo  To use NeuConX every day:
echo    - Double-click start.bat
echo    - Your browser will open automatically
echo    - You do NOT need to run install.bat again
echo.
set /p STARTAPP="  Launch NeuConX right now? [Y/N]: "
if /i "!STARTAPP!"=="Y" (
    start cmd /k "start.bat"
)
echo.
pause