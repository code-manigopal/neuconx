#!/bin/bash

# NeuConX — Daily launcher (Mac / Linux)

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo "  NeuConX — Starting..."
echo ""

# Find Python
PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        if "$cmd" -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "  ${RED}ERROR: Python not found.${NC}"
    echo "  Please run install.sh first."
    exit 1
fi

# Check Flask is installed
$PYTHON_CMD -c "import flask" 2>/dev/null
if [ $? -ne 0 ]; then
    echo -e "  ${RED}ERROR: NeuConX dependencies not installed.${NC}"
    echo "  Please run install.sh first, then try again."
    exit 1
fi

# Check .env exists
if [ ! -f ".env" ]; then
    echo -e "  ${YELLOW}WARNING: No .env file found.${NC}"
    echo "  Please run install.sh to complete setup."
    exit 1
fi

# Open browser after 2 seconds (background)
(sleep 2 && open "http://localhost:5050" 2>/dev/null || \
           xdg-open "http://localhost:5050" 2>/dev/null || \
           echo "  Open in browser: http://localhost:5050") &

echo -e "  ${GREEN}Running on http://localhost:5050${NC}"
echo "  Press Ctrl+C to stop."
echo ""

$PYTHON_CMD app.py
