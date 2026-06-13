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

## Version 0.0.1 — Local/LAN Model Expansion
*Released: June 2026*

> Small patch focused on making local models a first-class citizen alongside
> the cloud providers, plus a branding pass and a quiet-but-important merge
> engine bugfix.

### Added
- **LM Studio support** alongside Ollama — same Settings tab, now called **Local / LAN Models**. NeuConX auto-detects which backend is running by trying Ollama's `/api/tags` first, then falling back to the OpenAI-compatible `/v1/models`
- **LAN support** — point NeuConX at any machine on your local network running LM Studio, not just `localhost`. Useful if a more powerful PC on your network hosts the models
- **Pinned model support for local/LAN models** — pinning a specific Ollama/LM Studio model now works correctly; previously returned "key not configured" since local models don't use API keys
- **NCX logo** — replaced the `⬡` text/emoji branding with the new `NCXLogo.png` across the sidebar, welcome screen, onboarding flow, and favicon
- **Save button** for Local / LAN Models settings — URL and model name now persist to `.env` independently of the cloud API key form

### Fixed
- **Merge engine silently dropping local/LAN responses** — the parallel-call collector used `t.join(timeout=35)`, but local models can take up to 120s (especially cold-loading in LM Studio). Responses arriving after 35s were excluded from the result set entirely, so a 2-model request (e.g. one OpenRouter + one local model) would incorrectly look like "1 valid response" and skip merging. Collector timeout raised to `130s` — local/LAN responses are now reliably merged
- **Ollama/LM Studio 400 errors** — `_call_pinned` had no handler for `provider == 'ollama'`, falling through to "Unknown provider". Added a dedicated case using `/v1/chat/completions` against the configured `ollama_base_url`
- Error messages for local models now distinguish "cannot connect" (server not running / wrong URL) from "timed out" (model still cold-loading) — previously both showed a generic error

### Known gotchas (not bugs, but worth knowing)
- LM Studio's `/v1/models` lists every downloaded model, but only the model in the active inference slot will respond unless **"Load models on demand"** is enabled in LM Studio's server settings
- A `400 Bad Request` from LM Studio almost always means the model `id` in NeuConX Settings doesn't exactly match what `/v1/models` returns — copy it, don't retype
- First call to a newly-loaded LM Studio model can take 1-3 minutes; warm it up with a message in LM Studio's own chat UI first

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

## Version 0.0.2 — Export & Document Generation
*Released: June 2026*

> Focused on getting content OUT of NeuConX cleanly — copy buttons for
> code/tables, a full PDF/DOCX/TXT export dropdown, and a real PDF-generation
> pipeline for the pdf_creator skill. Also fixes a markdown tokenizer bug
> that affected tables across chat, exports, and generated PDFs alike.

### Added
- **Per-block copy buttons** — every code block and table in an AI response gets a hover `⎘` icon. Code blocks copy raw text; tables copy as TSV (paste-ready into Excel/Sheets)
- **Export dropdown (PDF / DOCX / TXT)** — every AI message has a `⬇` button in its action bar. PDF and DOCX preserve real structure (headings, tables, lists, code blocks, bold/italic) via vendored `jsPDF` and `docx` libraries (no CDN, CSP-compliant)
- **pdf_creator skill — real PDF generation** — when toggled on, every chat response is also rendered to a themed `.pdf` file (NCX Dark or Clean Pro, selectable via a small dropdown next to the skill toggle) and attached as a file card with download link + inline preview
- **Hybrid PDF engine** (`doc_generator.py`) — `reportlab` (always available, zero system deps) is the default and required engine; `weasyprint` (optional, nicer typography) is used automatically when installed for prose-heavy docs, with silent fallback to reportlab if unavailable or it errors
- New endpoints: `GET /api/generated/<filename>` (serve generated PDFs, strict filename validation), `GET /api/pdf-themes`

