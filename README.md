# ⬡ NeuConX — Personal AI Platform

> **Multiple minds. One truth. Always free.**
> Locally hosted. No subscriptions. No telemetry. Never tracks you.

![Phase](https://img.shields.io/badge/Phase-7%20Complete-cyan)
![Security](https://img.shields.io/badge/Security-Hardened-green)
![License](https://img.shields.io/badge/License-MIT-blue)
![Python](https://img.shields.io/badge/Python-3.10%2B-yellow)
![Models](https://img.shields.io/badge/Models-6%20Free%20APIs-orange)

---

## What is NeuConX?

NeuConX is a locally-hosted personal AI chat platform that queries **up to 6 free AI models in parallel**, merges their responses into one clean answer, and builds a personalised memory of you across sessions.

Everything runs on your machine. Your conversations, your profile, your API keys — none of it leaves your computer except the direct API calls you choose to make.

---

## Quick Start

### 1. Prerequisites
Python 3.10 or higher. Windows (or Mac/Linux with minor path adjustments).

### 2. Clone
```bash
git clone https://github.com/YOUR_USERNAME/neuconx.git
cd neuconx
```

### 3. Set up API keys
```bash
copy .env.example .env
# Open .env and add your keys (all free — see table below)
```

### 4. Launch
```bash
# Windows
start.bat

# Mac / Linux
pip install -r requirements.txt --break-system-packages
python app.py
```

Open **http://localhost:5050** in your browser.

---

## Free API Keys

All models are completely free. No credit card required.

| Model | Provider | Free Tier | Get Key |
|-------|----------|-----------|---------|
| Llama 3.3 70B | **Groq** | Generous daily limit, fastest | [console.groq.com](https://console.groq.com) |
| Llama 3.3 70B | **Cerebras** | 60 req/min, fast inference | [cloud.cerebras.ai](https://cloud.cerebras.ai) |
| Gemini 2.0 Flash | **Google AI Studio** | 1,500 req/day | [aistudio.google.com](https://aistudio.google.com) |
| Llama 3.3 70B | **NVIDIA NIM** | 40 req/min | [build.nvidia.com](https://build.nvidia.com) |
| DeepSeek Chat | **OpenRouter** | Free credits | [openrouter.ai](https://openrouter.ai) |
| Mistral 7B | **OpenRouter** | Free credits | [openrouter.ai](https://openrouter.ai) |

**Recommended:** Add Groq first — fastest and most generous free tier. Add Gemini second.

---

## How Smart Routing Works

NeuConX classifies every query **locally** (no API call, zero tokens) before deciding how many models to use.

```
Tier 1 — Quick      <=8 words, no complex keywords  -> 1 model  (Groq)
Tier 2 — Balanced   9-40 words                      -> 2 models (Groq + Cerebras)
Tier 3 — Deep       >40 words, OR complex keywords  -> All available models
                    (analyze, compare, write, code,
                    research, explain, design...)
```

### Merge Engine

When multiple models respond, a **merge operator** synthesises their answers:

- **0 valid responses** — descriptive error with fix instructions
- **1 valid response** — returned directly, no extra API call (saves quota)
- **2+ valid responses** — merged using Groq as editor (fastest available)

The merge operator deduplicates overlapping content and unions unique insights. It does not pick a winner or add new information — it is synthesis, not judgement.

### Model Priority Order
```
Groq -> Cerebras -> Gemini -> NVIDIA -> DeepSeek -> Mistral
```
Groq and Cerebras run first because they have the most generous free tiers. Gemini's 1,500/day hard cap is preserved for actual queries, not overhead.

---

## Features

### Core
| Feature | Detail |
|---------|--------|
| Multi-model parallel calling | Up to 6 models called simultaneously in threads |
| Smart routing | Tier 1/2/3 classified locally, zero token cost |
| Merge engine | Deduplication + union, Groq as merge operator |
| Session memory | Last 20 messages in-process, thread-safe |
| Conversation history | Saved locally as JSON, full reload on click |
| Onboarding wizard | 7-step personalisation, done once |
| Model status dots | Header dots show live status, hover for usage/quota tooltip |
| Dynamic token budget | 1,024-4,096 tokens based on prompt type |
| Auto-retry | Retries once on timeout/connection errors |
| Quota exhaustion routing | Gemini daily cap triggers auto-skip to Groq/Cerebras |

### Skills System (Phase 4)
| Feature | Detail |
|---------|--------|
| In-app skill editor | Edit skills live, no file manager needed |
| Create new skills | + New Skill button in sidebar |
| Categories | writing, coding, research, analysis, creative, productivity, custom |
| Skill chaining | Toggle multiple skills simultaneously |
| 5 starter skills | humanizer, code_reviewer, pdf_creator, researcher, data_analyst |

### Memory (Phases 3, 5, 6, 7)
| Feature | Detail |
|---------|--------|
| Session memory | In-process, thread-safe, last 20 messages |
| Semantic search | ChromaDB + sentence-transformers (optional install) |
| Memory candidates | Detects facts in messages, floating confirm/reject cards |
| Profile viewer | See onboarding answers + AI-learned facts |
| Learned facts | Auto-saved on confirmation, deletable individually |

### Security
| Layer | Controls |
|-------|---------|
| Network | host=127.0.0.1 only, never exposed to network |
| HTTP headers | 7 security headers on every response, Server header stripped |
| CSRF | Per-session token, timing-safe comparison |
| Input | bleach.clean(), null byte removal, max length, regex whitelists |
| File ops | Extension whitelist (.md only), filename sanitization, path traversal guards |
| API keys | Never returned to client, last-4 hint only, .env gitignored |
| Sessions | HttpOnly + SameSite=Strict cookie flags |
| Rate limiting | Flask-Limiter on all endpoints |
| Supply chain | All dependency versions pinned in requirements.txt |

---

## Skills

| Skill | Category | What it does |
|-------|----------|-------------|
| humanizer | writing | Removes jargon, makes responses conversational |
| code_reviewer | coding | Security, bugs, and performance analysis |
| pdf_creator | writing | Structures output as professional documents |
| researcher | research | Enforces Overview -> Findings -> Analysis -> Conclusion |
| data_analyst | analysis | Observation -> Interpretation -> Recommendation |

Create your own: click **+ New Skill** in the sidebar.

---

## Reset Options

All resets are in **Settings -> Reset Options**:

| Reset | What it does |
|-------|-------------|
| Onboarding | Delete profile.json, wizard runs on next load |
| Session Memory | Clear in-memory chat context |
| Conversations | Delete all saved conversation files |
| Learned Profile | Wipe AI-learned facts, keep onboarding answers |
| API Keys | Remove all keys from .env |
| Factory Reset | All of the above, two confirmations required |

---

## Enabling Semantic Memory (Optional)

```bash
pip install chromadb sentence-transformers --break-system-packages
```

Restart the app. The Search Memory button in the sidebar activates. To index existing conversations, POST to `/api/memory/index`.

---

## Project Structure

```
neuconx/
├── app.py                    # Flask backend, all phases (~1,700 lines)
├── requirements.txt          # Pinned dependencies
├── start.bat                 # Windows launcher
├── .env                      # Your API keys (NEVER commit)
├── .env.example              # Key template (safe to commit)
├── .gitignore
├── README.md
├── templates/index.html      # Single-page UI (Jinja2)
├── static/css/style.css      # Dark cinematic theme
├── static/js/app.js          # Frontend logic (~1,300 lines)
├── skills/                   # Skill .md files (committed)
└── data/                     # Runtime data (gitignored)
    ├── profile.json
    ├── conversations/
    └── memory/
```

---

## Build Phases

| Phase | Feature | Status |
|-------|---------|--------|
| 1 | Core chat, UI, security | done |
| 2 | Multi-model, smart routing, merge engine, Groq/Cerebras | done |
| 3 | Session memory, conversation history, delete, clear | done |
| 4 | Skills editor, categories, in-app creation | done |
| 5 | ChromaDB, RAG, semantic search, cross-session embeddings | done |
| 6 | Memory confirmation UI, learned fact approval | done |
| 7 | Profile viewer, auto-update, per-fact delete | done |

---

## Golden Rule

**NeuConX will always be 100% free to run. No paid tier. No subscription. No telemetry. Ever.**

---

## License

MIT — use it, fork it, build on it.
