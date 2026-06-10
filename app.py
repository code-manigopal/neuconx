"""
NeuConX — Personal AI Platform
Phase 2 + 3: Multi-model parallel calling, smart routing, merge engine,
             session memory, conversation history, Groq + Cerebras added.

Principal Security Architect Notes:
- All inputs sanitized before processing
- Rate limiting on all endpoints
- Secure HTTP headers on every response
- API keys loaded from .env only, never hardcoded
- File upload restricted to .md extension with name sanitization
- No user data leaves the local machine except AI API calls
- CSRF protection via token validation
- Content Security Policy prevents XSS
- Merge engine only activates with 2+ valid responses (saves Gemini quota)
- Thread-safe results dict with timeout guards
"""

import os
import re
import uuid
import json
import logging
import secrets
import threading
from pathlib import Path
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, jsonify, session, abort, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv, dotenv_values
import bleach

# ── Load environment ───────────────────────────────────────────────────────────
load_dotenv(override=True)

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('NeuConX.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Suppress noisy third-party loggers (HuggingFace HTTP cache checks, etc.)
for noisy in ['httpx', 'httpcore', 'sentence_transformers', 'huggingface_hub',
              'urllib3.connectionpool', 'chromadb.telemetry']:
    logging.getLogger(noisy).setLevel(logging.WARNING)

# ── App ────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(32))
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'
app.config['SESSION_COOKIE_SECURE'] = False
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024  # 1MB

# ── Rate Limiting ──────────────────────────────────────────────────────────────
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["300 per day", "60 per hour"],
    storage_uri="memory://"
)

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
SKILLS_DIR = BASE_DIR / 'skills'
DATA_DIR   = BASE_DIR / 'data'
CONV_DIR   = DATA_DIR / 'conversations'
PROFILE_FILE = DATA_DIR / 'profile.json'
ENV_PATH   = BASE_DIR / '.env'

for d in [SKILLS_DIR, CONV_DIR, DATA_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── API Keys (reloaded on each request via helper) ─────────────────────────────
def get_keys():
    """
    SECURITY + FIX: Reload .env on every call so new keys apply without restart.
    Strip all keys — whitespace in .env values causes 401 errors on all providers.
    """
    env = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    def _k(name):
        return (env.get(name, '') or os.getenv(name, '') or '').strip()
    return {
        'gemini':         _k('GEMINI_API_KEY'),
        'nvidia':         _k('NVIDIA_API_KEY'),
        'openrouter':     _k('OPENROUTER_API_KEY'),
        'groq':           _k('GROQ_API_KEY'),
        'cerebras':       _k('CEREBRAS_API_KEY'),
        'ollama_model':   _k('OLLAMA_MODEL'),
        'ollama_base_url': _k('OLLAMA_BASE_URL') or 'http://localhost:11434',
    }

# ── Security Helpers ───────────────────────────────────────────────────────────

def sanitize_input(text: str, max_length: int = 10000) -> str:
    """Strip HTML, null bytes, enforce max length."""
    if not isinstance(text, str):
        return ''
    text = text[:max_length]
    text = text.replace('\x00', '')
    text = bleach.clean(text, tags=[], strip=True)
    return text.strip()


def sanitize_filename(filename: str) -> str:
    """Prevent path traversal. Force .md extension."""
    name = re.sub(r'[^a-zA-Z0-9_\-]', '_', Path(filename).stem)
    return f"{name[:64]}.md"


def add_security_headers(response):
    """Add security headers to every response."""
    response.headers['X-Content-Type-Options']  = 'nosniff'
    response.headers['X-Frame-Options']          = 'DENY'
    response.headers['X-XSS-Protection']         = '1; mode=block'
    response.headers['Referrer-Policy']          = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy']       = 'geolocation=(), microphone=(), camera=()'
    response.headers['Content-Security-Policy']  = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "connect-src 'self'; "
        "img-src 'self' data:; "
        "frame-ancestors 'none';"
    )
    response.headers.pop('Server', None)
    return response


app.after_request(add_security_headers)

# ── CSRF helper ────────────────────────────────────────────────────────────────
def csrf_valid():
    token = request.headers.get('X-CSRF-Token', '')
    sess  = session.get('csrf_token', '')
    if not token or not sess:
        return False
    return secrets.compare_digest(str(token), str(sess))

# ── Model Callers ──────────────────────────────────────────────────────────────
import requests as http_req

def _safe_history(history: list, limit: int = 10) -> list:
    """Return sanitized history slice. Preserves newlines in assistant messages."""
    out = []
    for msg in history[-limit:]:
        if not isinstance(msg, dict):
            continue
        role = 'user' if msg.get('role') == 'user' else 'assistant'
        raw  = str(msg.get('content', ''))
        if role == 'user':
            content = sanitize_input(raw, max_length=3000)
        else:
            # Preserve formatting in assistant messages — only strip null bytes
            content = raw.replace('\x00', '')[:3000]
        if content:
            out.append({'role': role, 'content': content})
    return out


def call_gemini(prompt: str, history: list, keys: dict) -> dict:
    """Gemini 2.0 Flash — 1500 req/day free."""
    key = keys.get('gemini', '')
    if not key:
        return {'model': 'gemini', 'response': '', 'error': 'No API key'}
    try:
        import google.generativeai as genai
        genai.configure(api_key=key)
        model = genai.GenerativeModel('gemini-2.0-flash')
        # Convert history to Gemini format
        gem_history = []
        for msg in _safe_history(history):
            gem_history.append({
                'role': 'user' if msg['role'] == 'user' else 'model',
                'parts': [msg['content']]
            })
        # Last item must be user — pop it and use as send_message
        if gem_history and gem_history[-1]['role'] == 'user':
            gem_history = gem_history[:-1]
        chat = model.start_chat(history=gem_history)
        resp = chat.send_message(sanitize_input(prompt, 4000))
        return {'model': 'gemini', 'response': resp.text, 'error': None}
    except Exception as e:
        err_type = type(e).__name__
        err_str  = str(e)[:100]
        # FIX: Detect quota exhaustion — mark so future requests skip Gemini automatically
        if 'ResourceExhausted' in err_type or 'quota' in err_str.lower() or 'RESOURCE_EXHAUSTED' in err_str:
            mark_exhausted('gemini')
            return {'model': 'gemini', 'response': '', 'error': 'Daily quota exhausted — auto-routing to Groq/Cerebras'}
        if '429' in err_str:
            # Temporary rate limit, not daily exhaustion
            return {'model': 'gemini', 'response': '', 'error': 'Rate limited — retry in a moment'}
        logger.error(f"Gemini error: {err_type}")
        return {'model': 'gemini', 'response': '', 'error': 'Model unavailable'}


def call_nvidia(prompt: str, history: list, keys: dict) -> dict:
    """NVIDIA NIM — Llama 3.3 70B, 40 req/min free."""
    key = keys.get('nvidia', '')
    if not key:
        return {'model': 'nvidia', 'response': '', 'error': 'No API key'}
    try:
        messages = _safe_history(history)
        messages.append({'role': 'user', 'content': sanitize_input(prompt, 4000)})
        r = http_req.post(
            'https://integrate.api.nvidia.com/v1/chat/completions',
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json={
                'model': 'meta/llama-3.3-70b-instruct',
                'messages': messages,
                'max_tokens': estimate_max_tokens(prompt),
                'temperature': 0.7
            },
            timeout=60
        )
        r.raise_for_status()
        text = r.json()['choices'][0]['message']['content']
        return {'model': 'nvidia', 'response': text, 'error': None}
    except Exception as e:
        err_str = str(e)[:200]
        err_type = type(e).__name__
        logger.error(f"NVIDIA error: {err_type} — {err_str}")
        if '429' in err_str or 'rate' in err_str.lower():
            return {'model': 'nvidia', 'response': '', 'error': 'Rate limited — wait and retry'}
        if '401' in err_str or 'unauthorized' in err_str.lower():
            return {'model': 'nvidia', 'response': '', 'error': 'Invalid API key — check Settings'}
        if 'timeout' in err_str.lower():
            return {'model': 'nvidia', 'response': '', 'error': 'Request timed out — retry'}
        return {'model': 'nvidia', 'response': '', 'error': f'Error: {err_type}'}


def call_openrouter(prompt: str, history: list, keys: dict, model_id: str, label: str) -> dict:
    """OpenRouter — DeepSeek, Mistral, etc. Free credits."""
    key = keys.get('openrouter', '')
    if not key:
        return {'model': label, 'response': '', 'error': 'No API key'}
    try:
        messages = _safe_history(history)
        messages.append({'role': 'user', 'content': sanitize_input(prompt, 4000)})
        r = http_req.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {key}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'http://localhost:5050',
                'X-Title': 'NeuConX'
            },
            json={'model': model_id, 'messages': messages, 'max_tokens': estimate_max_tokens(prompt)},
            timeout=60
        )
        r.raise_for_status()
        text = r.json()['choices'][0]['message']['content']
        return {'model': label, 'response': text, 'error': None}
    except Exception as e:
        err_str = str(e)[:200]
        err_type = type(e).__name__
        logger.error(f"OpenRouter ({label}) error: {err_type} — {err_str}")
        if '429' in err_str:
            return {'model': label, 'response': '', 'error': 'Rate limited — wait and retry'}
        if '402' in err_str or 'credit' in err_str.lower():
            return {'model': label, 'response': '', 'error': 'No credits remaining — add credits at openrouter.ai'}
        if '401' in err_str or 'unauthorized' in err_str.lower():
            return {'model': label, 'response': '', 'error': 'Invalid API key — check Settings'}
        if 'timeout' in err_str.lower():
            return {'model': label, 'response': '', 'error': 'Request timed out — retry'}
        return {'model': label, 'response': '', 'error': f'Error: {err_type}'}


def call_groq(prompt: str, history: list, keys: dict, temperature: float = 0.7) -> dict:
    """Groq — Llama 3.3 70B, extremely fast, generous free tier."""
    key = keys.get('groq', '')
    if not key:
        return {'model': 'groq', 'response': '', 'error': 'No API key'}
    try:
        messages = _safe_history(history)
        messages.append({'role': 'user', 'content': sanitize_input(prompt, 4000)})
        r = http_req.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json={
                'model': 'llama-3.3-70b-versatile',
                'messages': messages,
                'max_tokens': estimate_max_tokens(prompt),
                'temperature': 0.7
            },
            timeout=60  # longer timeout for large outputs
        )
        r.raise_for_status()
        text = r.json()['choices'][0]['message']['content']
        return {'model': 'groq', 'response': text, 'error': None}
    except Exception as e:
        err_str = str(e)[:200]
        err_type = type(e).__name__
        logger.error(f"Groq error: {err_type} — {err_str}")
        if '429' in err_str:
            # Temporary rate limit — do NOT mark exhausted permanently
            return {'model': 'groq', 'response': '', 'error': 'Rate limited — wait a moment and retry'}
        if 'timeout' in err_str.lower() or 'timed out' in err_str.lower():
            return {'model': 'groq', 'response': '', 'error': 'Request timed out — retry'}
        if '401' in err_str or 'unauthorized' in err_str.lower() or 'invalid_api_key' in err_str.lower():
            return {'model': 'groq', 'response': '', 'error': 'Invalid API key — check Settings'}
        if '503' in err_str or '502' in err_str:
            return {'model': 'groq', 'response': '', 'error': 'Groq service temporarily down'}
        return {'model': 'groq', 'response': '', 'error': f'Error: {err_type}'}


def call_cerebras(prompt: str, history: list, keys: dict, temperature: float = 0.7) -> dict:
    """Cerebras — Llama 3.3 70B, very fast inference, free tier."""
    key = keys.get('cerebras', '')
    if not key:
        return {'model': 'cerebras', 'response': '', 'error': 'No API key'}
    try:
        messages = _safe_history(history)
        messages.append({'role': 'user', 'content': sanitize_input(prompt, 4000)})
        r = http_req.post(
            'https://api.cerebras.ai/v1/chat/completions',
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json={
                'model': 'llama-3.3-70b',
                'messages': messages,
                'max_tokens': estimate_max_tokens(prompt),
                'temperature': 0.7
            },
            timeout=60
        )
        r.raise_for_status()
        text = r.json()['choices'][0]['message']['content']
        return {'model': 'cerebras', 'response': text, 'error': None}
    except Exception as e:
        err_str = str(e)[:200]
        err_type = type(e).__name__
        logger.error(f"Cerebras error: {err_type} — {err_str}")
        if '429' in err_str:
            return {'model': 'cerebras', 'response': '', 'error': 'Rate limited — wait a moment and retry'}
        if 'timeout' in err_str.lower() or 'timed out' in err_str.lower():
            return {'model': 'cerebras', 'response': '', 'error': 'Request timed out — retry'}
        if '401' in err_str or 'unauthorized' in err_str.lower():
            return {'model': 'cerebras', 'response': '', 'error': 'Invalid API key — check Settings'}
        return {'model': 'cerebras', 'response': '', 'error': f'Error: {err_type}'}


