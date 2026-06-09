# NeuConX — Installation Guide

*Works on Windows 10/11, macOS 12+, Ubuntu 20.04+*

---

## The Quickest Way

### Windows
1. Download or clone the repo
2. Double-click `install.bat`
3. Follow the on-screen steps
4. Double-click `start.bat` to launch

### Mac / Linux
1. Download or clone the repo
2. Open Terminal in the NeuConX folder
3. Run: `bash install.sh`
4. Run: `bash start.sh` to launch

That covers 95% of installs. The rest of this document is for troubleshooting and manual setup.

---

## Prerequisites

| Requirement | Version | How to check |
|-------------|---------|-------------|
| Python | 3.10 or higher | `python --version` or `python3 --version` |
| pip | Any recent version | `python -m pip --version` |
| Internet | Required for install | — |

---

## Windows — Step by Step

### Step 1: Install Python (if you don't have it)

1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Click the yellow **Download Python** button
3. Run the downloaded `.exe` installer
4. **Critical:** On the first screen, tick **"Add Python to PATH"** before clicking Install

Verify it worked — open Command Prompt and run:
```cmd
python --version
```
You should see `Python 3.11.x` or similar.

### Step 2: Run the installer

```cmd
install.bat
```

The installer will:
- Check your Python version
- Install all required packages using `python -m pip`
- Ask if you want ChromaDB (optional semantic memory)
- Create your `.env` file
- Offer to open Groq's signup page for your first API key

### Step 3: Add at least one API key

Open `.env` in Notepad and add your key:
```
GROQ_API_KEY=gsk_your_key_here
```

