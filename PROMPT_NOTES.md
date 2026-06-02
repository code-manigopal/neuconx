# NeuConX — Prompt Notes & Merge Engine Guide

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