# ── Smart Router ───────────────────────────────────────────────────────────────

COMPLEX_KEYWORDS = {
    'analyze', 'analyse', 'compare', 'explain', 'write', 'research',
    'design', 'debug', 'code', 'generate', 'create', 'plan', 'build',
    'implement', 'architecture', 'review', 'evaluate', 'summarize',
    'summarise', 'translate', 'draft', 'calculate', 'solve', 'proof',
    'essay', 'report', 'poem', 'story', 'script', 'refactor', 'fix'
}

# ── Smart token budget ────────────────────────────────────────────────────────
# Long-form output keywords — requests that need large responses
LONGFORM_KEYWORDS = {
    'html', 'css', 'javascript', 'code', 'script', 'function', 'class',
    'component', 'template', 'page', 'website', 'ui', 'interface',
    'write', 'draft', 'essay', 'report', 'article', 'letter', 'email',
    'story', 'poem', 'summarize', 'summarise', 'explain', 'describe',
    'list', 'table', 'document', 'readme', 'full', 'complete', 'entire',
    'all', 'generate', 'create', 'build', 'implement', 'clone'
}

# Queries that typically produce very long structured responses
DEEPFORM_KEYWORDS = {
    'roadmap', 'curriculum', 'plan', 'strategy', 'guide', 'tutorial',
    'step by step', 'step-by-step', 'how to become', 'how do i become',
    'career', 'transition', 'switch', 'pivot', 'learn', 'learning path',
    'week', 'month', 'phase', 'syllabus', 'course', 'breakdown',
    'comprehensive', 'detailed', 'in-depth', 'thorough', 'exhaustive',
    'compare', 'comparison', 'difference between', 'pros and cons',
    'architecture', 'design', 'system', 'pipeline', 'workflow',
}

def estimate_max_tokens(prompt: str) -> int:
    """
    Dynamically set max_tokens based on what the user is asking for.

    Token limits by tier:
    - Groq free: ~6,000 tokens/min (input + output combined)
    - Cerebras free: 60 req/min
    - NVIDIA NIM: generous limits
    - OpenRouter free: varies per model

    We detect the response complexity needed and allocate accordingly.
    """
    lower = prompt.lower()
    words = lower.split()
    n = len(words)

    # Deep structured responses: roadmaps, career plans, comparisons, tutorials
    if any(k in lower for k in DEEPFORM_KEYWORDS):
        return 8192

    # Explicit long-form: full HTML, complete essays, entire documents
    explicit_long = {'html', 'css', 'full', 'complete', 'entire', 'whole'}
    if any(k in lower for k in explicit_long) and n > 10:
        return 6144

    # Code / technical content
    code_keywords = {'code', 'script', 'function', 'class', 'implement',
                     'write', 'build', 'create', 'generate', 'program'}
    if any(k in lower for k in code_keywords):
        return 4096

    # Long detailed prompts usually expect detailed answers
    if n > 80:
        return 6144
    if n > 40:
        return 4096
    if n > 20:
        return 2048

    # Short conversational
    if n <= 10:
        return 1024

    return 2048  # Default


def classify_query(text: str) -> str:
    """
    Phase 2 Smart Router — classify complexity locally, zero token cost.
    Returns tier1 / tier2 / tier3.

    Tier 1 (Quick)    — simple greetings, short factual questions → 1 model
    Tier 2 (Balanced) — medium length, some context needed → 2 models
    Tier 3 (Deep)     — complex, long, creative, or technical → all models
    """
    words  = text.split()
    count  = len(words)
    lower  = text.lower()
    has_complex = any(k in lower for k in COMPLEX_KEYWORDS)
    has_question_mark = '?' in text
    has_code = '```' in text or 'def ' in text or 'function ' in text

    if count <= 8 and not has_complex:
        return 'tier1'
    if count > 40 or has_complex or has_code:
        return 'tier3'
    return 'tier2'



# ── Quota exhaustion tracker (process-level, resets on app restart) ────────────
# SECURITY NOTE: This is a simple in-process flag. It persists until midnight
# or until the app restarts. No disk writes, no sensitive data stored.
_exhausted_models: set = set()
_exhausted_lock = threading.Lock()

def mark_exhausted(model: str):
    """Mark a model as quota-exhausted for this process lifetime."""
    with _exhausted_lock:
        _exhausted_models.add(model)
    logger.warning(f"Model '{model}' marked as quota-exhausted — will skip until restart")

def is_exhausted(model: str) -> bool:
    key = 'openrouter' if model.startswith('openrouter_') else model
    with _exhausted_lock:
        return key in _exhausted_models


# ── OpenRouter default free models for auto-routing ──────────────────────────
OPENROUTER_AUTO_MODELS = [
    'nvidia/nemotron-3-ultra-550b-a55b:free',
    'nvidia/nemotron-3-nano-30b-a3b:free',
    'qwen/qwen3-next-80b-a3b-instruct:free',
    'google/gemma-4-26b-a4b-it:free',
    'openai/gpt-oss-20b:free',
    'mistralai/mistral-7b-instruct:free',
]


def build_model_list(tier: str, keys: dict) -> list:
    """
    Build model list based on tier + available keys + quota status.

    FIX: Priority order is now Groq → Cerebras → Gemini → NVIDIA → DeepSeek → Mistral.
    Groq and Cerebras are fastest, most generous free tier, and don't exhaust daily.
    Gemini is deprioritised because it has a 1500/day hard cap.

    Quota-exhausted models are skipped automatically for the rest of the session.
    This means after Gemini hits its cap, Groq/Cerebras serve all traffic seamlessly.
    """
    # Priority: Groq first (fastest), then Cerebras, then OpenRouter (3 slots —
    # most model variety, no daily cap), then Gemini (preserve 1500/day quota),
    # then NVIDIA (tightest rate limit), then Ollama (local).
    available = []

    if keys.get('groq')      and not is_exhausted('groq'):       available.append('groq')
    if keys.get('cerebras')  and not is_exhausted('cerebras'):   available.append('cerebras')
    if keys.get('openrouter') and not is_exhausted('openrouter'):
        available.append('openrouter_1')
        available.append('openrouter_2')
        available.append('openrouter_3')
    if keys.get('gemini')    and not is_exhausted('gemini'):     available.append('gemini')
    if keys.get('nvidia')    and not is_exhausted('nvidia'):     available.append('nvidia')
    if keys.get('ollama_model') and not is_exhausted('ollama'):  available.append('ollama')

    if not available:
        fallback = []
        if keys.get('groq'):       fallback.append('groq')
        if keys.get('cerebras'):   fallback.append('cerebras')
        if keys.get('openrouter'): fallback.append('openrouter_1')
        if keys.get('gemini'):     fallback.append('gemini')
        if keys.get('nvidia'):     fallback.append('nvidia')
        return fallback[:1]

    limits = {'tier1': 1, 'tier2': 2, 'tier3': len(available)}
    return available[:limits.get(tier, 1)]



# ── Auto-Humanizer Post-Processor ─────────────────────────────────────────────

# ── Humanizer prompts: 3 passes, each targeting a different property ────────────

# ── Humanizer — single aggressive pass with system+user prompt split ────────────
# Research finding: using a SYSTEM prompt to set persona changes token distribution
# more effectively than putting everything in a user prompt.
# The model "becomes" a human editor at the system level, which shifts its
# probability distribution before it even reads the text.

HUMANIZE_SYSTEM = """You are Marcus, a 34-year-old freelance journalist and editor.
You write for print magazines, not websites. You hate buzzwords, passive voice, and
anything that sounds like it was generated by a committee or a machine.
Your editing style: ruthless on clichés, obsessed with rhythm, allergic to em dashes.
You write the way people actually think — which means imperfect, specific, and alive.
When you rewrite something, nobody can tell it was ever AI-generated."""

HUMANIZE_USER = """I need you to rewrite this text in your voice as Marcus the editor.

The text I'm giving you is AI-generated. Your job is to make it sound like you wrote it.
That means applying every one of these changes without exception:

DESTROY THESE (replace every single instance):
- Em dashes (—) and en dashes (–): use commas, colons, or new sentences instead. Zero dashes.
- "serves as", "stands as", "marks a", "represents": use is/are/has/does
- "it is worth noting", "it is important to note", "notably": just say the thing
- "furthermore", "additionally", "moreover": cut or use "and" or "also"  
- "in conclusion", "to summarize", "in summary": cut entirely, just stop
- "crucial", "pivotal", "vital", "key" (used vaguely): cut or be specific
- "showcasing", "highlighting", "underscoring", "fostering": find a real verb
- "tapestry", "landscape" (abstract), "vibrant", "robust" (metaphorical): cut
- "utilize": use
- "leverage" (verb): use
- "groundbreaking", "revolutionary", "game-changing": cut unless literally true
- "seamlessly", "effortlessly": cut
- Chatbot phrases: "Great question!", "Certainly!", "Here is a", "I hope this helps": cut

BUILD THESE IN (each one, no skipping):
1. Write at least one sentence that is 6 words or fewer. Punchy. Like this.
2. Write at least one sentence that builds across 35+ words, adding clause after clause,
   taking time to fully explore an idea before finally landing.
3. Write one fragment for rhythm. Not a full sentence. Just a phrase.
4. Start one sentence with "And" or "But" — real writers do this.
5. Add one moment where you catch yourself: "Actually — no, let me put it differently."
   or "Wait. That's not quite what I mean." Use a comma or period, not an em dash.
6. Add one rhetorical question you immediately answer. "Why does this matter? Because..."
7. Use "I" at least once if the content allows it, even mildly: "I'd put it this way..."
8. Add one concrete specific — a real or plausible name, number, year, or place.
   AI always speaks in categories. Humans speak in specifics.
9. Express one actual opinion or reaction. Not "this is interesting." Something real:
   "This surprises me more than it probably should." or "Honestly, this is the part
   most people miss."
10. Use one word that belongs to a slightly different register — formal in casual,
    casual in formal. The contrast is intentional. It signals a real person.

PRESERVE:
- Every factual claim in the original
- The overall structure and length
- Technical terms that must stay technical
- Any code, data, or numbers exactly as written

OUTPUT: Only the rewritten text. No preamble. No "Here is the rewrite:". Just the text.

TEXT TO REWRITE:
"""

# Keep old names for backward compatibility but point to new single-pass prompts
HUMANIZE_PASS1 = HUMANIZE_USER
HUMANIZE_PASS2 = HUMANIZE_USER  
HUMANIZE_PASS3 = HUMANIZE_USER

def _call_model_direct(prompt: str, keys: dict, prefer: str = 'groq',
                        temperature: float = 0.85, max_tokens: int = 3000,
                        system: str = '') -> str:
    """
    Call model with system+user prompt split.
    System prompt sets persona (shifts token distribution at model level).
    User prompt gives the specific task.
    Higher default temperature (0.85) for more unpredictable output.
    """
    import requests as _req

    def _build_messages(sys_p, user_p):
        if sys_p:
            return [
                {'role': 'system', 'content': sys_p},
                {'role': 'user',   'content': user_p}
            ]
        return [{'role': 'user', 'content': user_p}]

    def _groq(sys_p, user_p, temp, mt):
        if not keys.get('groq') or is_exhausted('groq'):
            return ''
        try:
            r = _req.post(
                'https://api.groq.com/openai/v1/chat/completions',
                headers={'Authorization': f'Bearer {keys["groq"]}',
                         'Content-Type': 'application/json'},
                json={'model': 'llama-3.3-70b-versatile',
                      'messages': _build_messages(sys_p, user_p),
                      'max_tokens': mt,
                      'temperature': temp,
                      'top_p': 0.9,
                      'frequency_penalty': 0.3,
                      'presence_penalty': 0.3},
                timeout=90
            )
            r.raise_for_status()
            return r.json()['choices'][0]['message']['content']
        except Exception as e:
            logger.debug(f"humanizer groq: {type(e).__name__}: {str(e)[:80]}")
            return ''

    def _cerebras(sys_p, user_p, temp, mt):
        if not keys.get('cerebras') or is_exhausted('cerebras'):
            return ''
        try:
            msgs = _build_messages(sys_p, user_p)
            r = _req.post(
                'https://api.cerebras.ai/v1/chat/completions',
                headers={'Authorization': f'Bearer {keys["cerebras"]}',
                         'Content-Type': 'application/json'},
                json={'model': 'llama-3.3-70b',
                      'messages': msgs,
                      'max_tokens': mt,
                      'temperature': min(temp, 1.0)},
                timeout=90
            )
            r.raise_for_status()
            return r.json()['choices'][0]['message']['content']
        except Exception as e:
            logger.debug(f"humanizer cerebras: {type(e).__name__}: {str(e)[:80]}")
            return ''

    sys_prompt  = system or HUMANIZE_SYSTEM
    user_prompt = prompt  # prompt already contains the full task + text

    if prefer == 'groq':
        result = _groq(sys_prompt, user_prompt, temperature, max_tokens)
        if result: return result
        return _cerebras(sys_prompt, user_prompt, temperature, max_tokens)
    else:
        result = _cerebras(sys_prompt, user_prompt, temperature, max_tokens)
        if result: return result
        return _groq(sys_prompt, user_prompt, temperature, max_tokens)


