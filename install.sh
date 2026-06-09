#!/bin/bash

# =====================================================
#   NeuConX - First Time Setup (Mac / Linux)
#   Multiple minds. One truth. Always free.
# =====================================================

set -e  # Exit on error (we handle errors manually below)

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m' # No Color

clear

echo ""
echo "  ====================================================="
echo "   NeuConX - First Time Setup"
echo "   Multiple minds. One truth. Always free."
echo "  ====================================================="
echo ""
echo "  Welcome! This installer sets up everything NeuConX"
echo "  needs to run. It only needs to run ONCE."
echo ""
echo "  What this installer does:"
echo "    1. Checks that Python is installed"
echo "    2. Installs all required Python packages"
echo "    3. Optionally installs AI memory (ChromaDB)"
echo "    4. Creates your personal settings file (.env)"
echo "    5. Guides you to get your first free API key"
echo ""
echo "  Time needed: 3-5 minutes"
echo "  Internet connection: required"
echo ""
read -p "  Press Enter to begin..."

# ================================================================
echo ""
echo "  -----------------------------------------------------"
echo "   STEP 1 of 6 - Checking Python"
echo "  -----------------------------------------------------"
echo ""
echo "  Python is the language NeuConX is built on."
echo "  We need version 3.10 or newer."
echo ""

PYTHON_CMD=""

# Try python3 first, then python
for cmd in python3 python python3.12 python3.11 python3.10; do
    if command -v "$cmd" &>/dev/null; then
        # Check version is 3.10+
        if "$cmd" -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "  ${RED}[ERROR] Python 3.10+ not found.${NC}"
    echo ""
    echo "  How to install Python:"
    echo ""

    # Detect OS
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "  Mac — Option A (recommended, using Homebrew):"
        echo "    1. Install Homebrew if you don't have it:"
        echo "       /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        echo "    2. Then run:  brew install python@3.11"
        echo ""
        echo "  Mac — Option B (direct download):"
        echo "    Go to https://www.python.org/downloads/macos/"
        echo "    Download and run the installer package."
    else
        echo "  Ubuntu / Debian:"
        echo "    sudo apt update && sudo apt install python3.11 python3-pip python3-venv -y"
        echo ""
        echo "  Fedora / RHEL:"
        echo "    sudo dnf install python3.11 -y"
        echo ""
        echo "  Arch Linux:"
        echo "    sudo pacman -S python"
    fi

    echo ""
    echo "  After installing Python, run this script again:"
    echo "    bash install.sh"
    echo ""
    exit 1
fi

PYVER=$($PYTHON_CMD --version 2>&1)
echo -e "  ${GREEN}[OK]${NC} Found: $PYVER"

# ================================================================
echo ""
echo "  -----------------------------------------------------"
echo "   STEP 2 of 6 - Setting Up Package Installer (pip)"
echo "  -----------------------------------------------------"
echo ""
echo "  pip downloads and installs Python packages."
echo "  Think of it like an app store for Python libraries."
echo ""

# Check pip
if ! $PYTHON_CMD -m pip --version &>/dev/null; then
    echo "  pip not found — installing it now..."
    $PYTHON_CMD -m ensurepip --upgrade 2>/dev/null || {
        echo -e "  ${RED}[ERROR] Could not install pip.${NC}"
        echo ""
        if [[ "$OSTYPE" == "darwin"* ]]; then
            echo "  Try:  brew install python@3.11"
        else
            echo "  Try:  sudo apt install python3-pip"
        fi
        exit 1
    }
fi

echo "  Upgrading pip to latest version..."
$PYTHON_CMD -m pip install --upgrade pip --quiet 2>/dev/null
echo -e "  ${GREEN}[OK]${NC} pip is ready."

# ================================================================
echo ""
echo "  -----------------------------------------------------"
echo "   STEP 3 of 6 - Installing NeuConX Packages"
echo "  -----------------------------------------------------"
echo ""
echo "  Installing the following packages:"
echo ""
echo "    Flask            - runs the local web server"
echo "    Flask-Limiter    - protects against overuse"
echo "    bleach           - keeps your input safe"
echo "    python-dotenv    - reads your API keys from .env"
echo "    requests         - makes calls to AI providers"
echo "    google-generativeai - connects to Google Gemini"
echo ""
echo "  Downloading and installing... (may take 1-2 minutes)"
echo ""

