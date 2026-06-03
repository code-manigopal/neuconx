# NeuConX — Installation Guide

*Version 0.0 · Works on Windows 10/11, macOS 12+, Ubuntu 20.04+*

---

## Prerequisites

| Requirement | Version | Check |
|-------------|---------|-------|
| Python | 3.10 or higher | `python --version` |
| pip | Latest | `pip --version` |
| Git | Any | `git --version` |
| Browser | Chrome, Firefox, Edge | — |

---

## Windows Installation

### Step 1 — Install Python (if not already installed)

1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Download Python 3.11 or higher
3. Run the installer — **tick "Add Python to PATH"** before clicking Install
4. Open Command Prompt and verify:
```cmd
python --version
```
You should see `Python 3.11.x` or similar.

### Step 2 — Clone the repository

```cmd
git clone https://github.com/YOUR_USERNAME/neuconx.git
cd neuconx
```

Or download the ZIP from GitHub → Extract to a folder of your choice.

### Step 3 — Set up your API keys

```cmd
copy .env.example .env
notepad .env
```

Paste your keys into the file. At minimum, add one key to get started (Groq recommended):

```
GROQ_API_KEY=gsk_your_key_here
GEMINI_API_KEY=AIza_your_key_here
CEREBRAS_API_KEY=csk_your_key_here
NVIDIA_API_KEY=nvapi_your_key_here
OPENROUTER_API_KEY=sk-or-your_key_here
SECRET_KEY=your_random_secret_here
```

To generate a `SECRET_KEY`:
```cmd
python -c "import secrets; print(secrets.token_hex(32))"
```

Save and close Notepad.

### Step 4 — Launch

Double-click `start.bat` or run from Command Prompt:

```cmd
start.bat
```

The launcher will:
1. Check Python is installed
2. Install all dependencies automatically
3. Open `http://localhost:5050` in your browser

### Step 5 — Enable Semantic Memory (Optional)

For ChromaDB semantic search across conversations:

```cmd
pip install chromadb sentence-transformers --break-system-packages
```

Then restart `start.bat`. First run downloads the `all-MiniLM-L6-v2` model (~80MB).

---

## macOS / Linux Installation

### Step 1 — Install Python

**macOS:**
```bash
# Using Homebrew (recommended)
brew install python@3.11

# Verify
python3 --version
```

**Ubuntu / Debian:**
```bash
sudo apt update
sudo apt install python3.11 python3-pip git -y

# Verify
python3 --version
```

### Step 2 — Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/neuconx.git
cd neuconx
```

### Step 3 — Set up your API keys

```bash
cp .env.example .env
nano .env        # or: vim .env / code .env
```

Add your keys:

```
GROQ_API_KEY=gsk_your_key_here
GEMINI_API_KEY=AIza_your_key_here
CEREBRAS_API_KEY=csk_your_key_here
NVIDIA_API_KEY=nvapi_your_key_here
OPENROUTER_API_KEY=sk-or-your_key_here
SECRET_KEY=your_random_secret_here
```

Generate a `SECRET_KEY`:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Step 4 — Install dependencies

```bash
pip3 install -r requirements.txt --break-system-packages
```

If you get a permissions error on macOS, use:
```bash
pip3 install -r requirements.txt --user
```

### Step 5 — Launch

```bash
python3 app.py
```

Open your browser at: **http://localhost:5050**

To keep it running in the background:
```bash
nohup python3 app.py &
```

To stop it:
```bash
kill $(lsof -t -i:5050)
```

### Step 6 — Enable Semantic Memory (Optional)

```bash
pip3 install chromadb sentence-transformers --break-system-packages
```

Restart the app. First run downloads `all-MiniLM-L6-v2` (~80MB). Fully offline after that.

---

## Getting Free API Keys

You need at least one key to use NeuConX. Groq is the best starting point.

| Provider | Sign Up | Free Tier | Get Key |
|----------|---------|-----------|---------|
| **Groq** (start here) | [console.groq.com](https://console.groq.com) | Generous daily limit, fastest | Console → API Keys → Create |
| **Cerebras** | [cloud.cerebras.ai](https://cloud.cerebras.ai) | 60 req/min | Dashboard → API Keys |
| **Google AI Studio** | [aistudio.google.com](https://aistudio.google.com) | 1,500 req/day | Get API Key button |
| **NVIDIA NIM** | [build.nvidia.com](https://build.nvidia.com) | 40 req/min | Sign in → Get API Key |
| **OpenRouter** | [openrouter.ai](https://openrouter.ai) | Free credits | Keys section |

All five take under 5 minutes to set up. No credit card required.

---

## Saving Keys Without Restarting

Once the app is running, you can add or update keys directly from the UI:

1. Open **⚙ Settings** in the sidebar
2. Paste your new key into the relevant field
3. Click **💾 Save Keys**
4. Keys are active on your **next message** — no restart needed

---

## First Run Checklist

After launching, work through this list:

- [ ] App opens at `http://localhost:5050`
- [ ] Onboarding wizard appears — complete all 7 steps
- [ ] Open ⚙ Settings — verify at least one key shows ✓ configured
- [ ] Send a test message — "Hello" or "What is Python?"
- [ ] Check right panel — model response should appear
- [ ] Check header dots — at least one should be coloured (not dark)
- [ ] (Optional) Install ChromaDB for semantic memory

---

## Folder Structure After Install

```
neuconx/
├── app.py                 ← Main application
├── start.bat              ← Windows launcher
├── requirements.txt       ← Dependencies
├── .env                   ← Your API keys (never commit this)
├── .env.example           ← Key template
├── how_it_works.html      ← Visual explainer (open in browser)
├── templates/index.html   ← UI
├── static/                ← CSS + JS
├── skills/                ← Skill .md files
└── data/                  ← Created automatically at runtime
    ├── profile.json       ← Your onboarding answers
    └── conversations/     ← Chat history
```

---

## Common Issues

**"python is not recognized" (Windows)**
Python wasn't added to PATH during install. Reinstall Python and tick "Add Python to PATH".

**"Port 5050 already in use"**
Something else is using that port. Either stop the other process or change the port in `app.py`:
```python
app.run(host='127.0.0.1', port=5051)  # change to any free port
```

**"No response received" in chat**
No API keys configured. Open Settings and add at least one key.

**"Module not found: bleach / flask_limiter"**
Dependencies not installed. Run:
```bash
# Windows
pip install -r requirements.txt --break-system-packages

# Mac/Linux
pip3 install -r requirements.txt --break-system-packages
```

**Gemini shows "Quota exhausted"**
You've hit the 1,500/day free limit. Add a Groq key — it takes over automatically.
Gemini quota resets at midnight Pacific time. Restart the app to clear the flag.

**ChromaDB install fails**
Try installing separately:
```bash
pip install chromadb --break-system-packages
pip install sentence-transformers --break-system-packages
```
On macOS with Apple Silicon, you may need:
```bash
pip install chromadb --no-binary chromadb --break-system-packages
```

---

## Upgrading

```bash
cd neuconx
git pull origin main
pip install -r requirements.txt --break-system-packages
```

Restart the app. Your `data/` folder and `.env` are not touched by upgrades.

---

## Uninstalling

```bash
# Delete the folder
rm -rf neuconx        # Mac/Linux
rmdir /s /q neuconx   # Windows
```

That's it. No registry entries, no system-wide changes, no background processes.

---

*NeuConX Version 0.0 · Built by Kanaga Manikandan Gopal*
*"Multiple minds. One truth. Always free."*