def humanize_output(text: str, keys: dict) -> str:
    """
    Single-pass humanizer with system+user prompt split.

    Key insight: using a CHARACTER PERSONA in the system prompt changes the model's
    token distribution at a fundamental level — not just what words it picks, but
    how it constructs sentences. "Be Marcus the editor" shifts burstiness and
    perplexity more effectively than any number of explicit rules alone.

    Combined with:
    - frequency_penalty=0.3 (discourages repeating common AI phrases)
    - presence_penalty=0.3 (encourages novel vocabulary)
    - temperature=0.85 (high enough for unpredictability, low enough for coherence)
    """
    if not text or len(text.strip()) < 50:
        return text

    # Skip if mostly code
    lines = text.split('\n')
    code_lines = sum(1 for l in lines if l.strip().startswith(
        ('def ', 'class ', '```', 'import ', 'from ', 'return ', '//', '/*', '#include', '    ')))
    if code_lines / max(1, len(lines)) > 0.5:
        return text

    cap = text[:5000]
    full_prompt = HUMANIZE_USER + cap

    logger.info("Humanizer: single-pass with persona system prompt")
    result = _call_model_direct(
        prompt=full_prompt,
        keys=keys,
        prefer='groq',
        temperature=0.85,
        max_tokens=3000,
        system=HUMANIZE_SYSTEM
    )

    if result and len(result) > 50:
        logger.info(f"Humanizer complete: {len(result)} chars")
        return result

    logger.warning("Humanizer failed — returning original")
    return text

# ── Merge Engine ───────────────────────────────────────────────────────────────

def merge_responses(prompt: str, responses: list, keys: dict) -> str:
    """
    Phase 2 Merge Engine:
    - If 0 valid responses → friendly error message
    - If 1 valid response → return it directly (NO extra Gemini call = saves quota)
    - If 2+ valid responses → semantic merge via fastest available model
    
    FIX: Previously always called Gemini for merge, burning quota.
         Now only merges when needed, and uses Groq/Cerebras first (faster + free).
    """
    valid = [r for r in responses if r.get('response') and not r.get('error')]

    if not valid:
        errors = [r.get('error', 'unknown') for r in responses]
        unique_errors = list(dict.fromkeys(errors))
        exhausted = [r['model'] for r in responses
                     if 'quota' in (r.get('error') or '').lower()
                     or 'exhausted' in (r.get('error') or '').lower()]
        if exhausted:
            # Mark them all for future skipping
            for m in exhausted:
                mark_exhausted(m)
            return (
                f"⚠️ **{', '.join(exhausted).title()} quota exhausted.**\n\n"
                "NeuConX will automatically route around it next message.\n\n"
                "**Available alternatives already configured:**\n"
                + ("- ✅ Groq (will be used automatically)\n" if keys.get('groq') else "- ❌ Groq — add key at console.groq.com (free)\n")
                + ("- ✅ Cerebras (will be used automatically)\n" if keys.get('cerebras') else "- ❌ Cerebras — add key at cloud.cerebras.ai (free)\n")
                + ("- ✅ NVIDIA NIM (will be used automatically)\n" if keys.get('nvidia') else "")
                + "\n**Just send your message again — quota model is now skipped automatically.**"
            )
        return (
            "⚠️ No models responded successfully.\n\n"
            f"Errors: {', '.join(unique_errors)}\n\n"
            "Go to ⚙ Settings to check your API keys."
        )

    # Single response — return directly, no merge needed
    if len(valid) == 1:
        return valid[0]['response']

    # 2+ responses — merge them
    merge_prompt = (
        "You are a merge operator. Combine these AI responses into ONE clean, complete answer.\n"
        "STRICT RULES:\n"
        "1. If multiple responses agree on something, include it ONCE\n"
        "2. If a response adds unique information, include it\n"
        "3. Do NOT add your own new information or opinions\n"
        "4. Do NOT mention models, sources, or 'according to'\n"
        "5. Output ONLY the final merged answer — no preamble\n\n"
        f"Original question: {sanitize_input(prompt, 300)}\n\n"
    )
    for i, r in enumerate(valid, 1):
        merge_prompt += f"--- Response {i} ---\n{r['response'][:1500]}\n\n"
    merge_prompt += "Merged answer:"

    # Use fastest available model for merge (prefer Groq > Cerebras > Gemini)
    if keys.get('groq'):
        result = call_groq(merge_prompt, [], keys)
    elif keys.get('cerebras'):
        result = call_cerebras(merge_prompt, [], keys)
    elif keys.get('gemini'):
        result = call_gemini(merge_prompt, [], keys)
    else:
        result = {'response': ''}

    if result.get('response'):
        return result['response']

    # Fallback: return longest response
    return max(valid, key=lambda x: len(x.get('response', '')))['response']


# ── Phase 3: Session Memory ────────────────────────────────────────────────────

class SessionMemory:
    """
    Phase 3: In-process session memory store.
    Keyed by session ID. Stores last N messages per session.
    Thread-safe via lock.
    SECURITY: Memory is in-process only. Never written to disk here.
              Disk persistence is handled by the conversations API separately.
    """
    def __init__(self, max_messages: int = 20):
        self._store: dict[str, list] = {}
        self._lock  = threading.Lock()
        self._max   = max_messages

    def get(self, session_id: str) -> list:
        with self._lock:
            return list(self._store.get(session_id, []))

    def append(self, session_id: str, role: str, content: str):
        with self._lock:
            if session_id not in self._store:
                self._store[session_id] = []
            self._store[session_id].append({
                'role': role,
                'content': content,
                'timestamp': datetime.now().isoformat()
            })
            # Keep only last N messages
            self._store[session_id] = self._store[session_id][-self._max:]

    def clear(self, session_id: str):
        with self._lock:
            self._store.pop(session_id, None)

    def set_from_history(self, session_id: str, history: list):
        """Load history from client into server memory."""
        with self._lock:
            clean = []
            for msg in history[-self._max:]:
                if isinstance(msg, dict):
                    content = sanitize_input(str(msg.get('content', '')), 4000)
                    role    = 'user' if msg.get('role') == 'user' else 'assistant'
                    if content:
                        clean.append({'role': role, 'content': content,
                                      'timestamp': msg.get('timestamp', datetime.now().isoformat())})
            self._store[session_id] = clean


memory = SessionMemory(max_messages=20)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    if 'session_id' not in session:
        session['session_id'] = uuid.uuid4().hex
    return render_template(
        'index.html',
        csrf_token=session['csrf_token'],
        onboarding_complete=PROFILE_FILE.exists()
    )


@app.route('/api/csrf-token')
def get_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return jsonify({'token': session['csrf_token']})


