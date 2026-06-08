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

## Quick Start

### Option A — Fresh Install (Windows)

```cmd
git clone https://github.com/YOUR_USERNAME/neuconx.git
cd neuconx
install.bat
```

`install.bat` checks Python, installs all dependencies, creates your `.env`, and walks you through setup. Then:

```cmd
start.bat
```

### Option B — Manual

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/neuconx.git
cd neuconx

# Install dependencies
pip install -r requirements.txt --break-system-packages

# Configure
copy .env.example .env   # Windows
cp .env.example .env     # Mac/Linux
# Edit .env and add your API keys

# Launch
python app.py            # Mac/Linux
start.bat                # Windows
```

Open **http://localhost:5050** in your browser.

---

## API Providers

### Cloud APIs (Free)

| Provider | Model | Free Tier | Get Key |
|----------|-------|-----------|---------|
| **Groq** | Llama 3.3 70B | Generous daily limit, fastest | [console.groq.com](https://console.groq.com) |
| **Cerebras** | Llama 3.3 70B | 60 req/min, fast | [cloud.cerebras.ai](https://cloud.cerebras.ai) |
| **Google AI Studio** | Gemini 2.0 Flash | 1,500 req/day | [aistudio.google.com](https://aistudio.google.com) |
| **NVIDIA NIM** | Llama 3.3 70B | 40 req/min | [build.nvidia.com](https://build.nvidia.com) |
| **OpenRouter** | 24+ free models | Free tier (`:free` suffix) | [openrouter.ai](https://openrouter.ai) |

**Recommended:** Add Groq first — fastest and most generous free tier.

### Local Models (No API Key)

| Provider | Setup | Hardware |
|----------|-------|----------|
| **Ollama** | `ollama pull llama3.2` | 8GB RAM min (7B models) |

Configure in **Settings → Local Models**. See hardware requirements there.

---

## How Smart Routing Works

NeuConX classifies every query **locally** (no API call, zero tokens) before deciding how many models to use.

```
Tier 1 — Quick      ≤8 words, no complex keywords   → 1 model  (Groq)
Tier 2 — Balanced   9–40 words                       → 2 models (Groq + Cerebras)
Tier 3 — Deep       >40 words, OR complex keywords   → All available models
                    (analyze, compare, write, code,
                    research, explain, design, switch,
                    roadmap, plan, career, learn...)
