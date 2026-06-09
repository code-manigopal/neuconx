# ⬡ NeuConX — Personal AI Platform

> **Multiple minds. One truth. Always free.**
> Locally hosted. No subscriptions. No telemetry. Never tracks you.

![Phase](https://img.shields.io/badge/Phase-7%20Complete-cyan)
![Security](https://img.shields.io/badge/Security-Hardened-green)
![License](https://img.shields.io/badge/License-MIT-blue)
![Python](https://img.shields.io/badge/Python-3.10%2B-yellow)
![Models](https://img.shields.io/badge/Models-6%2B%20Free%20APIs-orange)
![Ollama](https://img.shields.io/badge/Ollama-Local%20Models-purple)

---

## What is NeuConX?

NeuConX is a locally-hosted personal AI chat platform that queries **multiple free AI models in parallel**, merges their responses into one clean answer, and builds a personalised memory of you across sessions.

Everything runs on your machine. Your conversations, your profile, your API keys — none of it leaves your computer except the direct API calls you choose to make.

---

## Installation

### Windows

```cmd
git clone https://github.com/YOUR_USERNAME/neuconx.git
cd neuconx
install.bat
```

`install.bat` is a guided wizard — it checks Python, installs all packages, creates your `.env`, and walks you through getting your first free API key. Run it once, never again.

After setup:
```cmd
start.bat
```

### Mac / Linux

```bash
git clone https://github.com/YOUR_USERNAME/neuconx.git
cd neuconx
chmod +x install.sh start.sh
bash install.sh
```

After setup:
```bash
bash start.sh
```

### Manual (any platform)

```bash
git clone https://github.com/YOUR_USERNAME/neuconx.git
cd neuconx
pip install -r requirements.txt --break-system-packages
cp .env.example .env       # Mac/Linux
copy .env.example .env     # Windows
# Add your API keys to .env
python app.py
```

Open **http://localhost:5050** in your browser.

> See **INSTALL.md** for a detailed step-by-step guide including troubleshooting.

---

## API Providers

### Cloud APIs (Free — no credit card required)

| Provider | Model | Free Tier | Get Key |
|----------|-------|-----------|---------|
| **OpenRouter** | 24+ free models | `:free` suffix models | [openrouter.ai](https://openrouter.ai) |
| **Groq** | Llama 3.3 70B | Generous daily limit, fastest | [console.groq.com](https://console.groq.com) |
| **Cerebras** | Llama 3.3 70B | 60 req/min, fast | [cloud.cerebras.ai](https://cloud.cerebras.ai) |
| **Google AI Studio** | Gemini 2.0 Flash | 1,500 req/day | [aistudio.google.com](https://aistudio.google.com) |
| **NVIDIA NIM** | Llama 3.3 70B | 40 req/min | [build.nvidia.com](https://build.nvidia.com) |

**Recommended start:** Add Openrouter, and Groq first. It is the fastest, most generous free tier, and takes under 2 minutes to set up.

### Local Models (No API key needed)

| Provider | What it is | Hardware needed |
|----------|-----------|-----------------|
| **Ollama** | Runs AI models on your own computer | 8GB RAM minimum (7B models) |

Configure in **Settings → Local Models**. Hardware requirements are shown in-app before you enable it.

---

## How It Works

### Smart Routing

NeuConX classifies every query **locally** (no API call, zero cost) before deciding how many models to use:

```
Tier 1 — Quick      8 words or fewer, no complex keywords  → 1 model
Tier 2 — Balanced   9 to 40 words                          → 2 models
Tier 3 — Deep       Over 40 words, OR complex keywords      → All models
                    Keywords: analyze, compare, write, code,
                    research, explain, roadmap, career, plan,
                    switch, learn, build, design, implement...
```

Override anytime with the **Auto / Quick / Balanced / Deep** buttons in the header.

### Merge Engine

When multiple models respond:

- **0 valid responses** — error with specific fix instructions
- **1 valid response** — returned directly, no extra API call
- **2+ valid responses** — merged by Groq (fastest), acting as editor

The merge operator deduplicates overlapping content and combines unique insights. It does not add new information or pick a winner — it synthesises.

### AI Judge (Alternative)

Disable the merge engine in Settings → Engine. The judge reads all responses and returns the single best one verbatim. Choose any model as judge.

### Model Priority Order

```
OpenRouter -> Groq → Cerebras → Gemini → NVIDIA → OpenRouter → Ollama
```

Groq and Cerebras run first — most generous free tiers. Gemini's 1,500/day cap is preserved for actual queries.

### Dynamic Token Budget

Tokens are allocated per query based on what is being asked:

| Query type | Tokens | Example |
|------------|--------|---------|
| Career / roadmap / plan queries | 8,192 | "How do I switch to RAG engineering?" |
| Long prompts (80+ words) | 6,144 | Detailed technical questions |
| Full HTML / complete documents | 6,144 | "Write a complete HTML page..." |
| Code / technical | 4,096 | "Implement this function..." |
| Medium prompts (40+ words) | 4,096 | Most standard questions |
| Default | 2,048 | General queries |
| Short conversational | 1,024 | "Hello", "What is X?" |

---

## Features

### Core
| Feature | Detail |
|---------|--------|
| Multi-model parallel calling | All selected models called simultaneously in threads |
| Smart routing | Tier 1/2/3 classified locally, zero token cost |
| Merge engine | Deduplication + union synthesis across all responses |
| AI Judge mode | Picks single best response instead of merging |
| Model pin selector | Force any specific model for a conversation |
| Free Models Only toggle | Restrict to free-tier models only (default: ON) |
| Session memory | Last 20 messages in-process, thread-safe |
| Conversation history | Saved locally as JSON, full reload on click |
| Onboarding wizard | 7-step personalisation, done once |
| Personalised prompts | Profile + learned facts injected into every query |
| Model status dots | Hover to see live model count and usage quota |
| Dynamic token budget | 1,024–8,192 tokens based on prompt type |
| Auto-retry | Retries once on timeout/connection errors |
| Quota exhaustion routing | Auto-skips exhausted models silently |
| Markdown rendering | Full markdown in chat bubbles and right panel |
| Large model warnings | Alerts when pinning 70B+ models on free tier |

### Settings (4-tab modal)
| Tab | What is there |
|-----|--------------|
| **API Providers** | Key input per provider, Validate button, live model count badge, model list tooltip |
| **Local Models** | Ollama URL + model, hardware requirements table, Test Connection button |
| **Engine** | Free Models Only, Merge Engine toggle, AI Judge provider + model selector |
| **Reset** | Individual resets for onboarding, memory, conversations, profile, keys, factory reset |

### Skills System
| Feature | Detail |
|---------|--------|
| In-app editor | Create and edit skills live without touching files |
| Categories | writing, coding, research, analysis, creative, productivity, custom |
| Skill chaining | Toggle multiple skills simultaneously |
| 5 starter skills | humanizer, code_reviewer, pdf_creator, researcher, data_analyst |

### Memory
| Feature | Detail |
|---------|--------|
| Session memory | In-process, thread-safe, last 20 messages per session |
| Semantic search | ChromaDB + sentence-transformers (optional install) |
| Memory candidates | Detects personal facts mid-conversation, floating confirm/reject cards |
| Profile viewer | See all onboarding answers + AI-learned facts |
| Learned facts | Saved on confirmation, deletable individually |

### Security
| Layer | Controls |
|-------|---------|
| Network | host=127.0.0.1 only — never exposed to local network |
| HTTP headers | 7 security headers on every response, Server header stripped |
| CSRF | Per-session token, timing-safe comparison |
| Input | bleach.clean(), null byte removal, max length enforcement |
| File ops | .md extension whitelist, path traversal guards |
| API keys | Never returned to client, last-4 hint only, .env gitignored |
| Sessions | HttpOnly + SameSite=Strict cookie flags |
| Rate limiting | Flask-Limiter on all endpoints |
| Markdown | Only AI responses use innerHTML; user input always textContent |

---

## Starter Skills

| Skill | Category | What it does |
|-------|----------|-------------|
| humanizer | writing | Removes AI writing patterns — targets perplexity, burstiness, surface tells |
| code_reviewer | coding | Security, bugs, and performance analysis |
| pdf_creator | writing | Structures output as professional documents |
| researcher | research | Enforces Overview → Findings → Analysis → Conclusion |
| data_analyst | analysis | Enforces Observation → Interpretation → Recommendation |

Create your own: click **+ New Skill** in the sidebar, or upload any `.md` file.

---

## Engine Options

### Free Models Only (default: ON)
Only free-tier models appear in the dropdown and routing. Turn off if you have a paid subscription and want premium models. Persists across restarts.

### Merge Engine (default: ON)
All model responses are synthesised into one answer. Turn off to use AI Judge instead.

### AI Judge
When merge engine is OFF — picks the single best response verbatim. Configure judge provider (Groq / Cerebras / Gemini / Ollama) and specific model in Settings → Engine.

---

## Ollama Setup

```bash
# 1. Install Ollama
# Mac:   brew install ollama
# Linux: curl -fsSL https://ollama.com/install.sh | sh
# Windows: https://ollama.com/download

# 2. Pull a model
ollama pull llama3.2        # 2GB, good for most tasks
ollama pull phi3            # 2.3GB, fast and capable
ollama pull qwen2.5         # 4.7GB, strong multilingual

# 3. Start server
ollama serve

# 4. Configure in NeuConX
# Settings → Local Models → enter URL and model name → Test Connection
```

Hardware guide (shown in-app):

| Model size | RAM needed | VRAM needed |
|------------|-----------|-------------|
| 7B models | 8GB | 6GB |
| 13B models | 16GB | 10GB |
| 70B models | 64GB | 40GB |
| CPU-only | Any | Not required (slower) |

---

## Semantic Memory (Optional)

```bash
pip install chromadb sentence-transformers --break-system-packages
```

Restart the app. The **Search Memory** button in the sidebar becomes active. To index existing conversations into ChromaDB, run this once in the browser console:

```javascript
fetch('/api/memory/index', {
  method: 'POST',
  headers: {'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content}
}).then(r => r.json()).then(console.log)
```

The embedding model (`all-MiniLM-L6-v2`, 80MB) downloads on first use and runs fully offline after that.

---

## Project Structure

```
neuconx/
├── app.py                    # Flask backend (~2,600 lines)
├── requirements.txt          # All Python dependencies with comments
├── install.bat               # Windows one-time installer (guided wizard)
├── install.sh                # Mac/Linux one-time installer (guided wizard)
├── start.bat                 # Windows daily launcher
├── start.sh                  # Mac/Linux daily launcher
├── .env                      # Your API keys (NEVER commit — gitignored)
├── .env.example              # Key template (safe to commit)
├── .gitignore
├── README.md
├── INSTALL.md                # Detailed install guide with troubleshooting
├── PROMPT_NOTES.md           # Merge engine internals + prompting guide
├── RELEASE_NOTES_V0.0.md     # V0.0 feature list and changelog
├── how_it_works.html         # Visual flowchart (open in browser or /how_it_works.html)
├── templates/
│   └── index.html            # Single-page UI (Jinja2)
├── static/
│   ├── css/style.css         # Dark cinematic theme
│   └── js/
│       ├── app.js            # Frontend logic (~1,900 lines)
│       └── marked.min.js     # Bundled markdown parser (no CDN dependency)
├── skills/                   # Skill .md files
│   ├── humanizer.md
│   ├── code_reviewer.md
│   ├── pdf_creator.md
│   ├── researcher.md
│   └── data_analyst.md
└── data/                     # Created at runtime — gitignored
    ├── profile.json          # Onboarding answers + learned facts
    ├── neuconx_settings.json # Engine settings (merge, judge, free-only)
    ├── conversations/        # One JSON file per conversation
    └── memory/               # ChromaDB vector store (if enabled)
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/chat` | Main chat endpoint |
| GET | `/api/conversations` | List all conversations |
| GET/POST/DELETE | `/api/conversations/:id` | Load / save / delete conversation |
| GET | `/api/skills` | List skills with category metadata |
| GET/PUT/DELETE | `/api/skills/:name` | Get / update / delete skill |
| POST | `/api/skills/upload` | Upload a .md skill file |
| GET | `/api/skills/categories` | Category list with counts |
| GET/POST | `/api/settings` | API key status / save keys |
| GET/POST | `/api/neuconx-settings` | Engine settings (merge, judge, free-only) |
| POST | `/api/keys/validate` | Validate a single API key live |
| GET/POST | `/api/profile` | Onboarding profile |
| GET | `/api/profile/learned` | AI-learned facts |
| DELETE | `/api/profile/learned/:idx` | Delete one learned fact |
| GET | `/api/usage` | Per-model call counts |
| GET | `/api/memory/status` | ChromaDB status + embedding count |
| POST | `/api/memory/search` | Semantic search across history |
| POST | `/api/memory/index` | Index all conversations into ChromaDB |
| GET | `/api/memory/candidates` | Pending memory confirmation cards |
| POST | `/api/memory/candidates/:id/confirm` | Confirm a memory candidate |
| POST | `/api/memory/candidates/:id/reject` | Reject a memory candidate |
| GET | `/api/models/available` | Live model list from all configured providers |
| GET | `/api/models/counts` | Model count per provider |
| GET | `/api/onboarding/status` | Check if onboarding is complete |
| POST | `/api/reset/onboarding` | Reset onboarding |
| POST | `/api/reset/memory` | Clear session memory |
| POST | `/api/reset/conversations` | Delete all conversations |
| POST | `/api/reset/profile` | Reset learned profile |
| POST | `/api/reset/keys` | Wipe API keys |
| POST | `/api/reset/factory` | Full factory reset (two confirmations) |
| GET | `/how_it_works.html` | Visual flowchart page |

---

## Build History

| Phase | What was built |
|-------|---------------|
| 1 | Core chat, dark UI, security baseline, onboarding wizard |
| 2 | Multi-model parallel calling, smart routing, merge engine, Groq + Cerebras |
| 3 | Session memory, conversation history, save/load/delete |
| 4 | Skills editor, categories, in-app creation, 5 starter skills |
| 5 | ChromaDB RAG, semantic search, cross-session embeddings |
| 6 | Memory confirmation UI, learned fact approval cards |
| 7 | Profile viewer, auto-update from conversation, per-fact delete |
| Post-V0.0 | Model pin selector, live model listing, AI Judge mode, Ollama support, 4-tab settings modal, Free Models Only toggle, API key validation with model count, markdown rendering, dynamic token budget (8,192 for complex queries), large model warnings, install.bat + install.sh guided wizards, start.sh for Mac/Linux |

---

## Golden Rule

**NeuConX will always be 100% free to run. No paid tier. No subscription. No telemetry. Ever.**

---

## License

MIT — use it, fork it, build on it.

*Built by Kanaga Manikandan Gopal · June 2026*
*"Vibe coded — but architecturally serious."*