Get a free Groq key at [console.groq.com](https://console.groq.com) — takes under 2 minutes.

### Step 4: Launch

```cmd
start.bat
```

Your browser opens automatically at `http://localhost:5050`.

---

## Mac — Step by Step

### Step 1: Install Python

**Option A — Homebrew (recommended):**
```bash
# Install Homebrew if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python
brew install python@3.11
```

**Option B — Direct download:**
Go to [python.org/downloads/macos](https://www.python.org/downloads/macos/) and download the macOS installer.

Verify:
```bash
python3 --version
```

### Step 2: Run the installer

```bash
chmod +x install.sh
bash install.sh
```

### Step 3: Add your API key

```bash
nano .env
```

Add your Groq key next to `GROQ_API_KEY=`, save with `Ctrl+O`, exit with `Ctrl+X`.

### Step 4: Launch

```bash
bash start.sh
```

Browser opens automatically at `http://localhost:5050`.

---

## Linux — Step by Step

### Step 1: Install Python

**Ubuntu / Debian:**
```bash
sudo apt update
sudo apt install python3.11 python3-pip python3-venv -y
```

**Fedora / RHEL:**
```bash
sudo dnf install python3.11 -y
```

**Arch:**
```bash
sudo pacman -S python python-pip
```

Verify:
```bash
python3 --version
```

### Step 2: Run the installer

```bash
chmod +x install.sh
bash install.sh
```

The script tries `--break-system-packages` first (needed on Ubuntu 23+/Debian 12+), then `--user`, then bare install.

### Step 3: Add your API key

```bash
nano .env
# Add: GROQ_API_KEY=gsk_your_key_here
# Ctrl+O to save, Ctrl+X to exit
```

### Step 4: Launch

```bash
bash start.sh
```

---

## Manual Install (Any Platform)

If the scripts don't work, install manually:

```bash
# Install packages
pip install -r requirements.txt --break-system-packages

# Or with --user flag
pip install -r requirements.txt --user

# Create .env
cp .env.example .env      # Mac/Linux
copy .env.example .env    # Windows

# Generate a SECRET_KEY and add to .env
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
# Copy that output and paste into .env

# Create data folder
mkdir -p data/conversations

# Launch
python3 app.py     # Mac/Linux
python app.py      # Windows
```

---

## API Keys

You need at least one. All are completely free.

| Provider | Key prefix | Where to get it | Free tier |
|----------|-----------|-----------------|-----------|
| **Groq** (start here) | `gsk_` | [console.groq.com](https://console.groq.com) | Generous daily limit |
| **Cerebras** | `csk-` | [cloud.cerebras.ai](https://cloud.cerebras.ai) | 60 req/min |
| **Google Gemini** | `AIza` | [aistudio.google.com](https://aistudio.google.com) | 1,500 req/day |
| **NVIDIA NIM** | `nvapi-` | [build.nvidia.com](https://build.nvidia.com) | 40 req/min |
| **OpenRouter** | `sk-or-` | [openrouter.ai](https://openrouter.ai) | Free models with `:free` suffix |

Add keys to `.env`:
```
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=AIza...
```

Keys can also be added or changed through **Settings** in the app at any time — no restart needed.

---

## Optional: Semantic Memory (ChromaDB)

Enables the **Search Memory** feature — semantic search across all your past conversations.

```bash
pip install chromadb sentence-transformers --break-system-packages
```

The first run downloads `all-MiniLM-L6-v2` (~80MB). Fully offline after that.

After installing, restart the app. Then index your existing conversations once:

```javascript
// Run in browser DevTools console (F12)
fetch('/api/memory/index', {
  method: 'POST',
  headers: {'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content}
}).then(r => r.json()).then(console.log)
```

---

## Optional: Ollama (Local AI Models)

Run AI models entirely on your own machine — no API key, no internet after setup.

```bash
# Mac
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh

# Windows — download from https://ollama.com/download

# Pull a model
ollama pull llama3.2     # 2GB — good starting point
ollama pull phi3         # 2.3GB — fast and capable

# Start server
ollama serve
```

Then configure in **Settings → Local Models** — enter the URL (`http://localhost:11434`) and model name.

Hardware requirements:

| Model size | RAM | VRAM |
|------------|-----|------|
| 7B | 8GB | 6GB |
| 13B | 16GB | 10GB |
| 70B | 64GB | 40GB |
| CPU-only | 8GB+ | Not required (slower) |

---

## Troubleshooting

### "python is not recognized" (Windows)
Python is not on your PATH. Two options:
1. Reinstall Python and tick **"Add Python to PATH"**
2. Use the full path: `C:\Users\YourName\AppData\Local\Programs\Python\Python311\python.exe`

### "No module named flask" (or any module)
Dependencies not installed. Run:
```bash
python -m pip install Flask Flask-Limiter bleach python-dotenv requests google-generativeai
```

On Ubuntu 23+ or Debian 12+ you may need:
```bash
python3 -m pip install Flask --break-system-packages
```

### "Port 5050 already in use"
Something else is using that port. Either stop the other process, or change the port in `app.py`:
```python
app.run(host='127.0.0.1', port=5051)
```

### "No response received" in chat
No API keys configured, or keys are wrong. Open **Settings** in the app and add at least one key.

### 401 Unauthorized from OpenRouter
- Check your key has no spaces before or after it in `.env`
- The model may require credits — some `:free` models need a minimum OpenRouter balance
- Use the **Validate** button in Settings to test the key

### Gemini says "Quota exhausted"
You have hit the 1,500 requests/day free limit. NeuConX automatically routes to Groq/Cerebras. Quota resets at midnight Pacific time. Restart the app after midnight to clear the flag.

### ChromaDB fails to install
Try separately:
```bash
pip install chromadb --break-system-packages
pip install sentence-transformers --break-system-packages
```

On Mac with Apple Silicon:
```bash
pip install chromadb --no-binary chromadb --break-system-packages
```

### start.bat / start.sh closes immediately
Run it from a terminal (Command Prompt on Windows, Terminal on Mac/Linux) so you can see the error message. The most common cause is missing dependencies — run `install.bat` or `install.sh` first.

---

## Uninstalling

```bash
# Delete the folder
rm -rf neuconx          # Mac/Linux
rmdir /s /q neuconx     # Windows
```

No registry entries, no background services, no system-wide changes.

---

*NeuConX v0.0 · Built by Kanaga Manikandan Gopal · June 2026*