# Try with --break-system-packages first (needed on newer distros)
# Fall back to --user if that fails
INSTALL_FLAGS="--quiet"

$PYTHON_CMD -m pip install \
    Flask==3.0.3 \
    Werkzeug==3.0.3 \
    Flask-Limiter==3.7.0 \
    bleach==6.1.0 \
    python-dotenv==1.0.1 \
    google-generativeai==0.8.3 \
    requests==2.32.3 \
    urllib3==2.2.2 \
    $INSTALL_FLAGS \
    --break-system-packages 2>/dev/null || \
$PYTHON_CMD -m pip install \
    Flask==3.0.3 \
    Werkzeug==3.0.3 \
    Flask-Limiter==3.7.0 \
    bleach==6.1.0 \
    python-dotenv==1.0.1 \
    google-generativeai==0.8.3 \
    requests==2.32.3 \
    urllib3==2.2.2 \
    $INSTALL_FLAGS \
    --user 2>/dev/null || \
$PYTHON_CMD -m pip install \
    Flask==3.0.3 \
    Werkzeug==3.0.3 \
    Flask-Limiter==3.7.0 \
    bleach==6.1.0 \
    python-dotenv==1.0.1 \
    google-generativeai==0.8.3 \
    requests==2.32.3 \
    urllib3==2.2.2

if [ $? -ne 0 ]; then
    echo ""
    echo -e "  ${RED}[ERROR] Package installation failed.${NC}"
    echo ""
    echo "  Common causes:"
    echo "    - No internet connection"
    echo "    - Firewall blocking pip"
    echo ""
    echo "  Try running manually:"
    echo "    $PYTHON_CMD -m pip install Flask Flask-Limiter bleach python-dotenv requests google-generativeai"
    echo ""
    exit 1
fi

echo ""
echo "  Verifying installation..."
$PYTHON_CMD -c "import flask; import flask_limiter; import bleach; import dotenv; import requests; import google.generativeai" 2>/dev/null
if [ $? -ne 0 ]; then
    echo ""
    echo -e "  ${RED}[ERROR] Some packages did not install correctly:${NC}"
    echo ""
    $PYTHON_CMD -c "import flask" 2>/dev/null          || echo "    FAILED: Flask"
    $PYTHON_CMD -c "import flask_limiter" 2>/dev/null  || echo "    FAILED: Flask-Limiter"
    $PYTHON_CMD -c "import bleach" 2>/dev/null         || echo "    FAILED: bleach"
    $PYTHON_CMD -c "import dotenv" 2>/dev/null         || echo "    FAILED: python-dotenv"
    $PYTHON_CMD -c "import requests" 2>/dev/null       || echo "    FAILED: requests"
    $PYTHON_CMD -c "import google.generativeai" 2>/dev/null || echo "    FAILED: google-generativeai"
    echo ""
    echo "  Please share the above errors when asking for help."
    exit 1
fi
echo -e "  ${GREEN}[OK]${NC} All packages installed and verified."

# ================================================================
echo ""
echo "  -----------------------------------------------------"
echo "   STEP 4 of 6 - Smart Memory Feature (Optional)"
echo "  -----------------------------------------------------"
echo ""
echo "  NeuConX can remember things across conversations."
echo "  This lets you search your entire chat history by"
echo "  meaning — not just keywords."
echo ""
echo "  Example: search 'Python project I worked on last week'"
echo "  and it finds the right conversation even if you used"
echo "  different words when you chatted."
echo ""
echo "  This is OPTIONAL. NeuConX works fine without it."
echo "  Note: First use downloads an 80MB model to your PC."
echo "        After that it works fully offline."
echo ""
read -p "  Install this feature? [y/N]: " CHROMA
echo ""

if [[ "$CHROMA" =~ ^[Yy]$ ]]; then
    echo "  Installing... (may take 3-5 minutes)"
    echo ""
    $PYTHON_CMD -m pip install chromadb==1.5.9 sentence-transformers==5.5.1 \
        --break-system-packages 2>/dev/null || \
    $PYTHON_CMD -m pip install chromadb==1.5.9 sentence-transformers==5.5.1 \
        --user 2>/dev/null || \
    $PYTHON_CMD -m pip install chromadb==1.5.9 sentence-transformers==5.5.1

    $PYTHON_CMD -c "import chromadb" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo ""
        echo -e "  ${GREEN}[OK]${NC} Smart memory installed."
        echo "       The 80MB model will download on first use."
    else
        echo ""
        echo -e "  ${YELLOW}[WARNING]${NC} ChromaDB had issues. NeuConX will still work —"
        echo "  smart memory just won't be available right now."
        echo "  Try again later:  $PYTHON_CMD -m pip install chromadb sentence-transformers"
    fi