@app.route('/api/chat', methods=['POST'])
@limiter.limit("30 per minute")
def chat():
    """
    Phase 2+3 Chat endpoint.
    - Loads keys fresh from .env (no restart needed after adding keys)
    - Calls models in parallel based on tier
    - Merges only when 2+ models respond (saves Gemini quota)
    - Stores messages in session memory (Phase 3)
    """
    if not csrf_valid():
        abort(403)

    data = request.get_json(silent=True)
    if not data:
        abort(400)

    message = sanitize_input(data.get('message', ''), max_length=8000)
    if not message:
        return jsonify({'error': 'Message cannot be empty'}), 400

    # Default enriched to plain message — overwritten later with profile/skill context
    # Must be set here so Python's compiler doesn't treat it as unbound in early-exit branches
    enriched = message

    # AutoTune: client sends detected context + optimal temperature
    # We use it to set temperature per call instead of always 0.7
    autotune = data.get('autotune', {})
    autotune_temp = float(autotune.get('temperature', 0.7))
    autotune_top_p = float(autotune.get('top_p', 0.9))
    autotune_context = str(autotune.get('context', 'conversational'))
    # Clamp to safe ranges
    autotune_temp  = max(0.1, min(1.5, autotune_temp))
    autotune_top_p = max(0.5, min(1.0, autotune_top_p))
    logger.info(f"AutoTune: context={autotune_context} temp={autotune_temp} top_p={autotune_top_p}")

    # Load keys fresh every request — no restart needed
    keys = get_keys()

    # Phase 3: Sync client history into server memory
    sess_id = session.get('session_id', uuid.uuid4().hex)
    client_history = data.get('history', [])
    if client_history and isinstance(client_history, list):
        memory.set_from_history(sess_id, client_history)

    # Get server-side memory (most accurate)
    history = memory.get(sess_id)

    # Tier routing
    tier_override = data.get('tier_override', '')
    tier = tier_override if tier_override in ['tier1', 'tier2', 'tier3'] else classify_query(message)

    # ── Pinned model: bypass auto routing, call exact model on exact provider ──
    pinned_raw = data.get('pinned_model', None)
    # pinned_raw can be None or {provider: str, modelId: str}
    pinned_provider = None
    pinned_model_id = None

    if isinstance(pinned_raw, dict):
        pinned_provider = sanitize_input(str(pinned_raw.get('provider', '')), 50).lower()
        pinned_model_id = sanitize_input(str(pinned_raw.get('modelId', '')), 200)

    PROVIDER_KEY_MAP = {
    'groq':       keys.get('groq'),
    'cerebras':   keys.get('cerebras'),
    'gemini':     keys.get('gemini'),
    'nvidia':     keys.get('nvidia'),
    'openrouter': keys.get('openrouter'),
    'ollama':     keys.get('ollama_model') or 'local',  # ← ADD THIS
    }

    if pinned_provider and pinned_model_id:
        provider_key = PROVIDER_KEY_MAP.get(pinned_provider)
        if not provider_key:
            return jsonify({
                'final_answer': (
                    f"⚠️ **{pinned_provider.title()} key not configured.**\n\n"
                    f"Add the API key in ⚙ Settings, then try again."
                ),
                'model_responses': [],
                'tier_used': f'pinned:{pinned_provider}',
                'models_used': 0,
                'models_called': []
            }), 200

        # Call the exact model directly, skip merge entirely
        logger.info(f"Pinned model: {pinned_provider}/{pinned_model_id}")

        def _call_pinned(provider: str, model_id: str, prompt: str,
                         hist: list, k: dict) -> dict:
            """Call a specific model on a specific provider with an exact model ID."""
            try:
                if provider == 'groq':
                    r = http_req.post(
                        'https://api.groq.com/openai/v1/chat/completions',
                        headers={'Authorization': f'Bearer {k["groq"]}',
                                 'Content-Type': 'application/json'},
                        json={'model': model_id,
                              'messages': _safe_history(hist) + [{'role':'user','content': sanitize_input(prompt, 4000)}],
                              'max_tokens': estimate_max_tokens(prompt),
                              'temperature': 0.7},
                        timeout=60
                    )
                    r.raise_for_status()
                    return {'model': model_id, 'provider': provider,
                            'response': r.json()['choices'][0]['message']['content'],
                            'error': None}

                elif provider == 'cerebras':
                    r = http_req.post(
                        'https://api.cerebras.ai/v1/chat/completions',
                        headers={'Authorization': f'Bearer {k["cerebras"]}',
                                 'Content-Type': 'application/json'},
                        json={'model': model_id,
                              'messages': _safe_history(hist) + [{'role':'user','content': sanitize_input(prompt, 4000)}],
                              'max_tokens': estimate_max_tokens(prompt),
                              'temperature': 0.7},
                        timeout=60
                    )
                    r.raise_for_status()
                    return {'model': model_id, 'provider': provider,
                            'response': r.json()['choices'][0]['message']['content'],
                            'error': None}

                elif provider == 'nvidia':
                    r = http_req.post(
                        'https://integrate.api.nvidia.com/v1/chat/completions',
                        headers={'Authorization': f'Bearer {k["nvidia"]}',
                                 'Content-Type': 'application/json'},
                        json={'model': model_id,
                              'messages': _safe_history(hist) + [{'role':'user','content': sanitize_input(prompt, 4000)}],
                              'max_tokens': estimate_max_tokens(prompt),
                              'temperature': 0.7},
                        timeout=60
                    )
                    r.raise_for_status()
                    return {'model': model_id, 'provider': provider,
                            'response': r.json()['choices'][0]['message']['content'],
                            'error': None}

                elif provider == 'openrouter':
                    or_key = (k.get('openrouter') or '').strip()
                    if not or_key:
                        return {'model': model_id, 'provider': provider,
                                'response': '', 'error': 'No OpenRouter API key configured'}
                    r = http_req.post(
                        'https://openrouter.ai/api/v1/chat/completions',
                        headers={
                            'Authorization': f'Bearer {or_key}',
                            'Content-Type': 'application/json',
                            'HTTP-Referer': 'http://localhost:5050',
                            'X-Title': 'NeuConX'
                        },
                        json={
                            'model': model_id,
                            'messages': _safe_history(hist) + [{'role': 'user', 'content': sanitize_input(prompt, 4000)}],
                            'max_tokens': estimate_max_tokens(prompt)
                        },
                        timeout=180   # Large models on free tier can be slow
                    )
                    # OpenRouter returns error details in JSON even on 4xx
                    if not r.ok:
                        try:
                            err_body = r.json()
                            err_msg = err_body.get('error', {}).get('message', r.reason)
                        except Exception:
                            err_msg = r.reason
                        if r.status_code == 401:
                            return {'model': model_id, 'provider': provider, 'response': '',
                                    'error': f'OpenRouter 401: {err_msg} — check your API key in Settings'}
                        if r.status_code == 402:
                            return {'model': model_id, 'provider': provider, 'response': '',
                                    'error': f'OpenRouter 402: No credits — {err_msg}'}
                        if r.status_code == 429:
                            return {'model': model_id, 'provider': provider, 'response': '',
                                    'error': 'OpenRouter rate limited — wait a moment and retry'}
                        return {'model': model_id, 'provider': provider, 'response': '',
                                'error': f'OpenRouter {r.status_code}: {err_msg}'}
                    r.raise_for_status()
                    return {'model': model_id, 'provider': provider,
                            'response': r.json()['choices'][0]['message']['content'],
                            'error': None}

                elif provider == 'gemini':
                    import google.generativeai as genai
                    genai.configure(api_key=k['gemini'])
                    gmodel = genai.GenerativeModel(model_id)
                    resp = gmodel.generate_content(sanitize_input(prompt, 4000))
                    return {'model': model_id, 'provider': provider,
                            'response': resp.text, 'error': None}

                elif provider == 'ollama':
                    base_url = k.get('ollama_base_url', 'http://localhost:11434').rstrip('/')
                    if base_url.endswith('/v1'):
                        base_url = base_url[:-3]
                    r = http_req.post(
                        f'{base_url}/v1/chat/completions',
                        headers={'Content-Type': 'application/json'},
                        json={
                            'model': model_id,
                            'messages': _safe_history(hist) + [{'role': 'user', 'content': sanitize_input(prompt, 4000)}]
                        },
                        timeout=120
                    )
                    r.raise_for_status()
                    return {'model': model_id, 'provider': provider,
                            'response': r.json()['choices'][0]['message']['content'],
                            'error': None}

                return {'model': model_id, 'provider': provider,
                        'response': '', 'error': f'Unknown provider: {provider}'}

            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:100]}"
                logger.error(f"Pinned model call failed ({provider}/{model_id}): {err}")
                return {'model': model_id, 'provider': provider,
                        'response': '', 'error': err}

        # Respect personalization toggle for pinned model too
        personalized_pin = bool(data.get('personalized', True))

        # Build enriched prompt with profile if personalized
        pin_prompt = message
        if personalized_pin and PROFILE_FILE.exists():
            try:
                profile = json.loads(PROFILE_FILE.read_text(encoding='utf-8'))
                profile_lines = []
                field_labels = {
                    'identity': 'Name/Location', 'education': 'Education',
                    'career': 'Career', 'goals': 'Goals', 'projects': 'Projects',
                }
                for key_f, label in field_labels.items():
                    val = profile.get(key_f)
                    if val and isinstance(val, str) and val.strip():
                        profile_lines.append(f"- {label}: {val[:200]}")
                facts = profile.get('learned_facts', [])
                if facts:
                    profile_lines.append(f"- Known facts: {'; '.join(facts[:10])}")
                if profile_lines:
                    profile_block = "ABOUT THE USER:\n" + "\n".join(profile_lines)
                    pin_prompt = f"{profile_block}\n\n---\n\nUser message: {message}"
            except Exception:
                pass

        result = _call_pinned(pinned_provider, pinned_model_id, pin_prompt, history, keys)
        final  = result.get('response') or f"⚠️ {result.get('error', 'No response')}"

        memory.append(sess_id, 'user', message)
        memory.append(sess_id, 'assistant', final)
        if CHROMA_AVAILABLE or _init_chroma():
            embed_message('user', message, sess_id, datetime.now().isoformat())
            embed_message('assistant', final, sess_id, datetime.now().isoformat())
        extract_memory_candidates(message, final, sess_id)

        return jsonify({
            'final_answer':    final,
            'model_responses': [result],
            'tier_used':       'pinned',
            'models_used':     1 if result.get('response') else 0,
            'models_called':   [pinned_model_id],
            'personalized':    personalized_pin,
            'humanized':       False
        })

    else:
        # Normal auto routing
        models_to_call = build_model_list(tier, keys)

    if not models_to_call:
        return jsonify({
            'final_answer': (
                "⚠️ **No API keys configured.**\n\n"
                "Open ⚙ Settings and add at least one key:\n"
                "- **Gemini**: aistudio.google.com (free, 1500/day)\n"
                "- **Groq**: console.groq.com (free, very fast)\n"
                "- **Cerebras**: cloud.cerebras.ai (free)\n"
                "- **NVIDIA NIM**: build.nvidia.com (free)\n"
                "- **OpenRouter**: openrouter.ai (free credits)\n"
            ),
            'model_responses': [],
            'tier_used': tier,
            'models_used': 0,
            'models_called': []
        }), 200

    # ── Build system context ──────────────────────────────────────────────────
    system_parts = []
    personalized = bool(data.get('personalized', True))  # default ON

    # 1. User profile + learned facts — only when personalized mode is ON
    if personalized and PROFILE_FILE.exists():
        try:
            profile = json.loads(PROFILE_FILE.read_text(encoding='utf-8'))
            profile_lines = []
            field_labels = {
                'identity':      'Name/Location',
                'education':     'Education',
                'career':        'Career',
                'goals':         'Current Goals',
                'style':         'Response Style Preference',
                'projects':      'Current Projects',
                'working_style': 'Working Style',
            }
            for key, label in field_labels.items():
                val = profile.get(key)
                if val and isinstance(val, str) and val.strip():
                    profile_lines.append(f"- {label}: {val[:200]}")
            facts = profile.get('learned_facts', [])
            if facts:
                profile_lines.append(f"- Known facts: {'; '.join(facts[:10])}")
            if profile_lines:
                system_parts.append(
                    "ABOUT THE USER (use this to personalise your response):\n" + "\n".join(profile_lines)
                )
        except Exception:
            pass

    # 2. Active skills — always applied regardless of personalization mode
    skills_active = data.get('skills_active', [])
    if isinstance(skills_active, list):
        for skill_name in skills_active[:5]:
            safe_skill = sanitize_filename(str(skill_name))
            skill_path = SKILLS_DIR / safe_skill
            if skill_path.exists():
                try:
                    system_parts.append(
                        f"ACTIVE SKILL — {safe_skill}:\n{skill_path.read_text(encoding='utf-8')[:2000]}"
                    )
                except Exception:
                    pass

    # 3. Relevant semantic memory — only when personalized mode is ON
    if personalized and (CHROMA_AVAILABLE or _init_chroma()):
        try:
            mem_results = semantic_search(message, n_results=3)
            if mem_results:
                mem_snippets = []
                for r in mem_results:
                    if r['relevance'] > 0.55:
                        mem_snippets.append(f"- [{r['role']}]: {r['content'][:200]}")
                if mem_snippets:
                    system_parts.append(
                        "RELEVANT CONTEXT FROM PAST CONVERSATIONS:\n" + "\n".join(mem_snippets)
                    )
        except Exception:
            pass

    # Assemble enriched prompt
    if system_parts:
        system_block = "\n\n---\n\n".join(system_parts)
        enriched = f"{system_block}\n\n---\n\nUser message: {message}"
    else:
        enriched = message

    # Parallel model calls
    results: dict = {}
    lock = threading.Lock()

    def run(model_key: str):
        import time
        def _call():
            if model_key == 'gemini':
                return call_gemini(enriched, history, keys)
            elif model_key == 'nvidia':
                return call_nvidia(enriched, history, keys)
            elif model_key == 'deepseek':
                return call_openrouter(enriched, history, keys, 'deepseek/deepseek-chat', 'deepseek')
            elif model_key == 'mistral':
                return call_openrouter(enriched, history, keys, 'mistralai/mistral-7b-instruct', 'mistral')
            elif model_key == 'groq':
                return call_groq(enriched, history, keys, temperature=autotune_temp)
            elif model_key == 'cerebras':
                return call_cerebras(enriched, history, keys, temperature=autotune_temp)
            elif model_key == 'openrouter_1':
                return call_openrouter(enriched, history, keys, OPENROUTER_AUTO_MODELS[0], 'openrouter_1')
            elif model_key == 'openrouter_2':
                return call_openrouter(enriched, history, keys, OPENROUTER_AUTO_MODELS[1], 'openrouter_2')
            elif model_key == 'openrouter_3':
                return call_openrouter(enriched, history, keys, OPENROUTER_AUTO_MODELS[2], 'openrouter_3')
            elif model_key == 'ollama':
                return call_ollama(enriched, history, keys)
            return {'model': model_key, 'response': '', 'error': 'Unknown model'}

        r = _call()

        # Auto-retry once on transient errors (timeout, connection reset, 503)
        if r.get('error') and any(x in (r.get('error') or '') for x in ['timed out', 'timeout', 'temporarily down', 'retry']):
            logger.info(f"Retrying {model_key} after transient error: {r.get('error')}")
            time.sleep(1)
            r = _call()

        # Track usage
        if not (r.get('error') == 'No API key'):
            track_key = 'openrouter' if model_key.startswith('openrouter_') else model_key
            usage_tracker.record(track_key)
        with lock:
            results[model_key] = r

    threads = [threading.Thread(target=run, args=(m,)) for m in models_to_call]
    for t in threads: t.start()
    for t in threads: t.join(timeout=35)

    responses = list(results.values())
    # Feature 4: Merge Engine or AI Judge
    app_settings = load_neuconx_settings()
    if app_settings.get('merge_engine_enabled', True):
        # Default: merge engine combines all responses
        final = merge_responses(message, responses, keys)
    else:
        # AI Judge mode: pick the best single response
        judge_provider = app_settings.get('judge_provider', 'groq')
        judge_model    = app_settings.get('judge_model', '')
        valid_responses = [r for r in responses if r.get('response') and not r.get('error')]

        if not valid_responses:
            final = "⚠️ No valid responses received."
        elif len(valid_responses) == 1:
            final = valid_responses[0]['response']
        else:
            # Build judge prompt
            candidates = "\n\n".join([
                f"--- Response from {r['model']} ---\n{r['response'][:2000]}"
                for r in valid_responses
            ])
            judge_prompt = (
                f"You are a judge evaluating AI responses. Pick the BEST response to this question:\n\n"
                f"QUESTION: {sanitize_input(message, 500)}\n\n"
                f"{candidates}\n\n"
                f"Return ONLY the best response text verbatim. Do not add commentary."
            )
            if judge_provider == 'groq':
                judge_result = call_groq(judge_prompt, [], keys)
            elif judge_provider == 'cerebras':
                judge_result = call_cerebras(judge_prompt, [], keys)
            elif judge_provider == 'gemini':
                judge_result = call_gemini(judge_prompt, [], keys)
            elif judge_provider == 'ollama':
                judge_result = call_ollama(judge_prompt, [], keys, judge_model)
            else:
                judge_result = call_groq(judge_prompt, [], keys)
            final = judge_result.get('response') or valid_responses[0]['response']

    humanized = False  # kept for backward compat

    # Phase 3: Store in session memory
    memory.append(sess_id, 'user', message)
    memory.append(sess_id, 'assistant', final)

    # Phase 5: Embed messages into ChromaDB for semantic search
    if CHROMA_AVAILABLE or _init_chroma():
        embed_message('user', message, sess_id, datetime.now().isoformat())
        embed_message('assistant', final, sess_id, datetime.now().isoformat())

    # Phase 6: Extract memory candidates from this exchange
    extract_memory_candidates(message, final, sess_id)

    return jsonify({
        'final_answer':    final,
        'model_responses': [
            {'model': r['model'], 'response': r.get('response', ''), 'error': r.get('error')}
            for r in responses
        ],
        'tier_used':    tier,
        'models_used':  len([r for r in responses if r.get('response')]),
        'models_called': models_to_call,
        'personalized':  personalized,
        'humanized':     humanized
    })


