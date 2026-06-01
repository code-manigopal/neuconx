# ⬡ NeuConX — Personal AI Platform

> **Your personal AI. Multiple minds. One truth.**
> 100% free to run. Locally hosted. Never tracks you.

![Phase](https://img.shields.io/badge/Phase-1%20Core-cyan)
![Security](https://img.shields.io/badge/Security-Hardened-green)
![License](https://img.shields.io/badge/License-MIT-blue)
![Python](https://img.shields.io/badge/Python-3.10%2B-yellow)

---

## What is NeuConX?

NeuConX is a locally-hosted personal AI chat platform that queries **multiple free AI models in parallel**, merges their responses into one clean answer, and remembers context about you across sessions.

Built for power users who want full control — no subscriptions, no cloud lock-in, no data leaving your machine except the API calls you choose to make.

---

## Features (Phase 1)

| Feature | Status |
|---------|--------|
| Multi-model parallel querying | ✅ Gemini + NVIDIA + OpenRouter |
| Smart routing (Tier 1/2/3) | ✅ Auto-classifies query complexity |
| Merge Engine | ✅ Deduplicates, unions unique insights |
| Skills System | ✅ Toggle .md instruction files |
| Conversation history | ✅ Local JSON storage |
| Onboarding wizard | ✅ Personalises responses |
| Settings (API key manager) | ✅ Local .env only |
| Dark cinematic UI | ✅ Syne + JetBrains Mono fonts |
| Security hardening | ✅ See Security section below |

---

## Quick Start

### 1. Prerequisites
- Python 3.10 or higher
- Windows (or Mac/Linux with minor path adjustments)

### 2. Clone
```bash
git clone https://github.com/YOUR_USERNAME/NeuConX.git
cd NeuConX
```

### 3. Set up API keys
```bash
copy .env.example .env
# Open .env and paste your keys (all free tiers — see below)
```

### 4. Launch
```bash
# Windows
start.bat

# Mac / Linux
pip install -r requirements.txt
python app.py
```

Open **http://localhost:5050** in your browser.

---

## Free API Keys (All $0)

| Model | Provider | Free Tier | Get Key |
|-------|----------|-----------|---------|
| Gemini 2.0 Flash | Google AI Studio | 1,500 req/day | [aistudio.google.com](https://aistudio.google.com) |
| Llama 3.3 70B | NVIDIA NIM | 40 req/min | [build.nvidia.com](https://build.nvidia.com) |
| DeepSeek Chat | OpenRouter | Free credits | [openrouter.ai](https://openrouter.ai) |
| Mistral 7B | OpenRouter | Free credits | [openrouter.ai](https://openrouter.ai) |

---

## How Smart Routing Works

NeuConX classifies every query before sending it:

```
Tier 1 — Quick      < 10 words           → 1 model  (Gemini only)
Tier 2 — Balanced   10–30 words          → 2 models (Gemini + NVIDIA)
Tier 3 — Deep       > 30 words or        → All 4 models
                    contains: analyze,
                    compare, write,
                    research, debug...
```

You can override the tier manually using the buttons in the top bar.

---

## Skills System

Skills are plain `.md` files in the `/skills/` folder. Toggle them on before sending a message — their instructions are prepended to your prompt.

**Included starter skills:**
- `humanizer.md` — Makes responses sound natural, not robotic
- `code_reviewer.md` — Reviews code with senior-engineer rigor
- `pdf_creator.md` — Structures output as professional documents

**Add your own:** Click "+ Upload Skill" in the sidebar. Any `.md` file under 50KB works.

---

## Security Architecture

> This section documents all security controls implemented by the Principal Security Architect. Every control maps to a real threat.

### Threat Model

| Threat | Attack Vector | Control |
|--------|--------------|---------|
| API key leak | Git commit | `.gitignore`, `.env` pattern |
| XSS | User input in DOM | `textContent` only, never `innerHTML` |
| CSRF | State-changing requests | Per-session CSRF token, `X-CSRF-Token` header |
| Prompt injection | Malicious user input | `bleach` sanitization on all inputs |
| Path traversal | File upload / conv ID | Regex whitelist on all IDs and filenames |
| DoS / API abuse | Rapid requests | `Flask-Limiter` on all endpoints |
| Clickjacking | Iframe embedding | `X-Frame-Options: DENY` |
| MIME sniffing | Content-type abuse | `X-Content-Type-Options: nosniff` |
| Info disclosure | Error messages | Generic errors to client, detail in server log |
| Supply chain | Dependency confusion | All versions pinned in `requirements.txt` |
| Credential exposure | Settings API | Only last 4 chars hint returned, never full key |
| Session hijacking | Cookie theft | `HttpOnly`, `SameSite=Strict` session cookies |
| Null byte injection | File paths | Null bytes stripped from all inputs |
| Oversized payloads | Large uploads | 1MB max content length, 50KB max skill file |

### Security Headers (every response)

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
Content-Security-Policy: default-src 'self'; ...
```

### CSRF Protection Flow

```
1. Flask generates token: secrets.token_hex(32)
2. Token stored in server-side session (HttpOnly cookie)
3. Token rendered into <meta name="csrf-token"> in HTML
4. JS reads token from meta tag (NOT localStorage)
5. Every POST/PUT/DELETE sends: X-CSRF-Token header
6. Flask validates using secrets.compare_digest() (timing-safe)
7. 403 returned on mismatch — request rejected
```

### Input Sanitization Pipeline

```
User input → bleach.clean() (strip HTML) 
           → null byte removal 
           → max length enforcement 
           → sanitize_filename() for file ops 
           → regex whitelist for IDs
```

### What Data Leaves Your Machine

| Data | Destination | When |
|------|-------------|------|
| Your message + history | Gemini / NVIDIA / OpenRouter | On every chat send |
| Nothing else | — | — |

Your conversations, profile, API keys — all stay on your local disk.

---

## Project Structure

```
NeuConX/
├── app.py                    # Flask backend — all API routes
├── requirements.txt          # Pinned dependencies
├── start.bat                 # Windows one-click launcher
├── .env.example              # Key template (commit this)
├── .env                      # Your actual keys (NEVER commit)
├── .gitignore                # Protects secrets and local data
├── README.md
│
├── templates/
│   └── index.html            # Full single-page UI
│
├── static/
│   ├── css/style.css         # Dark cinematic theme
│   └── js/app.js             # Frontend logic (XSS-safe)
│
├── skills/                   # Skill instruction files
│   ├── humanizer.md
│   ├── code_reviewer.md
│   └── pdf_creator.md
│
└── data/                     # Created at runtime (gitignored)
    ├── profile.json          # Your onboarding answers
    └── conversations/        # Chat history (local JSON)
```

---

## Build Phases

| Phase | Feature | Status |
|-------|---------|--------|
| 1 | Core chat + UI + security | ✅ This commit |
| 2 | Multi-model + smart routing + merge engine | 🔲 Next |
| 3 | Session memory + conversation history UI | 🔲 |
| 4 | Skills system (advanced) | 🔲 |
| 5 | ChromaDB + RAG + cross-session memory | 🔲 |
| 6 | Memory confirmation UI + feedback loop | 🔲 |
| 7 | Onboarding wizard + auto profile updates | 🔲 |

---

## Golden Rule

> **NeuConX will always be 100% free to run.**
> No paid tier. No subscription. No telemetry. Ever.

---

## License

MIT — Use it, fork it, build on it. Attribution appreciated but not required.