### Fixed
- **Tables immediately following a text line (no blank line) were swallowed as raw paragraph text** — e.g. `"Mani's Leverage Points:\n| Investment | Return |\n|---|---|"` rendered as literal `|`-pipe text instead of a table. This affected the live chat bubble (`marked.min.js`), the export dropdown (`simpleMdTokenize`), and pdf_creator's generated PDFs (`doc_generator.py`) — all three tokenizers shared the same paragraph-consumption loop that didn't look ahead for a table separator. All three now check the next line before consuming the current one into a paragraph
- **PDF export emoji/LaTeX garbage** — jsPDF's built-in fonts can't render emoji or LaTeX, producing garbled boxes (e.g. `$\rightarrow$` showing as broken glyphs). Added `cleanPdfText()`: converts common LaTeX (`$\rightarrow$` → `->`, `$\sim$` → `~`, etc.) to plain text and strips emoji/pictographic Unicode ranges before drawing
- **PDF export table cell truncation** — table cells previously took only the first wrapped line at a fixed 16pt row height, cutting off longer cell content. Cells now wrap fully with row height sized to the tallest cell
- **`marked.lexer()` did not exist** — the bundled `marked.min.js` is a custom parser with only `.parse()`. Export functions calling `.lexer()` silently fell back to treating the entire response as one paragraph. Added `simpleMdTokenize()`, a standalone tokenizer mirroring the bundled parser's block-splitting logic

### Design decisions
- **Every message generates a PDF when pdf_creator is on** (not just messages that explicitly ask for a document) — simpler mental model, no regex-based "does this look like a document request" guessing
- The pdf_creator skill prompt now explicitly tells the AI **not** to suggest writing a separate Python/fpdf2/reportlab script to generate a PDF, since NeuConX already does this natively for every response — avoids redundant code-dump responses

---

## Version 0.0.1 — Local/LAN Model Expansion
*Released: June 2026*

> Small patch focused on making local models a first-class citizen alongside
> the cloud providers, plus a branding pass and a quiet-but-important merge
> engine bugfix.

### Added
- **LM Studio support** alongside Ollama — same Settings tab, now called **Local / LAN Models**. NeuConX auto-detects which backend is running by trying Ollama's `/api/tags` first, then falling back to the OpenAI-compatible `/v1/models`
- **LAN support** — point NeuConX at any machine on your local network running LM Studio, not just `localhost`. Useful if a more powerful PC on your network hosts the models
- **Pinned model support for local/LAN models** — pinning a specific Ollama/LM Studio model now works correctly; previously returned "key not configured" since local models don't use API keys
- **NCX logo** — replaced the `⬡` text/emoji branding with the new `NCXLogo.png` across the sidebar, welcome screen, onboarding flow, and favicon
- **Save button** for Local / LAN Models settings — URL and model name now persist to `.env` independently of the cloud API key form

### Fixed
- **Merge engine silently dropping local/LAN responses** — the parallel-call collector used `t.join(timeout=35)`, but local models can take up to 120s (especially cold-loading in LM Studio). Responses arriving after 35s were excluded from the result set entirely, so a 2-model request (e.g. one OpenRouter + one local model) would incorrectly look like "1 valid response" and skip merging. Collector timeout raised to `130s` — local/LAN responses are now reliably merged
- **Ollama/LM Studio 400 errors** — `_call_pinned` had no handler for `provider == 'ollama'`, falling through to "Unknown provider". Added a dedicated case using `/v1/chat/completions` against the configured `ollama_base_url`
- Error messages for local models now distinguish "cannot connect" (server not running / wrong URL) from "timed out" (model still cold-loading) — previously both showed a generic error

### Known gotchas (not bugs, but worth knowing)
- LM Studio's `/v1/models` lists every downloaded model, but only the model in the active inference slot will respond unless **"Load models on demand"** is enabled in LM Studio's server settings
- A `400 Bad Request` from LM Studio almost always means the model `id` in NeuConX Settings doesn't exactly match what `/v1/models` returns — copy it, don't retype
- First call to a newly-loaded LM Studio model can take 1-3 minutes; warm it up with a message in LM Studio's own chat UI first

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