@app.route('/api/memory/clear', methods=['POST'])
@limiter.limit("20 per minute")
def clear_memory():
    """Phase 3: Clear session memory for current user."""
    if not csrf_valid():
        abort(403)
    sess_id = session.get('session_id', '')
    if sess_id:
        memory.clear(sess_id)
    return jsonify({'status': 'cleared'})


@app.route('/api/memory', methods=['GET'])
@limiter.limit("30 per minute")
def get_memory():
    """Phase 3: Return current session memory (for debugging / display)."""
    sess_id = session.get('session_id', '')
    msgs = memory.get(sess_id)
    return jsonify({'messages': msgs, 'count': len(msgs)})


# ── Usage Tracker ─────────────────────────────────────────────────────────────

class UsageTracker:
    """
    Track per-model API call counts in-process.
    Resets on app restart. Gives the frontend data to show in hover tooltips.
    Thread-safe via lock.

    Free tier limits (approximate, for display only):
      Gemini:   1,500 req/day
      Groq:     14,400 req/day (generous daily limit)
      Cerebras: 60 req/min
      NVIDIA:   40 req/min (2,400/hr)
      OpenRouter: credit-based
    """
    LIMITS = {
        'gemini':     {'limit': 1500,  'reset': 'daily',  'unit': 'req/day'},
        'groq':       {'limit': 14400, 'reset': 'daily',  'unit': 'req/day'},
        'cerebras':   {'limit': 60,    'reset': 'minute', 'unit': 'req/min'},
        'nvidia':     {'limit': 40,    'reset': 'minute', 'unit': 'req/min'},
        'deepseek':   {'limit': None,  'reset': 'credit', 'unit': 'credits'},
        'mistral':    {'limit': None,  'reset': 'credit', 'unit': 'credits'},
        'openrouter': {'limit': None,  'reset': 'credit', 'unit': 'credits'},
    }

    def __init__(self):
        self._counts: dict = {}   # { model: int }
        self._start: datetime = datetime.now()
        self._lock = threading.Lock()

    def record(self, model: str):
        with self._lock:
            self._counts[model] = self._counts.get(model, 0) + 1

    def get_all(self) -> dict:
        """Return usage stats for all models."""
        with self._lock:
            counts = dict(self._counts)
        now = datetime.now()
        elapsed_secs = (now - self._start).total_seconds()
        result = {}
        for model, info in self.LIMITS.items():
            used  = counts.get(model, 0)
            limit = info['limit']
            reset = info['reset']
            pct   = round((used / limit) * 100, 1) if limit else None

            # Estimate reset time
            if reset == 'daily':
                remaining_secs = max(0, 86400 - elapsed_secs)
                h = int(remaining_secs // 3600)
                m = int((remaining_secs % 3600) // 60)
                reset_in = f"{h}h {m}m"
            elif reset == 'minute':
                reset_in = "~1 min rolling"
            else:
                reset_in = "per credit balance"

            result[model] = {
                'used':     used,
                'limit':    limit,
                'pct':      pct,
                'unit':     info['unit'],
                'resetIn':  reset_in,
            }
        return result


usage_tracker = UsageTracker()


@app.route('/api/usage', methods=['GET'])
@limiter.limit("60 per minute")
def get_usage():
    """Return per-model usage stats for tooltip display."""
    return jsonify(usage_tracker.get_all())


# ── Conversations ──────────────────────────────────────────────────────────────

@app.route('/api/conversations', methods=['GET'])
@limiter.limit("60 per minute")
def list_conversations():
    convs = []
    for f in sorted(CONV_DIR.glob('*.json'), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            convs.append({
                'id':            data.get('id', f.stem),
                'title':         sanitize_input(data.get('title', 'Untitled'), 100),
                'created_at':    data.get('created_at', ''),
                'updated_at':    data.get('updated_at', ''),
                'message_count': len(data.get('messages', []))
            })
        except Exception:
            pass
    return jsonify(convs)


@app.route('/api/conversations/<conv_id>', methods=['GET'])
@limiter.limit("60 per minute")
def get_conversation(conv_id):
    if not re.match(r'^[a-zA-Z0-9_\-]{1,64}$', conv_id):
        abort(400)
    conv_file = CONV_DIR / f'{conv_id}.json'
    if not conv_file.exists():
        abort(404)
    try:
        return jsonify(json.loads(conv_file.read_text(encoding='utf-8')))
    except Exception:
        abort(500)


@app.route('/api/conversations', methods=['POST'])
@limiter.limit("30 per minute")
def save_conversation():
    if not csrf_valid():
        abort(403)
    data = request.get_json(silent=True)
    if not data:
        abort(400)

    conv_id = data.get('id') or f"conv_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    if not re.match(r'^[a-zA-Z0-9_\-]{1,64}$', conv_id):
        abort(400)

    title = sanitize_input(data.get('title', 'New Conversation'), 100) or 'New Conversation'
    messages = []
    for msg in data.get('messages', [])[-200:]:
        if isinstance(msg, dict):
            role = 'user' if msg.get('role') == 'user' else 'assistant'
            raw  = str(msg.get('content', ''))
            if role == 'user':
                # User input: full sanitization (strip HTML, null bytes)
                content = sanitize_input(raw, 8000)
            else:
                # Assistant output: preserve newlines and formatting
                # Only remove null bytes and enforce length — no bleach strip
                content = raw.replace('\x00', '')[:8000]
            messages.append({
                'role':      role,
                'content':   content,
                'timestamp': msg.get('timestamp', datetime.now().isoformat())
            })

    conv_data = {
        'id':         conv_id,
        'title':      title,
        'created_at': data.get('created_at', datetime.now().isoformat()),
        'updated_at': datetime.now().isoformat(),
        'messages':   messages
    }
    (CONV_DIR / f'{conv_id}.json').write_text(
        json.dumps(conv_data, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    return jsonify({'id': conv_id, 'status': 'saved'})


@app.route('/api/conversations/<conv_id>', methods=['DELETE'])
@limiter.limit("20 per minute")
def delete_conversation(conv_id):
    if not csrf_valid():
        abort(403)
    if not re.match(r'^[a-zA-Z0-9_\-]{1,64}$', conv_id):
        abort(400)
    f = CONV_DIR / f'{conv_id}.json'
    if f.exists():
        f.unlink()
    return jsonify({'status': 'deleted'})


# ── Skills ─────────────────────────────────────────────────────────────────────




# ── Settings ───────────────────────────────────────────────────────────────────

@app.route('/api/settings', methods=['GET'])
@limiter.limit("20 per minute")
def get_settings():
    """Return configuration status. NEVER return actual key values."""
    keys = get_keys()
    configured = {}
    hints      = {}
    for name in ['gemini', 'nvidia', 'openrouter', 'groq', 'cerebras']:
        val = keys.get(name, '')
        configured[name] = bool(val)
        hints[name]      = f"...{val[-4:]}" if val else None
    with _exhausted_lock:
        exhausted_list = list(_exhausted_models)
    ollama_model = keys.get('ollama_model', '')
    ollama_base  = keys.get('ollama_base_url', '')
    return jsonify({
        **{f'{k}_configured': v for k, v in configured.items()},
        **{f'{k}_hint':       v for k, v in hints.items()},
        'any_configured':    any(configured.values()) or bool(ollama_model),
        'ollama_configured': bool(ollama_model),
        'ollama_hint':       ollama_base or 'localhost:11434',
        'ollama_model':      ollama_model,
        'ollama_base_url':   ollama_base,
        'exhausted_models':  exhausted_list
    })


@app.route('/api/settings', methods=['POST'])
@limiter.limit("5 per minute")
def save_settings():
    """
    Save API keys to .env.
    FIX: Keys reload on next request without restarting the app.
    """
    if not csrf_valid():
        abort(403)
    data = request.get_json(silent=True)
    if not data:
        abort(400)

    key_pattern = re.compile(r'^[a-zA-Z0-9_\-\.]{10,300}$')
    env_map = {
        'gemini_key':     'GEMINI_API_KEY',
        'nvidia_key':     'NVIDIA_API_KEY',
        'openrouter_key': 'OPENROUTER_API_KEY',
        'groq_key':       'GROQ_API_KEY',
        'cerebras_key':   'CEREBRAS_API_KEY',
    }

    # Load existing .env to preserve values not being updated
    existing = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}

    for field, env_var in env_map.items():
        val = data.get(field, '').strip()
        if val:
            if not key_pattern.match(val):
                return jsonify({'error': f'Invalid key format for {field}'}), 400
            existing[env_var] = val

    # Ollama / LM Studio — URL and model (not API keys, skip key_pattern check)
    ollama_url   = sanitize_input(str(data.get('ollama_base_url', '')), 300).strip()
    ollama_model = sanitize_input(str(data.get('ollama_model',    '')), 200).strip()
    if ollama_url:   existing['OLLAMA_BASE_URL'] = ollama_url
    if ollama_model: existing['OLLAMA_MODEL']    = ollama_model

    # Preserve SECRET_KEY
    if os.getenv('SECRET_KEY'):
        existing['SECRET_KEY'] = os.getenv('SECRET_KEY')

    lines = [f"{k}={v}" for k, v in existing.items() if v]
    ENV_PATH.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    logger.info("Settings updated")
    return jsonify({'status': 'saved', 'message': 'Keys saved. Active on next message — no restart needed.'})


# ── Profile ────────────────────────────────────────────────────────────────────

@app.route('/api/profile', methods=['GET'])
@limiter.limit("30 per minute")
def get_profile():
    if not PROFILE_FILE.exists():
        return jsonify({})
    try:
        return jsonify(json.loads(PROFILE_FILE.read_text(encoding='utf-8')))
    except Exception:
        return jsonify({})


@app.route('/api/profile', methods=['POST'])
@limiter.limit("10 per minute")
def save_profile():
    if not csrf_valid():
        abort(403)
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        abort(400)
    clean = {}
    for k, v in data.items():
        safe_k = re.sub(r'[^a-zA-Z0-9_]', '_', str(k))[:50]
        if isinstance(v, str):
            clean[safe_k] = sanitize_input(v, 500)
        elif isinstance(v, list):
            clean[safe_k] = [sanitize_input(str(i), 200) for i in v[:20]]
        elif isinstance(v, dict):
            clean[safe_k] = {
                re.sub(r'[^a-zA-Z0-9_]', '_', str(dk))[:50]: sanitize_input(str(dv), 200)
                for dk, dv in list(v.items())[:20]
            }
    PROFILE_FILE.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding='utf-8')
    return jsonify({'status': 'saved'})


@app.route('/api/onboarding/status')
def onboarding_status():
    return jsonify({'complete': PROFILE_FILE.exists()})


# ── Reset Endpoints ────────────────────────────────────────────────────────────

@app.route('/api/reset/onboarding', methods=['POST'])
@limiter.limit("5 per minute")
def reset_onboarding():
    """Delete profile.json so onboarding runs again on next page load."""
    if not csrf_valid():
        abort(403)
    if PROFILE_FILE.exists():
        PROFILE_FILE.unlink()
    logger.info("Onboarding reset")
    return jsonify({'status': 'reset', 'message': 'Onboarding will run on next page load.'})


@app.route('/api/reset/memory', methods=['POST'])
@limiter.limit("10 per minute")
def reset_session_memory():
    """Clear in-process session memory for current user."""
    if not csrf_valid():
        abort(403)
    sess_id = session.get('session_id', '')
    if sess_id:
        memory.clear(sess_id)
    logger.info("Session memory cleared via reset")
    return jsonify({'status': 'cleared', 'message': 'Session memory cleared.'})


@app.route('/api/reset/conversations', methods=['POST'])
@limiter.limit("3 per minute")
def reset_conversations():
    """Delete all saved conversation JSON files."""
    if not csrf_valid():
        abort(403)
    deleted = 0
    for f in CONV_DIR.glob('*.json'):
        try:
            f.unlink()
            deleted += 1
        except Exception:
            pass
    logger.info(f"Reset: deleted {deleted} conversations")
    return jsonify({'status': 'deleted', 'count': deleted, 'message': f'Deleted {deleted} conversations.'})


@app.route('/api/reset/profile', methods=['POST'])
@limiter.limit("5 per minute")
def reset_learned_profile():
    """Wipe only the learned_facts from profile, keep onboarding answers."""
    if not csrf_valid():
        abort(403)
    if PROFILE_FILE.exists():
        try:
            data = json.loads(PROFILE_FILE.read_text(encoding='utf-8'))
            data.pop('learned_facts', None)
            PROFILE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass
    logger.info("Learned profile facts reset")
    return jsonify({'status': 'cleared', 'message': 'Learned facts removed from profile.'})


@app.route('/api/reset/keys', methods=['POST'])
@limiter.limit("3 per minute")
def reset_api_keys():
    """Wipe all API keys from .env (keep SECRET_KEY)."""
    if not csrf_valid():
        abort(403)
    secret = os.getenv('SECRET_KEY', '')
    lines = [f'SECRET_KEY={secret}'] if secret else []
    ENV_PATH.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    logger.info("API keys wiped")
    return jsonify({'status': 'wiped', 'message': 'All API keys removed.'})


@app.route('/api/reset/factory', methods=['POST'])
@limiter.limit("2 per minute")
def factory_reset():
    """Full factory reset — wipe profile, conversations, keys, memory."""
    if not csrf_valid():
        abort(403)

    # Delete profile
    if PROFILE_FILE.exists():
        PROFILE_FILE.unlink()

    # Delete all conversations
    deleted_convs = 0
    for f in CONV_DIR.glob('*.json'):
        try:
            f.unlink()
            deleted_convs += 1
        except Exception:
            pass

    # Wipe API keys (preserve SECRET_KEY)
    secret = os.getenv('SECRET_KEY', '')
    lines = [f'SECRET_KEY={secret}'] if secret else []
    ENV_PATH.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    # Clear session memory
    sess_id = session.get('session_id', '')
    if sess_id:
        memory.clear(sess_id)

    # Clear ChromaDB if available
    try:
        if _chroma_collection:
            _chroma_collection.delete(where={'role': {'$in': ['user', 'assistant']}})
    except Exception:
        pass

    logger.info("Factory reset completed")
    return jsonify({
        'status':  'reset',
        'message': f'Factory reset complete. Deleted {deleted_convs} conversations, profile, and all keys.',
        'reload':  True
    })



SKILL_CATEGORIES = ['writing', 'coding', 'research', 'analysis', 'creative', 'productivity', 'custom']

def parse_skill_metadata(content: str) -> dict:
    """
    Extract metadata from skill .md frontmatter or first heading.
    Supports:
      # Skill: Name
      Category: writing
      Description: One-line summary
    """
    meta = {'category': 'custom', 'description': '', 'author': 'local', 'version': '1.0'}
    lines = content.split('\n')[:15]  # Only scan first 15 lines
    for line in lines:
        line = line.strip()
        if line.lower().startswith('category:'):
            cat = line.split(':', 1)[1].strip().lower()
            if cat in SKILL_CATEGORIES:
                meta['category'] = cat
        elif line.lower().startswith('description:'):
            meta['description'] = sanitize_input(line.split(':', 1)[1].strip(), 200)
        elif line.lower().startswith('author:'):
            meta['author'] = sanitize_input(line.split(':', 1)[1].strip(), 50)
        elif line.lower().startswith('version:'):
            meta['version'] = sanitize_input(line.split(':', 1)[1].strip(), 10)
    return meta


@app.route('/api/skills', methods=['GET'])
@limiter.limit("60 per minute")
def list_skills():
    skills = []
    category_filter = request.args.get('category', '').lower()
    for f in sorted(SKILLS_DIR.glob('*.md')):
        try:
            content = f.read_text(encoding='utf-8')
            meta = parse_skill_metadata(content)
            if category_filter and meta['category'] != category_filter:
                continue
            skills.append({
                'name':        f.stem,
                'filename':    f.name,
                'preview':     sanitize_input(content[:300], 200),
                'category':    meta['category'],
                'description': meta['description'],
                'author':      meta['author'],
                'version':     meta['version'],
                'size':        len(content)
            })
        except Exception:
            pass
    return jsonify(skills)


@app.route('/api/skills/<skill_name>', methods=['GET'])
@limiter.limit("30 per minute")
def get_skill(skill_name):
    """Get full skill content for editing."""
    safe = sanitize_filename(skill_name)
    p = SKILLS_DIR / safe
    if not p.exists():
        abort(404)
    content = p.read_text(encoding='utf-8')
    meta = parse_skill_metadata(content)
    return jsonify({'name': p.stem, 'filename': p.name, 'content': content, **meta})


@app.route('/api/skills/<skill_name>', methods=['PUT'])
@limiter.limit("10 per minute")
def update_skill(skill_name):
    """Create or update a skill file from the in-app editor."""
    if not csrf_valid():
        abort(403)
    data = request.get_json(silent=True)
    if not data:
        abort(400)
    safe = sanitize_filename(skill_name)
    content = data.get('content', '')
    if not isinstance(content, str) or not content.strip():
        return jsonify({'error': 'Content cannot be empty'}), 400
    if len(content) > 50 * 1024:
        return jsonify({'error': 'Skill file too large (max 50KB)'}), 400
    (SKILLS_DIR / safe).write_text(content[:50*1024], encoding='utf-8')
    logger.info(f"Skill updated: {safe}")
    return jsonify({'status': 'saved', 'filename': safe})


@app.route('/api/skills/<skill_name>', methods=['DELETE'])
@limiter.limit("10 per minute")
def delete_skill(skill_name):
    if not csrf_valid():
        abort(403)
    safe = sanitize_filename(skill_name)
    p = SKILLS_DIR / safe
    if p.exists():
        p.unlink()
    return jsonify({'status': 'deleted'})


@app.route('/api/skills/upload', methods=['POST'])
@limiter.limit("10 per minute")
def upload_skill():
    if not csrf_valid():
        abort(403)
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    f = request.files['file']
    if not f.filename or not f.filename.lower().endswith('.md'):
        return jsonify({'error': 'Only .md files allowed'}), 400
    safe_name = sanitize_filename(f.filename)
    raw = f.read(50 * 1024)
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return jsonify({'error': 'File must be UTF-8 text'}), 400
    (SKILLS_DIR / safe_name).write_text(text, encoding='utf-8')
    return jsonify({'status': 'uploaded', 'filename': safe_name})


@app.route('/api/skills/categories', methods=['GET'])
def get_skill_categories():
    """Return available skill categories with counts."""
    counts = {cat: 0 for cat in SKILL_CATEGORIES}
    for f in SKILLS_DIR.glob('*.md'):
        try:
            content = f.read_text(encoding='utf-8')
            meta = parse_skill_metadata(content)
            cat = meta.get('category', 'custom')
            if cat in counts:
                counts[cat] += 1
            else:
                counts['custom'] += 1
        except Exception:
            pass
    return jsonify({'categories': SKILL_CATEGORIES, 'counts': counts})


# ── Phase 5: ChromaDB + RAG Memory ────────────────────────────────────────────
# Semantic memory search across conversations using vector embeddings.
# Uses ChromaDB with local sentence-transformers (no API calls needed).
# Falls back gracefully if ChromaDB not installed.

import hashlib

CHROMA_AVAILABLE = False
_chroma_client = None
_chroma_collection = None

def _init_chroma():
    """
    Initialize ChromaDB with local sentence-transformers embeddings.
    Uses all-MiniLM-L6-v2 — small (80MB), fast, runs entirely offline.
    Falls back silently if packages not installed.
    """
    global CHROMA_AVAILABLE, _chroma_client, _chroma_collection
    if _chroma_client is not None:
        return CHROMA_AVAILABLE
    try:
        import chromadb
        from chromadb.config import Settings
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

        # Use local model — no API calls, no internet needed after first download
        embedding_fn = SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )

        memory_dir = BASE_DIR / 'memory' / 'chroma'
        memory_dir.mkdir(parents=True, exist_ok=True)

        _chroma_client = chromadb.PersistentClient(
            path=str(memory_dir),
            settings=Settings(anonymized_telemetry=False)
        )

        # Handle conflict: collection may exist from a previous run without
        # an embedding function. Try to get it first; if it conflicts, delete
        # and recreate cleanly.
        try:
            _chroma_collection = _chroma_client.get_or_create_collection(
                name='neuconx_memory',
                embedding_function=embedding_fn,
                metadata={'hnsw:space': 'cosine'}
            )
        except ValueError as ve:
            if 'embedding function already exists' in str(ve).lower() or \
               'already exists' in str(ve).lower():
                logger.info("ChromaDB: embedding function conflict — rebuilding collection")
                # Delete old collection and recreate with correct embedding function
                _chroma_client.delete_collection('neuconx_memory')
                _chroma_collection = _chroma_client.create_collection(
                    name='neuconx_memory',
                    embedding_function=embedding_fn,
                    metadata={'hnsw:space': 'cosine'}
                )
                logger.info("ChromaDB: collection rebuilt cleanly — re-index via /api/memory/index")
            else:
                raise

        CHROMA_AVAILABLE = True
        count = _chroma_collection.count()
        logger.info(f"ChromaDB ready — {count} embeddings — semantic memory active")
    except ImportError:
        logger.info("ChromaDB not installed — run: pip install chromadb sentence-transformers --break-system-packages")
    except Exception as e:
        logger.warning(f"ChromaDB init failed: {type(e).__name__}: {str(e)[:120]}")
    return CHROMA_AVAILABLE


def embed_message(role: str, content: str, conv_id: str, timestamp: str):
    """
    Store a message embedding in ChromaDB for semantic retrieval.
    Called after each chat exchange.
    SECURITY: Only stores text content, no PII beyond what user typed.
    """
    if not _init_chroma():
        return
    try:
        doc_id = hashlib.sha256(f"{conv_id}:{timestamp}:{content[:50]}".encode()).hexdigest()[:32]
        _chroma_collection.upsert(
            ids=[doc_id],
            documents=[content[:2000]],
            metadatas=[{
                'role':    role,
                'conv_id': conv_id,
                'ts':      timestamp
            }]
        )
    except Exception as e:
        logger.debug(f"Embed error: {type(e).__name__}")


def semantic_search(query: str, n_results: int = 5) -> list:
    """
    Search conversation history semantically.
    Returns list of relevant passages with metadata.
    """
    if not _init_chroma():
        return []
    try:
        results = _chroma_collection.query(
            query_texts=[query[:500]],
            n_results=min(n_results, 10),
            include=['documents', 'metadatas', 'distances']
        )
        out = []
        docs      = results.get('documents', [[]])[0]
        metas     = results.get('metadatas', [[]])[0]
        distances = results.get('distances', [[]])[0]
        for doc, meta, dist in zip(docs, metas, distances):
            relevance = round(1 - dist, 3)  # cosine similarity
            if relevance > 0.3:  # Only return meaningfully similar results
                out.append({
                    'content':   sanitize_input(doc, 500),
                    'role':      meta.get('role', 'unknown'),
                    'conv_id':   meta.get('conv_id', ''),
                    'timestamp': meta.get('ts', ''),
                    'relevance': relevance
                })
        return sorted(out, key=lambda x: x['relevance'], reverse=True)
    except Exception as e:
        logger.debug(f"Semantic search error: {type(e).__name__}")
        return []


def embed_conversation(conv_data: dict):
    """Embed all messages from a saved conversation into ChromaDB."""
    conv_id = conv_data.get('id', 'unknown')
    for msg in conv_data.get('messages', []):
        content   = msg.get('content', '')
        role      = msg.get('role', 'user')
        timestamp = msg.get('timestamp', datetime.now().isoformat())
        if content and len(content) > 20:  # Skip trivially short messages
            embed_message(role, content, conv_id, timestamp)


@app.route('/api/memory/search', methods=['POST'])
@limiter.limit("20 per minute")
def memory_search():
    """
    Phase 5: Semantic search across all conversation history.
    Returns relevant passages ranked by similarity.
    """
    if not csrf_valid():
        abort(403)
    data = request.get_json(silent=True)
    if not data:
        abort(400)
    query = sanitize_input(data.get('query', ''), 500)
    if not query:
        return jsonify({'error': 'Query required'}), 400
    n = min(int(data.get('n', 5)), 10)
    results = semantic_search(query, n)
    return jsonify({
        'results':   results,
        'count':     len(results),
        'rag_active': CHROMA_AVAILABLE
    })


@app.route('/api/memory/status', methods=['GET'])
@limiter.limit("30 per minute")
def memory_status():
    """Return RAG/ChromaDB status."""
    available = _init_chroma()
    count = 0
    if available and _chroma_collection:
        try:
            count = _chroma_collection.count()
        except Exception:
            pass
    return jsonify({
        'rag_available':   available,
        'embeddings_count': count,
        'session_messages': len(memory.get(session.get('session_id', '')))
    })


@app.route('/api/memory/index', methods=['POST'])
@limiter.limit("5 per minute")
def index_all_conversations():
    """
    Phase 5: Re-index all saved conversations into ChromaDB.
    Call this once after enabling ChromaDB to backfill history.
    """
    if not csrf_valid():
        abort(403)
    if not _init_chroma():
        return jsonify({'error': 'ChromaDB not available. Install: pip install chromadb sentence-transformers'}), 503
    indexed = 0
    for f in CONV_DIR.glob('*.json'):
        try:
            conv = json.loads(f.read_text(encoding='utf-8'))
            embed_conversation(conv)
            indexed += 1
        except Exception:
            pass
    return jsonify({'status': 'indexed', 'conversations': indexed})


# ── Phase 6: Memory Confirmation + Profile Auto-Update ─────────────────────────

class MemoryCandidate:
    """
    Phase 6: Tracks AI-extracted memory candidates awaiting user confirmation.
    Memory candidates are facts/preferences extracted from conversation.
    Thread-safe, in-process only.
    """
    def __init__(self):
        self._pending: dict[str, list] = {}   # session_id → [candidates]
        self._confirmed: dict[str, list] = {} # session_id → [confirmed facts]
        self._lock = threading.Lock()

    def add_candidate(self, sess_id: str, fact: str, source: str):
        with self._lock:
            if sess_id not in self._pending:
                self._pending[sess_id] = []
            # Avoid duplicates
            existing = [c['fact'] for c in self._pending[sess_id]]
            if fact not in existing and len(self._pending[sess_id]) < 20:
                self._pending[sess_id].append({
                    'fact':      sanitize_input(fact, 200),
                    'source':    sanitize_input(source, 100),
                    'timestamp': datetime.now().isoformat(),
                    'id':        uuid.uuid4().hex[:8]
                })

    def get_pending(self, sess_id: str) -> list:
        with self._lock:
            return list(self._pending.get(sess_id, []))

    def confirm(self, sess_id: str, candidate_id: str) -> bool:
        with self._lock:
            pending = self._pending.get(sess_id, [])
            for i, c in enumerate(pending):
                if c['id'] == candidate_id:
                    confirmed = self._confirmed.setdefault(sess_id, [])
                    confirmed.append(c)
                    pending.pop(i)
                    return True
        return False

    def reject(self, sess_id: str, candidate_id: str) -> bool:
        with self._lock:
            pending = self._pending.get(sess_id, [])
            for i, c in enumerate(pending):
                if c['id'] == candidate_id:
                    pending.pop(i)
                    return True
        return False

    def get_confirmed(self, sess_id: str) -> list:
        with self._lock:
            return list(self._confirmed.get(sess_id, []))

    def clear_pending(self, sess_id: str):
        with self._lock:
            self._pending.pop(sess_id, None)


memory_candidates = MemoryCandidate()


def extract_memory_candidates(user_msg: str, ai_response: str, sess_id: str):
    """
    Phase 6: Extract memorable facts from a conversation turn.
    Uses simple heuristics (no API call needed) to detect facts worth remembering.
    """
    # Personal facts patterns
    patterns = [
        (r"\bI(?:\s+am|'m)\s+(?:a|an)?\s*([\w\s]{3,40}?)(?:\.|,|$)", "profession/identity"),
        (r"\bI\s+(?:live|work|study)\s+(?:in|at)\s+([\w\s,]{3,40}?)(?:\.|,|$)", "location"),
        (r"\bI\s+(?:love|hate|prefer|like|enjoy)\s+([\w\s]{3,40}?)(?:\.|,|$)", "preference"),
        (r"\bmy\s+(?:name|company|project|goal|team)\s+is\s+([\w\s]{3,40}?)(?:\.|,|$)", "identity"),
        (r"\bI\s+(?:am|was)\s+(?:born|based)\s+in\s+([\w\s]{3,40}?)(?:\.|,|$)", "origin"),
        (r"\bI\s+have\s+(?:a|an)?\s*([\w\s]{3,40}?)\s+(?:degree|background|experience)", "background"),
    ]
    for pattern, category in patterns:
        matches = re.findall(pattern, user_msg, re.IGNORECASE)
        for match in matches[:2]:
            fact = match.strip()
            if 5 < len(fact) < 80 and fact.lower() not in ['the', 'a', 'an', 'it', 'this', 'that']:
                memory_candidates.add_candidate(
                    sess_id,
                    f"{category}: {fact}",
                    f"Said: '{user_msg[:60]}...'"
                )


@app.route('/api/memory/candidates', methods=['GET'])
@limiter.limit("30 per minute")
def get_memory_candidates():
    """Return pending memory candidates for this session."""
    sess_id = session.get('session_id', '')
    pending   = memory_candidates.get_pending(sess_id)
    confirmed = memory_candidates.get_confirmed(sess_id)
    return jsonify({'pending': pending, 'confirmed': confirmed})


@app.route('/api/memory/candidates/<candidate_id>/confirm', methods=['POST'])
@limiter.limit("20 per minute")
def confirm_memory_candidate(candidate_id):
    """Confirm a memory candidate — saves it to user profile."""
    if not csrf_valid():
        abort(403)
    sess_id = session.get('session_id', '')
    if not re.match(r'^[a-f0-9]{8}$', candidate_id):
        abort(400)
    success = memory_candidates.confirm(sess_id, candidate_id)
    if success:
        # Optionally auto-save to profile
        confirmed = memory_candidates.get_confirmed(sess_id)
        try:
            profile = {}
            if PROFILE_FILE.exists():
                profile = json.loads(PROFILE_FILE.read_text(encoding='utf-8'))
            facts = profile.get('learned_facts', [])
            for c in confirmed:
                if c['fact'] not in facts:
                    facts.append(c['fact'])
            profile['learned_facts'] = facts[-50:]  # Keep last 50 facts
            PROFILE_FILE.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass
    return jsonify({'status': 'confirmed' if success else 'not_found'})


@app.route('/api/memory/candidates/<candidate_id>/reject', methods=['POST'])
@limiter.limit("20 per minute")
def reject_memory_candidate(candidate_id):
    """Reject a memory candidate — discard it."""
    if not csrf_valid():
        abort(403)
    sess_id = session.get('session_id', '')
    if not re.match(r'^[a-f0-9]{8}$', candidate_id):
        abort(400)
    success = memory_candidates.reject(sess_id, candidate_id)
    return jsonify({'status': 'rejected' if success else 'not_found'})


# ── Phase 7: Profile Auto-Update ──────────────────────────────────────────────

@app.route('/api/profile/learned', methods=['GET'])
@limiter.limit("20 per minute")
def get_learned_profile():
    """Return AI-learned profile facts separate from onboarding answers."""
    if not PROFILE_FILE.exists():
        return jsonify({'learned_facts': [], 'onboarding': {}})
    try:
        data = json.loads(PROFILE_FILE.read_text(encoding='utf-8'))
        return jsonify({
            'learned_facts': data.get('learned_facts', []),
            'onboarding':    {k: v for k, v in data.items() if k != 'learned_facts'}
        })
    except Exception:
        return jsonify({'learned_facts': [], 'onboarding': {}})


@app.route('/api/profile/learned/<int:idx>', methods=['DELETE'])
@limiter.limit("10 per minute")
def delete_learned_fact(idx):
    """Delete a specific learned fact by index."""
    if not csrf_valid():
        abort(403)
    if not PROFILE_FILE.exists():
        abort(404)
    try:
        data = json.loads(PROFILE_FILE.read_text(encoding='utf-8'))
        facts = data.get('learned_facts', [])
        if 0 <= idx < len(facts):
            facts.pop(idx)
            data['learned_facts'] = facts
            PROFILE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        return jsonify({'status': 'deleted', 'remaining': len(facts)})
    except Exception:
        abort(500)

# ── Static pages ──────────────────────────────────────────────────────────────

@app.route('/how_it_works.html')
def how_it_works():
    """
    Serve how_it_works.html — checks multiple locations:
    1. Current working directory (where you ran start.bat from)
    2. Same folder as app.py (BASE_DIR)
    3. Static folder
    """
    filename = 'how_it_works.html'
    search_dirs = [
        Path(os.getcwd()),          # Where start.bat / python was launched from
        BASE_DIR,                   # Same folder as app.py
        BASE_DIR / 'static',        # static/ subfolder
        BASE_DIR.parent,            # One level up
    ]
    for directory in search_dirs:
        candidate = directory / filename
        if candidate.exists():
            logger.info(f"Serving {filename} from {directory}")
            return send_from_directory(str(directory), filename)

    # File not found in any location — show helpful message
    checked = '\n'.join(f'  • {d}/{filename}' for d in search_dirs)
    logger.warning(f"how_it_works.html not found. Searched:\n{checked}")
    return (
        f"<html><body style='background:#080c10;color:#c8d6e5;"
        f"font-family:monospace;padding:40px;line-height:1.8'>"
        f"<h2 style='color:#ff7b00'>⚠ how_it_works.html not found</h2>"
        f"<p>Place <code>how_it_works.html</code> in your <strong>NEUCONX/</strong> "
        f"folder (same folder as <code>app.py</code>), then refresh.</p>"
        f"<p style='color:#4a6478;font-size:12px'>Searched in:<br>"
        f"{'<br>'.join(f'&nbsp;&nbsp;• {d}/{filename}' for d in search_dirs)}</p>"
        f"</body></html>"
    ), 404



# ── Dynamic Model Listing ─────────────────────────────────────────────────────
# Calls each provider's native /v1/models endpoint (OpenAI-compatible)
# to return the live, complete list of available models for configured keys.
# This is exactly how free-claude-code does it — hit /v1/models, parse the
# response, return the full list. No hardcoding.

def _fetch_models_from_url(url: str, api_key: str,
                                  provider: str) -> list[dict]:
    """
    Fetch live model list from any OpenAI-compatible /v1/models endpoint.
    Returns list of {id, provider, label} dicts.
    """
    if not api_key:
        return []
    try:
        r = http_req.get(
            url,
            headers={'Authorization': f'Bearer {api_key}',
                     'Content-Type': 'application/json'},
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
        models = []
        for m in data.get('data', []):
            model_id = m.get('id', '')
            if model_id:
                models.append({
                    'id':       model_id,
                    'provider': provider,
                    'label':    f"{model_id}",
                })
        return sorted(models, key=lambda x: x['id'])
    except Exception as e:
        logger.debug(f"Model listing failed for {provider}: {type(e).__name__}: {str(e)[:80]}")
        return []


def _fetch_gemini_models(api_key: str) -> list[dict]:
    """
    Gemini uses a different REST endpoint for model listing.
    Returns only generative models that support generateContent.
    """
    if not api_key:
        return []
    try:
        r = http_req.get(
            f'https://generativelanguage.googleapis.com/v1beta/models?key={api_key}',
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
        models = []
        for m in data.get('models', []):
            name = m.get('name', '')           # e.g. "models/gemini-2.0-flash"
            model_id = name.replace('models/', '')
            supported = m.get('supportedGenerationMethods', [])
            # Only include models that can actually generate content
            if 'generateContent' in supported and model_id:
                models.append({
                    'id':       model_id,
                    'provider': 'gemini',
                    'label':    model_id,
                })
        return sorted(models, key=lambda x: x['id'])
    except Exception as e:
        logger.debug(f"Gemini model listing failed: {type(e).__name__}: {str(e)[:80]}")
        return []


@app.route('/api/models/available', methods=['GET'])
@limiter.limit("10 per minute")
def get_available_models():
    """
    Return live model lists from all configured providers.
    Calls each provider's /v1/models endpoint with the stored API key.
    Front-end uses this to populate the model pin dropdown dynamically.
    """
    keys = get_keys()
    all_models = []

    # Groq — OpenAI-compatible /v1/models
    if keys.get('groq'):
        models = _fetch_models_from_url(
            'https://api.groq.com/openai/v1/models',
            keys['groq'], 'groq'
        )
        all_models.extend(models)

    # Cerebras — OpenAI-compatible /v1/models
    if keys.get('cerebras'):
        models = _fetch_models_from_url(
            'https://api.cerebras.ai/v1/models',
            keys['cerebras'], 'cerebras'
        )
        all_models.extend(models)

    # NVIDIA NIM — OpenAI-compatible /v1/models
    if keys.get('nvidia'):
        models = _fetch_models_from_url(
            'https://integrate.api.nvidia.com/v1/models',
            keys['nvidia'], 'nvidia'
        )
        all_models.extend(models)

    # OpenRouter — OpenAI-compatible /v1/models (huge list — filter to free/tool-capable)
    if keys.get('openrouter'):
        models = _fetch_models_from_url(
            'https://openrouter.ai/api/v1/models',
            keys['openrouter'], 'openrouter'
        )
        # Apply free filter based on user setting
        app_cfg = load_neuconx_settings()
        if app_cfg.get('free_models_only', True):
            free_models = [m for m in models if m['id'].endswith(':free')]
            all_models.extend(free_models if free_models else models[:30])
        else:
            all_models.extend(models)  # All models including paid

    # Gemini — different endpoint
    if keys.get('gemini'):
        models = _fetch_gemini_models(keys['gemini'])
        all_models.extend(models)

    # Ollama / LM Studio — local or LAN server
    ollama_base  = keys.get('ollama_base_url', '').rstrip('/')
    ollama_model = keys.get('ollama_model', '')
    if ollama_base and ollama_model:
        base_clean = ollama_base.removesuffix('/v1')
        local_models = []
        try:
            r = http_req.get(f'{base_clean}/api/tags', timeout=5)
            if r.ok:
                local_models = [m['name'] for m in r.json().get('models', [])]
        except Exception:
            pass
        if not local_models:
            try:
                r2 = http_req.get(f'{base_clean}/v1/models', timeout=5)
                if r2.ok:
                    local_models = [m['id'] for m in r2.json().get('data', [])]
            except Exception:
                pass
        if ollama_model not in local_models:
            local_models.insert(0, ollama_model)
        for m in local_models:
            all_models.append({'id': m, 'provider': 'ollama', 'label': m})

    return jsonify({
        'models':  all_models,
        'count':   len(all_models),
        'providers': list({m['provider'] for m in all_models})
    })


# ── Feature 1: API Key Validation Endpoint ────────────────────────────────────

@app.route('/api/keys/validate', methods=['POST'])
@limiter.limit("10 per minute")
def validate_api_key():
    """
    Validate a single API key by calling its /models endpoint.
    Returns model count and model list for tooltip display.
    """
    if not csrf_valid():
        abort(403)
    data = request.get_json(silent=True)
    if not data:
        abort(400)

    provider = sanitize_input(str(data.get('provider', '')), 50).lower()
    key      = sanitize_input(str(data.get('key', '')), 500)

    if not key or not provider:
        return jsonify({'valid': False, 'error': 'Provider and key required'}), 400

    models = []
    error  = None

    try:
        if provider == 'groq':
            r = http_req.get('https://api.groq.com/openai/v1/models',
                headers={'Authorization': f'Bearer {key}'}, timeout=8)
            r.raise_for_status()
            models = [m['id'] for m in r.json().get('data', [])]

        elif provider == 'cerebras':
            r = http_req.get('https://api.cerebras.ai/v1/models',
                headers={'Authorization': f'Bearer {key}'}, timeout=8)
            r.raise_for_status()
            models = [m['id'] for m in r.json().get('data', [])]

        elif provider == 'nvidia':
            r = http_req.get('https://integrate.api.nvidia.com/v1/models',
                headers={'Authorization': f'Bearer {key}'}, timeout=8)
            r.raise_for_status()
            models = [m['id'] for m in r.json().get('data', [])]

        elif provider == 'openrouter':
            r = http_req.get('https://openrouter.ai/api/v1/models',
                headers={'Authorization': f'Bearer {key}'}, timeout=8)
            r.raise_for_status()
            all_m = r.json().get('data', [])
            app_cfg = load_neuconx_settings()
            if app_cfg.get('free_models_only', True):
                models = [m['id'] for m in all_m if m.get('id','').endswith(':free')]
                if not models:
                    models = [m['id'] for m in all_m[:20]]
            else:
                models = [m['id'] for m in all_m]

        elif provider == 'gemini':
            r = http_req.get(
                f'https://generativelanguage.googleapis.com/v1beta/models?key={key}',
                timeout=8)
            r.raise_for_status()
            models = [m['name'].replace('models/','') for m in r.json().get('models',[])
                      if 'generateContent' in m.get('supportedGenerationMethods', [])]

        elif provider == 'ollama':
            base = sanitize_input(str(data.get('base_url', 'http://localhost:11434')), 200)
            base_clean = base.rstrip('/').removesuffix('/v1')
            models = []
            try:
                r = http_req.get(f'{base_clean}/api/tags', timeout=5)
                if r.ok:
                    models = [m['name'] for m in r.json().get('models', [])]
            except Exception:
                pass
            if not models:
                try:
                    r2 = http_req.get(f'{base_clean}/v1/models', timeout=5)
                    if r2.ok:
                        models = [m['id'] for m in r2.json().get('data', [])]
                except Exception:
                    pass

        else:
            return jsonify({'valid': False, 'error': f'Unknown provider: {provider}'}), 400

    except Exception as e:
        err_str = str(e)
        if '401' in err_str or 'unauthorized' in err_str.lower():
            error = 'Invalid API key'
        elif '403' in err_str:
            error = 'Access denied'
        elif 'timeout' in err_str.lower() or 'connection' in err_str.lower():
            error = 'Connection failed — check URL or network'
        else:
            error = f'Validation failed: {type(e).__name__}'
        return jsonify({'valid': False, 'error': error, 'models': []}), 200

    return jsonify({
        'valid':       True,
        'count':       len(models),
        'models':      models[:50],   # Cap at 50 for tooltip
        'provider':    provider
    })


# ── Feature 2: Model count for header dots ────────────────────────────────────

@app.route('/api/models/counts', methods=['GET'])
@limiter.limit("5 per minute")
def get_model_counts():
    """Return model counts per provider for header dot tooltips.
    Uses identical filtering as /api/models/available so counts match the dropdown."""
    keys  = get_keys()
    counts = {}
    provider_endpoints = {
        'groq':       ('https://api.groq.com/openai/v1/models',     keys.get('groq','')),
        'cerebras':   ('https://api.cerebras.ai/v1/models',          keys.get('cerebras','')),
        'nvidia':     ('https://integrate.api.nvidia.com/v1/models', keys.get('nvidia','')),
        'gemini':     (None,                                          keys.get('gemini','')),
        'openrouter': ('https://openrouter.ai/api/v1/models',        keys.get('openrouter','')),
    }
    for provider, (url, key) in provider_endpoints.items():
        if not key:
            counts[provider] = 0
            continue
        try:
            if provider == 'gemini':
                models = _fetch_gemini_models(key)
            elif provider == 'openrouter':
                all_models_raw = _fetch_models_from_url(url, key, provider)
                app_cfg = load_neuconx_settings()
                if app_cfg.get('free_models_only', True):
                    models = [m for m in all_models_raw if m['id'].endswith(':free')]
                    if not models:
                        models = all_models_raw[:30]
                else:
                    models = all_models_raw
            else:
                models = _fetch_models_from_url(url, key, provider)
            counts[provider] = len(models)
        except Exception:
            counts[provider] = -1

    # Ollama / LM Studio
    ollama_base  = keys.get('ollama_base_url', '').rstrip('/')
    ollama_model = keys.get('ollama_model', '')
    if ollama_base and ollama_model:
        base_clean = ollama_base.removesuffix('/v1')
        try:
            r = http_req.get(f'{base_clean}/api/tags', timeout=5)
            if r.ok:
                counts['ollama'] = len(r.json().get('models', []))
            else:
                raise ValueError('try v1')
        except Exception:
            try:
                r2 = http_req.get(f'{base_clean}/v1/models', timeout=5)
                counts['ollama'] = len(r2.json().get('data', [])) if r2.ok else 1
            except Exception:
                counts['ollama'] = 1
    else:
        counts['ollama'] = 0

    return jsonify(counts)


# ── Feature 4: Settings persistence (merge engine + judge) ───────────────────

SETTINGS_FILE = BASE_DIR / 'data' / 'neuconx_settings.json'

def load_neuconx_settings() -> dict:
    defaults = {
        'merge_engine_enabled': True,
        'judge_model':          'groq',
        'judge_provider':       'groq',
        'free_models_only':     True,   # default ON — honour the golden rule
    }
    if not SETTINGS_FILE.exists():
        return defaults
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
        return {**defaults, **saved}
    except Exception:
        return defaults


@app.route('/api/neuconx-settings', methods=['GET'])
@limiter.limit("20 per minute")
def get_neuconx_settings():
    return jsonify(load_neuconx_settings())


@app.route('/api/neuconx-settings', methods=['POST'])
@limiter.limit("10 per minute")
def save_neuconx_settings():
    if not csrf_valid():
        abort(403)
    data = request.get_json(silent=True)
    if not data:
        abort(400)
    current = load_neuconx_settings()
    if 'merge_engine_enabled' in data:
        current['merge_engine_enabled'] = bool(data['merge_engine_enabled'])
    if 'judge_model' in data:
        current['judge_model'] = sanitize_input(str(data['judge_model']), 200)
    if 'judge_provider' in data:
        current['judge_provider'] = sanitize_input(str(data['judge_provider']), 50)
    if 'free_models_only' in data:
        current['free_models_only'] = bool(data['free_models_only'])
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(current, indent=2), encoding='utf-8')
    return jsonify({'status': 'saved', **current})


# ── Feature 5: Ollama support ─────────────────────────────────────────────────

def call_ollama(prompt: str, history: list, keys: dict, model_id: str = '') -> dict:
    """
    Call Ollama / LM Studio local server via OpenAI-compatible endpoint.
    No API key needed — just a running local server.
    """
    base_url = keys.get('ollama_base_url', 'http://localhost:11434').rstrip('/')
    # Ensure base_url doesn't already end with /v1
    if base_url.endswith('/v1'):
        base_url = base_url[:-3]
    model = model_id or keys.get('ollama_model', 'llama3.2')

    if not model:
        return {'model': 'ollama', 'response': '',
                'error': 'No model configured — add model name in Settings → Local / LAN Models'}

    try:
        r = http_req.post(
            f'{base_url}/v1/chat/completions',
            headers={'Content-Type': 'application/json'},
            json={
                'model': model,
                'messages': _safe_history(history) + [
                    {'role': 'user', 'content': sanitize_input(prompt, 4000)}
                ]
            },
            timeout=120
        )
        r.raise_for_status()
        content = r.json()['choices'][0]['message']['content']
        return {'model': f'ollama:{model}', 'response': content, 'error': None}
    except Exception as e:
        err = str(e)
        if 'connection' in err.lower() or 'refused' in err.lower():
            return {'model': f'ollama:{model}', 'response': '',
                    'error': 'Cannot connect — check the server URL in Settings → Local / LAN Models'}
        return {'model': f'ollama:{model}', 'response': '',
                'error': f'Local model error: {type(e).__name__}: {err[:120]}'}

# ── Error Handlers ─────────────────────────────────────────────────────────────

@app.errorhandler(400)
def bad_request(e):   return jsonify({'error': 'Bad request'}), 400

@app.errorhandler(403)
def forbidden(e):     return jsonify({'error': 'Forbidden'}), 403

@app.errorhandler(404)
def not_found(e):     return jsonify({'error': 'Not found'}), 404

@app.errorhandler(429)
def rate_limited(e):  return jsonify({'error': 'Too many requests. Slow down.'}), 429

@app.errorhandler(500)
def server_error(e):
    logger.error(f"Internal error: {e}")
    return jsonify({'error': 'Internal server error'}), 500


# ── Launch ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    keys = get_keys()
    configured = [k for k, v in keys.items() if v]
    print("\n╔══════════════════════════════════════════╗")
    print("║         NeuConX  —  Starting...          ║")
    print("╠══════════════════════════════════════════╣")
    print("║  http://localhost:5050                   ║")
    print(f"║  Keys loaded: {', '.join(configured) or 'NONE — open Settings':<26}║")
    print("╚══════════════════════════════════════════╝\n")

    app.run(
        debug=False,
        host='127.0.0.1',
        port=5050,
        threaded=True
    )