# NeuConX — Prompt Notes
## PromptNotes_V0.0
*Last updated: June 2026 · Applies to NeuConX Version 0.0*

---

## How the Merge Engine Works

### The Big Picture

When you send a message, NeuConX doesn't just call one AI. It calls multiple models **in parallel**, collects all their answers, and then uses a **merge operator** to combine them into one clean response. The model doing the merging acts as an editor, not a judge — it doesn't pick a winner, it synthesises.

```
Your message
     │
     ▼
┌─────────────────────────────┐
│       Smart Router          │  ← classifies complexity locally, 0 tokens
│  tier1 / tier2 / tier3      │
└─────────────────────────────┘
     │
     ▼
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│  Groq    │  │ Cerebras │  │  Gemini  │  │  NVIDIA  │  ← run in parallel threads
│ (fast)   │  │ (fast)   │  │ (daily)  │  │ (40/min) │
└──────────┘  └──────────┘  └──────────┘  └──────────┘
     │              │              │              │
     └──────────────┴──────────────┴──────────────┘
                         │
                         ▼
              ┌───────────────────┐
              │   Merge Engine    │
              │                   │
              │  0 valid  → error │
              │  1 valid  → pass  │  ← no extra API call, saves quota
              │  2+ valid → merge │  ← Groq used as merge operator
              └───────────────────┘
                         │
                         ▼
                  Your final answer
```

---

## The Three Tiers

The Smart Router classifies every query **locally** (no API call, zero tokens spent) before deciding how many models to use.

| Tier | Trigger | Models Used | When |
|------|---------|-------------|------|
| **Tier 1 — Quick** | ≤8 words, no complex keywords | 1 model | "Hello", "What is Python?", "Hi" |
| **Tier 2 — Balanced** | 9–40 words, no complex signals | 2 models | Medium questions needing some context |
| **Tier 3 — Deep** | >40 words, OR contains complex keywords, OR has code blocks | All available models | Research, code, analysis, long prompts |

**Complex keywords that trigger Tier 3:**
`analyze, compare, explain, write, research, design, debug, code, generate, create, plan, build, implement, architecture, review, evaluate, summarize, translate, draft, calculate, solve, proof, essay, report, poem, story, script, refactor, fix`

You can override the tier manually using the **Auto / Quick / Balanced / Deep** buttons in the header.

---

## Model Priority Order

Models are chosen in this order. Groq and Cerebras are first because they're the fastest and have the most generous free tiers. Gemini is last because it has a hard 1,500 req/day cap.

```
1. Groq       (Llama 3.3 70B — fastest, free, generous daily limit)
2. Cerebras   (Llama 3.3 70B — fast, free)
3. Gemini     (Gemini 2.0 Flash — 1,500/day hard cap)
4. NVIDIA NIM (Llama 3.3 70B — 40 req/min free)
5. DeepSeek   (via OpenRouter — free credits)
6. Mistral    (via OpenRouter — free credits)
```

Only models with configured API keys are included. Missing keys are silently skipped.

---

## The Merge Operator

When 2+ models respond, a merge call is made using this prompt:

```
You are a merge operator. Combine these AI responses into ONE clean, complete answer.
STRICT RULES:
1. If multiple responses agree on something, include it ONCE
2. If a response adds unique information, include it
3. Do NOT add your own new information or opinions
4. Do NOT mention models, sources, or 'according to'
5. Output ONLY the final merged answer — no preamble

Original question: {your question}

--- Response 1 ---
{groq response}

--- Response 2 ---
{cerebras response}

Merged answer:
```

**The model chosen for merging is Groq → Cerebras → Gemini (fastest first).** This keeps the merge fast and avoids burning Gemini's daily quota on overhead.

**If only 1 model responds** — the merge call is skipped entirely. The single response passes through directly. No extra API call, no extra latency, no quota used.

---

## Token Budget

`max_tokens` is set dynamically per request to balance quality vs. rate limits:

| Prompt type | Token budget | Why |
|-------------|-------------|-----|
| Short conversational (≤15 words) | 1,024 | Saves quota, answers fit easily |
| Default medium | 1,536 | Balanced |
| Long prompts (>50 words) | 2,048 | More context needed |
| Code / technical keywords | 2,048 | Code can be longer |
| Explicit long-form (html, full, complete, entire…) | 4,096 | Full files/essays |

Groq's free tier has a combined input+output token budget per minute. Requesting 8,192 tokens per message (the old setting) burned through that in 2–3 messages, causing 429 errors. These conservative limits keep you well within free tier limits.

---

## Quota Exhaustion Handling

When Gemini hits its 1,500/day cap (`ResourceExhausted` error):
1. `mark_exhausted('gemini')` is called
2. `build_model_list()` skips Gemini on all future requests for this session
3. Groq/Cerebras take over automatically
4. The Gemini header dot turns orange — hover to see status
5. Quota resets at midnight (Pacific time). Restart the app to clear the exhaustion flag.

**Groq/Cerebras are NOT permanently banned on 429.** A 429 from them means "too many requests this minute" — it's temporary. They show a retry message but remain available for the next request.

---

## Prompting Tips for NeuConX

### Get Tier 3 (all models) automatically
Use any complex keyword in your prompt:

```
✅ "Explain the difference between REST and GraphQL"
✅ "Analyze this Python code for bugs"
✅ "Write a cover letter for a software engineer role"
✅ "Compare MySQL vs PostgreSQL"
```

```
❌ "REST vs GraphQL" → tier1 (too short, 3 words)
   Fix: "Compare REST vs GraphQL APIs for a microservices backend"
```

### Get better code output
Always specify the language and context:

```
✅ "Write a Python Flask route that accepts a POST request with JSON body,
    validates the input, and returns a 400 error if required fields are missing"

❌ "write flask route"
```

### Get better long-form output
Include the word `full`, `complete`, or `entire` to trigger 4,096 token budget:

```
✅ "Write a complete HTML page with inline CSS for a dark-themed login form"
✅ "Write a full README.md for a Python Flask app"
```

### Use Skills for consistent output
Toggle a skill on before asking:

- **Humanizer** — responses sound natural, no corporate jargon
- **Code Reviewer** — gets security + performance analysis, not just bugs
- **PDF Creator** — structures output with headings, sections, TL;DR
- **Researcher** — enforces Overview → Findings → Analysis → Conclusion
- **Data Analyst** — enforces observation → interpretation → recommendation

### Tier override tips
- **Quick** — use when you just want a fast single answer, no frills
- **Deep** — force all models even on a short query when you want multiple perspectives
- **Auto** — best for most things; let the router decide

---

## What the Merge Engine is NOT

- It does **not** pick the "best" model's answer and discard the others
- It does **not** fact-check responses against each other
- It does **not** add new information beyond what the models provided
- It is **not** a consensus mechanism — if all models are wrong, the merge will also be wrong

The merge operator is purely a **deduplication and union** operation. Think of it as a copy-editor merging three drafts of the same document into one.


---

*NeuConX Version 0.0 · Built by Kanaga Manikandan Gopal · June 2026*


---

## PromptNotes Appendix — Post-V0.0 Updates
*Added: June 2026*

---

## Dynamic Token Budget (Updated)

The token budget has been significantly expanded to avoid cut-off responses on complex queries. The old conservative limits caused roadmap, career, and tutorial responses to be truncated mid-sentence.

| Query type | Token budget | Triggered by |
|------------|-------------|--------------|
| Career / roadmap / plan / pivot | **8,192** | `switch`, `roadmap`, `career`, `learn`, `phase`, `curriculum`, `strategy`, `guide`, `transition`, `plan`, `pivot`... |
| Long prompts (>80 words) | **6,144** | word count |
| Full HTML / complete docs | **6,144** | `full`, `complete`, `entire` + long prompt |
| Code / technical | **4,096** | `code`, `build`, `implement`, `create`... |
| Medium prompts (>40 words) | **4,096** | word count |
| Default | **2,048** | everything else |
| Short conversational (≤10 words) | **1,024** | word count |