else
    echo "  Skipped. Install later with:"
    echo "    $PYTHON_CMD -m pip install chromadb sentence-transformers"
fi

# ================================================================
echo ""
echo "  -----------------------------------------------------"
echo "   STEP 5 of 6 - Creating Your Settings File"
echo "  -----------------------------------------------------"
echo ""

if [ -f ".env" ]; then
    echo -e "  ${GREEN}[OK]${NC} Settings file already exists — keeping it as-is."
else
    echo "  Creating your .env file..."
    echo ""
    echo "  This file stores your API keys. It lives only on your"
    echo "  computer and is never uploaded or shared anywhere."
    echo ""

    if [ -f ".env.example" ]; then
        cp .env.example .env
    else
        SECRET_KEY=$($PYTHON_CMD -c "import secrets; print(secrets.token_hex(32))")
        cat > .env << ENVEOF
SECRET_KEY=$SECRET_KEY
GEMINI_API_KEY=
GROQ_API_KEY=
CEREBRAS_API_KEY=
NVIDIA_API_KEY=
OPENROUTER_API_KEY=
OLLAMA_MODEL=
OLLAMA_BASE_URL=http://localhost:11434
ENVEOF
    fi

    # Add SECRET_KEY if missing
    if ! grep -q "SECRET_KEY" .env 2>/dev/null; then
        SECRET_KEY=$($PYTHON_CMD -c "import secrets; print(secrets.token_hex(32))")
        echo "SECRET_KEY=$SECRET_KEY" >> .env
    fi

    # Create data directories
    mkdir -p data/conversations

    echo -e "  ${GREEN}[OK]${NC} Settings file created."
fi

# ================================================================
echo ""
echo "  -----------------------------------------------------"
echo "   STEP 6 of 6 - Getting Your First API Key"
echo "  -----------------------------------------------------"
echo ""
echo "  NeuConX connects to free AI services online."
echo "  You need at least one API key to start chatting."
echo ""
echo "  We recommend GROQ — completely free, fastest,"
echo "  and takes under 2 minutes to set up."
echo ""
echo "  How to get a free Groq key:"
echo "    1. Go to https://console.groq.com"
echo "    2. Create a free account"
echo "    3. Click 'API Keys' in the left menu"
echo "    4. Click 'Create API Key' — copy the key"
echo "    5. Open .env and paste next to GROQ_API_KEY="
echo ""
read -p "  Open .env now to add your key? [y/N]: " OPENENV
echo ""

if [[ "$OPENENV" =~ ^[Yy]$ ]]; then
    # Try common editors
    if command -v nano &>/dev/null; then
        nano .env
    elif command -v vim &>/dev/null; then
        vim .env
    elif command -v code &>/dev/null; then
        code .env
    else
        echo "  No editor found. Open .env manually with any text editor."
        echo "  File location: $(pwd)/.env"
    fi
else
    echo "  No problem. You can add keys later via the"
    echo "  Settings button inside the NeuConX app."
    echo ""
    echo "  Other free providers:"
    echo "    Gemini:   https://aistudio.google.com"
    echo "    Cerebras: https://cloud.cerebras.ai"
    echo "    NVIDIA:   https://build.nvidia.com"
fi

# Make start.sh executable if it exists
if [ -f "start.sh" ]; then
    chmod +x start.sh
fi

# ================================================================
echo ""
echo -e "  ${GREEN}====================================================="
echo "   Setup Complete! NeuConX is ready."
echo -e "  =====================================================${NC}"
echo ""
echo "  To use NeuConX every day:"
echo -e "    ${BOLD}bash start.sh${NC}      (or: python3 app.py)"
echo "    Then open:  http://localhost:5050"
echo ""
echo "  You do NOT need to run install.sh again."
echo ""
read -p "  Launch NeuConX right now? [y/N]: " LAUNCH
if [[ "$LAUNCH" =~ ^[Yy]$ ]]; then
    echo ""
    echo "  Starting NeuConX..."
    $PYTHON_CMD app.py
fi

echo ""
