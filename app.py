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

from flask import Flask, render_template, request, jsonify, session, abort
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
    This fixes the 'save keys → must restart' UX problem.
    """
    env = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    return {
        'gemini':      env.get('GEMINI_API_KEY', '')      or os.getenv('GEMINI_API_KEY', ''),
        'nvidia':      env.get('NVIDIA_API_KEY', '')      or os.getenv('NVIDIA_API_KEY', ''),
        'openrouter':  env.get('OPENROUTER_API_KEY', '')  or os.getenv('OPENROUTER_API_KEY', ''),
        'groq':        env.get('GROQ_API_KEY', '')        or os.getenv('GROQ_API_KEY', ''),
        'cerebras':    env.get('CEREBRAS_API_KEY', '')    or os.getenv('CEREBRAS_API_KEY', ''),
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
    """Return sanitized history slice."""
    out = []
    for msg in history[-limit:]:
        if not isinstance(msg, dict):
            continue
        content = sanitize_input(str(msg.get('content', '')), max_length=3000)
        role    = 'user' if msg.get('role') == 'user' else 'assistant'
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


def call_groq(prompt: str, history: list, keys: dict) -> dict:
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


def call_cerebras(prompt: str, history: list, keys: dict) -> dict:
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

def estimate_max_tokens(prompt: str) -> int:
    """
    Dynamically set max_tokens based on what the user is asking for.
    Conservative limits to avoid rate limiting on free tiers.

    Groq free: ~6000 tokens/min total (input+output combined)
    Cerebras free: 60 req/min
    So we keep output tokens reasonable to stay within limits.
    """
    lower = prompt.lower()
    words = lower.split()

    # Very explicit long-form: full HTML pages, complete essays, full code files
    explicit_long = {'html', 'css', 'full', 'complete', 'entire', 'whole', 'all'}
    if any(k in lower for k in explicit_long) and len(words) > 10:
        return 4096  # Was 8192 — too high, causes rate limits

    # Code / technical content
    code_keywords = {'code', 'script', 'function', 'class', 'implement', 'write', 'build', 'create', 'generate'}
    if any(k in lower for k in code_keywords):
        return 2048

    # Long prompts
    if len(words) > 50:
        return 2048

    # Short conversational
    if len(words) <= 15:
        return 1024

    return 1536  # Default — was 2048, slightly lower to reduce rate limit hits


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
    with _exhausted_lock:
        return model in _exhausted_models


def build_model_list(tier: str, keys: dict) -> list:
    """
    Build model list based on tier + available keys + quota status.

    FIX: Priority order is now Groq → Cerebras → Gemini → NVIDIA → DeepSeek → Mistral.
    Groq and Cerebras are fastest, most generous free tier, and don't exhaust daily.
    Gemini is deprioritised because it has a 1500/day hard cap.

    Quota-exhausted models are skipped automatically for the rest of the session.
    This means after Gemini hits its cap, Groq/Cerebras serve all traffic seamlessly.
    """
    # Priority order: fastest/most-reliable free first
    # Groq and Cerebras before Gemini intentionally — saves Gemini quota for merge ops
    available = []
    if keys.get('groq')      and not is_exhausted('groq'):      available.append('groq')
    if keys.get('cerebras')  and not is_exhausted('cerebras'):  available.append('cerebras')
    if keys.get('gemini')    and not is_exhausted('gemini'):    available.append('gemini')
    if keys.get('nvidia')    and not is_exhausted('nvidia'):    available.append('nvidia')
    if keys.get('openrouter') and not is_exhausted('deepseek'): available.append('deepseek')
    if keys.get('openrouter') and not is_exhausted('mistral'):  available.append('mistral')

    if not available:
        # All preferred models exhausted — try exhausted ones as last resort
        # (quota may have reset since we marked them)
        fallback = []
        if keys.get('groq'):      fallback.append('groq')
        if keys.get('cerebras'):  fallback.append('cerebras')
        if keys.get('gemini'):    fallback.append('gemini')
        if keys.get('nvidia'):    fallback.append('nvidia')
        if keys.get('openrouter'):
            fallback.append('deepseek')
            fallback.append('mistral')
        return fallback[:1]  # last resort: try any one model

    # Tier limits
    limits = {'tier1': 1, 'tier2': 2, 'tier3': len(available)}
    limit  = limits.get(tier, 1)

    return available[:limit]


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

    # Build model list based on tier + available keys
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

    # 1. User profile — always injected so responses are personalised
    if PROFILE_FILE.exists():
        try:
            profile = json.loads(PROFILE_FILE.read_text(encoding='utf-8'))
            # Build a compact profile summary (not the full JSON blob)
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
            # Include learned facts too
            facts = profile.get('learned_facts', [])
            if facts:
                profile_lines.append(f"- Known facts: {'; '.join(facts[:10])}")

            if profile_lines:
                system_parts.append(
                    "ABOUT THE USER (use this to personalise your response):\n" + "\n".join(profile_lines)
                )
        except Exception:
            pass

    # 2. Active skills
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

    # 3. Relevant semantic memory (if ChromaDB available)
    if CHROMA_AVAILABLE or _init_chroma():
        try:
            mem_results = semantic_search(message, n_results=3)
            if mem_results:
                mem_snippets = []
                for r in mem_results:
                    if r['relevance'] > 0.55:  # Only high-relevance memory
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
                return call_groq(enriched, history, keys)
            elif model_key == 'cerebras':
                return call_cerebras(enriched, history, keys)
            return {'model': model_key, 'response': '', 'error': 'Unknown model'}

        r = _call()

        # Auto-retry once on transient errors (timeout, connection reset, 503)
        if r.get('error') and any(x in (r.get('error') or '') for x in ['timed out', 'timeout', 'temporarily down', 'retry']):
            logger.info(f"Retrying {model_key} after transient error: {r.get('error')}")
            time.sleep(1)
            r = _call()

        # Track usage
        if not (r.get('error') == 'No API key'):
            usage_tracker.record(model_key)
        with lock:
            results[model_key] = r

    threads = [threading.Thread(target=run, args=(m,)) for m in models_to_call]
    for t in threads: t.start()
    for t in threads: t.join(timeout=35)

    responses = list(results.values())
    final    = merge_responses(message, responses, keys)

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
        'models_called': models_to_call
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
            messages.append({
                'role':      'user' if msg.get('role') == 'user' else 'assistant',
                'content':   sanitize_input(str(msg.get('content', '')), 8000),
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
    return jsonify({
        **{f'{k}_configured': v for k, v in configured.items()},
        **{f'{k}_hint':       v for k, v in hints.items()},
        'any_configured': any(configured.values()),
        'exhausted_models': exhausted_list  # frontend uses this to dim model dots
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
            model_name="all-MiniLM-L6-v2"  # 80MB, fast, good quality
        )

        memory_dir = BASE_DIR / 'memory' / 'chroma'
        memory_dir.mkdir(parents=True, exist_ok=True)

        _chroma_client = chromadb.PersistentClient(
            path=str(memory_dir),
            settings=Settings(anonymized_telemetry=False)  # SECURITY: no telemetry
        )
        _chroma_collection = _chroma_client.get_or_create_collection(
            name='neuconx_memory',
            embedding_function=embedding_fn,   # ← THIS was missing
            metadata={'hnsw:space': 'cosine'}
        )
        CHROMA_AVAILABLE = True
        count = _chroma_collection.count()
        logger.info(f"ChromaDB ready — {count} embeddings stored — semantic memory active")
    except ImportError:
        logger.info("ChromaDB/sentence-transformers not installed — run: pip install chromadb sentence-transformers --break-system-packages")
    except Exception as e:
        logger.warning(f"ChromaDB init failed: {type(e).__name__}: {str(e)[:100]}")
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