**Key insight:** "I want to switch from Java to RAG Engineer" is 13 words — previously bucketed as "short conversational → 1,024 tokens", causing truncation. The new `DEEPFORM_KEYWORDS` set detects structural complexity intent (roadmaps, curricula, comparisons) regardless of word count and allocates 8,192 tokens.

---

## Model Pin Selector

The header contains a small toggle (left of tier buttons) that lets you force all queries to a specific model. When ON, a dropdown appears populated with **live models fetched from each provider's `/v1/models` endpoint** — not a hardcoded list.

```
OFF (default):  [○] Auto   → auto routing applies, tier buttons active
ON:             [●] Pin:   [Groq · Llama 3.3 ▾]  → tier buttons dimmed
```

**When pinned:**
- Entire routing pipeline is bypassed
- No merge engine, no deduplication
- Model receives raw message + profile context (if personalization is ON)
- Response shows `pinned` in meta line
- Personalization badge reflects your actual toggle state (bug fixed: was always showing `◇ generic`)

**Important:** Pinned model mode still respects the Personalization toggle. Your profile, goals, and career context are injected before the message reaches the model.

---

## Free Models Only Toggle

Located in **Settings → Engine → Free Models Only** (default: ON).

When ON (default):
- OpenRouter dropdown shows only `:free` suffix models (~24 currently)
- Header dot count matches the dropdown count
- Auto routing only selects free models
- Validate badge shows free model count

When OFF (paid subscribers):
- OpenRouter shows all 341+ models
- Any model can be pinned and used
- Header dot shows full provider count

Setting persists to `data/neuconx_settings.json`. Immediately refreshes model counts and dropdown on toggle.

---

## AI Judge Mode

Alternative to the merge engine. Located in **Settings → Engine → Merge Engine** (toggle OFF to activate).

**Merge Engine ON (default):** All valid model responses are deduplicated and synthesised into one answer by a merge operator (Groq → Cerebras → Gemini, fastest first).

**Merge Engine OFF (AI Judge):** The judge model reads all candidate responses and returns the single best one verbatim. Configure:
- **Judge Provider:** Groq (recommended), Cerebras, Gemini, or Ollama
- **Judge Model:** Live dropdown of models for that provider

Judge prompt used internally:
```
You are a judge evaluating AI responses. Pick the BEST response to this question:

QUESTION: {user message}

--- Response from {model1} ---
{response1}

--- Response from {model2} ---
{response2}

Return ONLY the best response text verbatim. Do not add commentary.
```

**When to use AI Judge instead of Merge Engine:**
- When you want a single coherent voice rather than a synthesised blend
- When models are giving contradictory answers and you want the most confident one picked
- When one of your models is particularly strong for the query type

---

## Ollama / Local Model Support

Ollama runs entirely on your machine. No API key needed. Configure in **Settings → Local Models**.