```

### Token Budget

Tokens are allocated dynamically based on query complexity:

| Query type | Token budget |
|------------|-------------|
| Career/roadmap/plan/pivot queries | 8,192 |
| Long prompts (>80 words) | 6,144 |
| Full HTML/complete docs | 6,144 |
| Code/technical | 4,096 |
| Medium prompts (>40 words) | 4,096 |
| Default | 2,048 |
| Short conversational (≤10 words) | 1,024 |

### Merge Engine

When multiple models respond, a **merge operator** synthesises their answers:

- **0 valid responses** — descriptive error with fix instructions
- **1 valid response** — returned directly, no extra API call (saves quota)
- **2+ valid responses** — merged using Groq as editor (fastest available)

### AI Judge Mode (Alternative to Merge)

Disable the merge engine in **Settings → Engine** to use AI Judge mode instead. The judge reads all responses and returns the single best one verbatim. Choose any configured model as judge.

### Model Priority Order

```
Groq → Cerebras → Gemini → NVIDIA → OpenRouter → Ollama
```

---

## Features

### Core
| Feature | Detail |
|---------|--------|
| Multi-model parallel calling | All models called simultaneously in threads |
| Smart routing | Tier 1/2/3 classified locally, zero token cost |
| Merge engine | Deduplication + union synthesis |
| AI Judge mode | Alternative to merge — picks single best response |
| Model pin selector | Force any specific model for a conversation |
| Session memory | Last 20 messages in-process, thread-safe |
| Conversation history | Saved locally as JSON, full reload on click |
| Onboarding wizard | 7-step personalisation, done once |
| Personalised prompts | Profile + learned facts injected into every query |
| Model status dots | Hover to see model count and usage quota |
| Dynamic token budget | 1,024–8,192 tokens based on prompt type |
| Auto-retry | Retries once on timeout/connection errors |
| Quota exhaustion routing | Auto-skips exhausted models |
| Markdown rendering | Full markdown in chat bubbles and model response panel |

### Settings (4-tab modal)
| Tab | Features |
|-----|---------|
| **API Providers** | Key input, live validation, model count badge, per-provider model list on hover |
| **Local Models** | Ollama server URL + model, hardware requirements, connection test |
| **Engine** | Free Models Only toggle, Merge Engine toggle, AI Judge config |
| **Reset** | Onboarding, memory, conversations, profile, keys, factory reset |

### Skills System
| Feature | Detail |
|---------|--------|
| In-app skill editor | Create and edit skills without touching files |
| Skill categories | writing, coding, research, analysis, creative, productivity, custom |
| Skill chaining | Toggle multiple skills simultaneously |
| 5 starter skills | humanizer, code_reviewer, pdf_creator, researcher, data_analyst |

### Memory
| Feature | Detail |
|---------|--------|
| Session memory | In-process, thread-safe, last 20 messages |
| Semantic search | ChromaDB + sentence-transformers (optional) |
| Memory candidates | Detects facts, floating confirm/reject cards |
| Profile viewer | Onboarding answers + AI-learned facts |
| Learned facts | Auto-saved on confirmation, deletable individually |

### Security
| Layer | Controls |
|-------|---------|
| Network | host=127.0.0.1 only |
| HTTP headers | 7 security headers, Server header stripped |
| CSRF | Per-session token, timing-safe comparison |
| Input | bleach.clean(), null byte removal, max length |
| File ops | .md whitelist, path traversal guards |
| API keys | Never returned to client, last-4 hint only |
| Sessions | HttpOnly + SameSite=Strict |
| Rate limiting | Flask-Limiter on all endpoints |
| Markdown | Only AI responses use innerHTML; user input always textContent |

---

## Skills

| Skill | Category | What it does |
|-------|----------|-------------|
| humanizer | writing | 3-pass AI pattern removal — targets perplexity, burstiness, surface tells |
| code_reviewer | coding | Security, bugs, performance analysis |
| pdf_creator | writing | Structures output as professional documents |
| researcher | research | Overview → Findings → Analysis → Conclusion |
| data_analyst | analysis | Observation → Interpretation → Recommendation |

Create your own: click **+ New Skill** in the sidebar.

---

## Engine Settings

### Free Models Only (default: ON)
When enabled, only `:free` tier models appear in the model dropdown and routing. Disable if you have a paid subscription and want access to premium models. Setting persists across restarts.

### Merge Engine (default: ON)
When enabled, all model responses are combined by the merge operator. When disabled, the AI Judge picks the single best response from all candidates.

### AI Judge
Choose which provider and model acts as judge when merge engine is off. Supports Groq, Cerebras, Gemini, or Ollama.

---

## Ollama (Local Models)

1. Install: [ollama.com/download](https://ollama.com/download)
2. Pull a model: `ollama pull llama3.2`
3. Start server: `ollama serve`
4. Configure in **Settings → Local Models**
5. Click **Test Connection** — shows model count if running

Hardware requirements shown in-app. Minimum 8GB RAM for 7B models.

---

## Semantic Memory (Optional)

```bash
pip install chromadb sentence-transformers --break-system-packages
```

Restart the app. 🔍 **Search Memory** in the sidebar activates. Index existing conversations:

```bash
# Browser console:
fetch('/api/memory/index', {method:'POST', headers:{'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content}}).then(r=>r.json()).then(console.log)
```

---

## Project Structure

```
neuconx/
├── app.py                    # Flask backend (~2,600 lines)
├── requirements.txt          # Pinned dependencies
├── install.bat               # One-click Windows installer
├── start.bat                 # Windows launcher
├── .env                      # Your API keys (NEVER commit)
├── .env.example              # Key template (safe to commit)
├── .gitignore
├── README.md
├── PROMPT_NOTES.md
├── RELEASE_NOTES_V0.0.md
├── INSTALL.md
├── how_it_works.html         # Visual flowchart (served at /how_it_works.html)
├── templates/index.html      # Single-page UI (Jinja2)
├── static/
│   ├── css/style.css         # Dark cinematic theme
│   └── js/
│       ├── app.js            # Frontend logic (~1,850 lines)
│       └── marked.min.js     # Local markdown parser (no CDN)
├── skills/                   # Skill .md files (committed)
└── data/                     # Runtime data (gitignored)
    ├── profile.json
    ├── neuconx_settings.json
    ├── conversations/
    └── memory/
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/chat` | Main chat |
| GET/POST/DELETE | `/api/conversations/:id` | Conversation management |
| GET | `/api/skills` | List skills with metadata |
| GET/PUT/DELETE | `/api/skills/:name` | Skill CRUD |
| GET | `/api/skills/categories` | Categories with counts |
| GET/POST | `/api/settings` | Key status / save keys |
| GET/POST | `/api/neuconx-settings` | Engine settings (merge, judge, free-only) |
| GET/POST | `/api/profile` | Onboarding profile |
| GET/DELETE | `/api/profile/learned/:idx` | Learned facts |
| GET | `/api/memory/status` | ChromaDB + session status |
| POST | `/api/memory/search` | Semantic search |
| POST | `/api/memory/index` | Index all conversations |
| GET/POST | `/api/memory/candidates/:id/confirm\|reject` | Memory card actions |
| GET | `/api/models/available` | Live model list from all providers |
| GET | `/api/models/counts` | Model count per provider (for header dots) |
| POST | `/api/keys/validate` | Validate a single API key |
| POST | `/api/reset/*` | Individual reset actions |
| POST | `/api/reset/factory` | Full factory reset |

---

## Build Phases

| Phase | Feature | Status |
|-------|---------|--------|
| 1 | Core chat, UI, security | ✅ |
| 2 | Multi-model, smart routing, merge engine | ✅ |
| 3 | Session memory, conversation history | ✅ |
| 4 | Skills editor, categories, in-app creation | ✅ |
| 5 | ChromaDB, RAG, semantic search | ✅ |
| 6 | Memory confirmation UI, learned fact approval | ✅ |
| 7 | Profile viewer, auto-update, per-fact delete | ✅ |
| Post-V0.0 | Model pin selector, AI Judge, Ollama, settings tabs, free-only toggle, markdown rendering, dynamic token budget, API key validation, install.bat | ✅ |

---

## Golden Rule

**NeuConX will always be 100% free to run. No paid tier. No subscription. No telemetry. Ever.**

---

## License

MIT — use it, fork it, build on it.
*Built by Kanaga Manikandan Gopal · June 2026*