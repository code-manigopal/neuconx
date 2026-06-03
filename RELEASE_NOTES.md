# NeuConX — Release Notes

---

## Version 0.0 — Initial Release
*Released: June 2026*

> "Multiple minds. One truth. Always free."
> First public build of NeuConX — a locally-hosted, multi-model personal AI platform.
> 100% free to run. No subscriptions. No telemetry. No data leaves your machine
> except the API calls you choose to make.

---

### What's Included in V0.0

#### Core Platform
- Single-page dark UI built with Flask + Vanilla JS (no React, no Node, no build step)
- One-click Windows launcher (`start.bat`) — auto-installs dependencies, opens browser
- Fully offline after initial setup — no internet required except for AI API calls
- Runs at `http://localhost:5050` — bound to localhost only, never exposed to network

#### Multi-Model Engine
- 6 free AI models supported: Groq, Cerebras, Gemini 2.0 Flash, NVIDIA NIM, DeepSeek (via OpenRouter), Mistral (via OpenRouter)
- All models called **in parallel** using Python threads — no waiting in line
- Smart Router classifies query complexity locally (zero tokens, zero cost) into three tiers:
  - Tier 1 Quick — 1 model for short/simple queries
  - Tier 2 Balanced — 2 models for medium questions
  - Tier 3 Deep — all models for complex, long, or technical requests
- Manual tier override: Auto / Quick / Balanced / Deep buttons in header
- Model priority order: Groq → Cerebras → Gemini → NVIDIA → DeepSeek → Mistral
- Dynamic token budget: 1,024–4,096 tokens based on prompt type (prevents rate limiting)
- Auto-retry once on transient timeout or connection errors

#### Merge Engine
- 0 valid responses → descriptive error with specific fix instructions
- 1 valid response → passed through directly (no extra API call, no quota used)
- 2+ valid responses → merged by Groq (fastest available) acting as editor/synthesiser
- Merge operator deduplicates overlapping content, unions unique insights
- Does not add new information or pick a winner — pure synthesis

#### Quota & Rate Limit Handling
- Gemini daily quota exhaustion (`ResourceExhausted`) auto-detected
- Exhausted models auto-skipped for the session — Groq/Cerebras take over silently
- Header model dots turn orange on exhaustion — hover for tooltip with usage/quota bar
- Groq/Cerebras rate limits (429) treated as temporary — no permanent blacklisting
- Keys reload from `.env` on every request — no restart needed after saving keys

#### Personalisation
- 7-step onboarding wizard captures: name, location, education, career, goals, response style, current projects
- Profile injected into every prompt automatically — responses personalised without you repeating yourself
- AI-learned facts extracted from conversation (pattern detection) with confirm/reject floating cards
- Confirmed facts saved to `profile.json` and injected alongside onboarding answers
- Profile viewer (👤 My Profile) shows onboarding answers + learned facts, per-fact delete

#### Skills System
- 5 starter skills: humanizer, code_reviewer, pdf_creator, researcher, data_analyst
- Toggle skills on/off in sidebar — injected into prompt when active
- In-app skill editor — create and edit skills without touching the filesystem
- Skill categories: writing, coding, research, analysis, creative, productivity, custom
- Upload any `.md` file as a custom skill

#### Memory
- Session memory: last 20 messages in-process, thread-safe, gone on restart
- ChromaDB semantic memory (optional): embeddings of all conversations stored locally
- Embedding model: `all-MiniLM-L6-v2` (80MB, runs fully offline after first download)
- Semantic search across all conversation history with relevance scores
- Memory search UI accessible from sidebar (🔍 Search Memory)
- Backfill existing conversations into ChromaDB via `/api/memory/index`

#### Conversation Management
- All conversations auto-saved as JSON to `data/conversations/`
- Sidebar shows conversation list with date and message count
- Click to reload any past conversation with full context
- Delete button (×) on each conversation item
- New Chat (+) button clears context and starts fresh

#### Settings & Reset
- Settings modal with API key manager for all 6 providers
- Keys stored in `.env` only — never returned to client (last-4 hint only)
- No restart needed after saving keys
- Reset options for: onboarding, session memory, conversations, learned profile, API keys, full factory reset
- Factory reset requires two confirmation dialogs

#### Security (Principal Architect level)
- `host=127.0.0.1` — never exposed to local network
- 7 HTTP security headers on every response (CSP, X-Frame-Options, X-XSS-Protection, etc.)
- CSRF tokens via `secrets.compare_digest()` — timing-attack resistant
- All inputs sanitized with `bleach.clean()` + null byte removal + max length enforcement
- Path traversal prevention on all file operations
- API keys never logged, never returned to client
- Session cookies: `HttpOnly` + `SameSite=Strict`
- Rate limiting on all endpoints via `Flask-Limiter`
- All dependency versions pinned in `requirements.txt`
- ChromaDB telemetry disabled (`anonymized_telemetry=False`)

#### Documentation
- `README.md` — full project documentation
- `PROMPT_NOTES_V0.0.md` — merge engine internals + prompting guide
- `how_it_works.html` — visual flowchart explainer (accessible at `/how_it_works.html`)
- `INSTALL.md` — step-by-step setup for Windows and Mac/Linux

---

### Known Limitations in V0.0

- Single-user only — no multi-user support
- No mobile responsive layout — designed for desktop browser
- ChromaDB semantic memory requires manual install (`pip install chromadb sentence-transformers`)
- Session memory resets on app restart (in-process only)
- Quota exhaustion flag resets only on restart — no midnight auto-reset
- No export of conversations to PDF or Markdown
- No voice input
- No image/multimodal support

---

### What's Next (V0.1 Planned)

- Mobile responsive layout
- Conversation export (PDF / Markdown)
- Midnight quota reset timer (auto-clears exhaustion flags)
- Community skills marketplace
- Voice input via Web Speech API
- Model response streaming (show answer as it types)

---

### Free API Keys Used in V0.0

| Provider | Model | Free Tier |
|----------|-------|-----------|
| Groq | Llama 3.3 70B | Generous daily limit |
| Cerebras | Llama 3.3 70B | 60 req/min |
| Google AI Studio | Gemini 2.0 Flash | 1,500 req/day |
| NVIDIA NIM | Llama 3.3 70B | 40 req/min |
| OpenRouter | DeepSeek Chat + Mistral 7B | Free credits |

---

### License

MIT — use it, fork it, build on it. Attribution appreciated but not required.

---

*Built by Kanaga Manikandan Gopal · June 2026*
*"Vibe coded — but architecturally serious."*