**Setup:**
1. Download from [ollama.com/download](https://ollama.com/download)
2. Run: `ollama pull llama3.2` (or any supported model)
3. Start server: `ollama serve` (runs on `http://localhost:11434`)
4. Set URL and model name in Settings → Local Models
5. Click **Test Connection** to validate

**Recommended models by hardware:**

| RAM / VRAM | Recommended model |
|------------|-------------------|
| 8GB | `llama3.2` (3B), `phi3` (3.8B) |
| 16GB | `llama3.1:8b`, `mistral:7b`, `qwen2.5:7b` |
| 32GB | `llama3.1:13b`, `codellama:13b` |
| 64GB+ | `llama3.3:70b`, `qwen2.5:72b` |

**Ollama in routing:**
- Participates in auto-routing when `OLLAMA_MODEL` is set in `.env`
- Works with model pin selector (shows in dropdown)
- Can be selected as AI Judge
- Timeout set to 120s (local models are slower)
- Error messages distinguish between "Ollama not running" and actual model errors

**Prompting note:** Local models through Ollama use the same profile injection and context enrichment as cloud models. Personalization works identically.

---

## API Key Validation

Each provider row in **Settings → API Providers** has a **Validate** button. Clicking it:

1. Calls `/api/keys/validate` with the provider name and key
2. Hits the provider's live `/v1/models` endpoint
3. Returns model count and full model list
4. Shows a green badge: `12 models` on success, red `Invalid key` on failure
5. Hover the badge to see the full model list as a tooltip

The validation count respects the **Free Models Only** setting — if ON, OpenRouter shows free model count; if OFF, shows total count.

**Endpoint:** `POST /api/keys/validate`
```json
{ "provider": "groq", "key": "gsk_..." }
```
Returns: `{ "valid": true, "count": 12, "models": ["llama-3.3-70b", ...] }`

---

## Header Status Dots — Model Count

The colored dots in the header now show model count on hover instead of "READY":

- `12 Models` — provider configured, count fetched from live API
- `Ready` — provider configured, count not yet fetched (pre-load)
- `Exhausted` — daily quota hit, auto-skipped this session
- `No Key` — provider not configured

Counts are fetched 2 seconds after page load via `/api/models/counts`. After fetching, `updateModelStatusBar()` re-renders all dots with the count data. The count uses the same filter as the dropdown (Free Models Only respected).

---

## Personalization in Pinned Model Route (Bug Fix)

**Problem:** When a model was pinned, the backend hardcoded `'personalized': False` in the response regardless of the toggle state. This caused:
- Badge always showing `◇ generic` even when toggle was ON
- Profile context not being injected into the prompt

**Fix:** The pinned route now:
1. Reads `personalized` from the request payload
2. Builds the full profile context block if personalized is ON
3. Returns the actual `personalized` state in the response

Profile injection in pinned mode is identical to auto routing — name, career, goals, projects, and learned facts are all included when ON.

---

## Markdown Rendering

AI responses now render full markdown in both the main chat bubble and the right-panel model responses:

- **Headers** `#` `##` `###` — cyan-colored, sized
- **Bold** `**text**` and **Italic** `*text*`
- **Inline code** `` `code` `` — dark background, monospace
- **Code blocks** ` ```lang ``` ` — dark panel, scrollable
- **Unordered lists** `- item`
- **Ordered lists** `1. item`
- **Tables** `| col |`
- **Blockquotes** `> text` — cyan left border
- **Horizontal rules** `---`
- **Links** — open in new tab

**Security:** User messages always use `textContent` (never `innerHTML`). Only AI responses go through the markdown renderer since they are trusted backend content.

**Collapsed text handling:** Old saved conversations had newlines stripped by `bleach.clean()`. The custom parser (`marked.min.js`) includes a pre-pass that reconstructs structure from collapsed single-line markdown — detecting `### Heading`, `1. Item`, `* Bullet` patterns inline and inserting proper block breaks.

**No CDN:** `marked.min.js` is a self-contained 6KB parser bundled locally. No external network calls for rendering.

---

## Prompting Tips — Updated

### Long structured responses (roadmaps, career guides)
Just ask naturally — the DEEPFORM detector handles token allocation:

```
✅ "I want to switch from Java development to RAG Engineer"
✅ "Give me a 12-week learning plan for becoming a data engineer"
✅ "Compare LangChain vs LlamaIndex for production RAG systems"
```

These now get 8,192 tokens automatically. No need to add "full" or "complete".

### Pinned model for consistent responses
When testing a specific model or comparing outputs:
1. Toggle the pin switch (header, left of tier buttons)
2. Select the model from the dropdown
3. All messages go to that model only, no merge

### AI Judge for subjective tasks
When you want a definitive answer rather than a blended synthesis:
1. Settings → Engine → turn off Merge Engine
2. Choose a capable judge (Groq Llama 3.3 recommended)
3. All model responses are evaluated and the best returned

### Free vs Paid models
If you have an OpenRouter paid account with access to GPT-4o, Claude, etc.:
1. Settings → Engine → turn off Free Models Only
2. All 341+ OpenRouter models appear in the pin dropdown
3. Auto-routing still prioritises Groq/Cerebras first (fastest free)
4. Use pin selector to force a specific paid model when needed