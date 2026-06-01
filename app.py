"""
MultiMind — Personal AI Platform
Principal Security Architect Notes:
- All inputs sanitized before processing
- Rate limiting on all endpoints
- Secure HTTP headers on every response
- API keys loaded from .env only, never hardcoded
- File upload restricted to .md extension with name sanitization
- No user data leaves the local machine except AI API calls
- CSRF protection via token validation
- Content Security Policy prevents XSS
"""

import os
import re
import uuid
import json
import html
import logging
import secrets
import hashlib
import threading
from pathlib import Path
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, jsonify,
    session, abort, send_from_directory
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
import bleach

# ── Load environment ──────────────────────────────────────────────────────────
load_dotenv()

# ── Logging (never log sensitive data) ────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('multimind.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ── App Initialization ────────────────────────────────────────────────────────
app = Flask(__name__)

# SECURITY: Strong secret key for session signing — generated fresh each start
# In production, set SECRET_KEY in .env for persistence across restarts
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(32))
app.config['SESSION_COOKIE_HTTPONLY'] = True      # Prevent JS access to session
app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'  # CSRF protection
app.config['SESSION_COOKIE_SECURE'] = False        # Set True when using HTTPS
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024  # 1MB max upload size

# ── Rate Limiting ─────────────────────────────────────────────────────────────
# SECURITY: Prevents DoS and API abuse
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "60 per hour"],
    storage_uri="memory://"
)

# ── Path Definitions ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
SKILLS_DIR = BASE_DIR / 'skills'
DATA_DIR = BASE_DIR / 'data'
CONV_DIR = DATA_DIR / 'conversations'
PROFILE_FILE = DATA_DIR / 'profile.json'

# Ensure directories exist
for d in [SKILLS_DIR, CONV_DIR, DATA_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── API Keys ──────────────────────────────────────────────────────────────────
# SECURITY: All keys from environment only. Never hardcoded.
GEMINI_API_KEY    = os.getenv('GEMINI_API_KEY', '')
NVIDIA_API_KEY    = os.getenv('NVIDIA_API_KEY', '')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')

# ── Security Helpers ──────────────────────────────────────────────────────────

def sanitize_input(text: str, max_length: int = 10000) -> str:
    """
    SECURITY: Sanitize all user input.
    - Strip HTML tags to prevent XSS
    - Enforce max length to prevent payload attacks
    - Remove null bytes
    """
    if not isinstance(text, str):
        return ''
    text = text[:max_length]
    text = text.replace('\x00', '')                         # Remove null bytes
    text = bleach.clean(text, tags=[], strip=True)         # Strip all HTML
    return text.strip()


def sanitize_filename(filename: str) -> str:
    """
    SECURITY: Prevent path traversal attacks in file uploads.
    Only allow alphanumeric, hyphen, underscore. Force .md extension.
    """
    # Strip path separators and dangerous characters
    name = re.sub(r'[^a-zA-Z0-9_\-]', '_', Path(filename).stem)
    name = name[:64]  # Max 64 char filename
    return f"{name}.md"


def validate_csrf(f):
    """
    SECURITY: CSRF token validation decorator for state-changing endpoints.
    Token is generated per session and validated on each POST.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method in ['POST', 'PUT', 'DELETE']:
            token = request.headers.get('X-CSRF-Token') or \
                    request.json.get('csrf_token') if request.is_json else None
            session_token = session.get('csrf_token')
            if not token or not session_token or not secrets.compare_digest(
                str(token), str(session_token)
            ):
                logger.warning(f"CSRF validation failed from {get_remote_address()}")
                abort(403)
        return f(*args, **kwargs)
    return decorated


def add_security_headers(response):
    """
    SECURITY: Add HTTP security headers to every response.
    Prevents XSS, clickjacking, MIME sniffing, and information leakage.
    """
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "   # unsafe-inline needed for inline JS
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "connect-src 'self'; "
        "img-src 'self' data:; "
        "frame-ancestors 'none';"
    )
    # SECURITY: Remove server identification header
    response.headers.pop('Server', None)
    return response


app.after_request(add_security_headers)


# ── Model Callers ─────────────────────────────────────────────────────────────
import requests as http_requests

def call_gemini(prompt: str, history: list) -> dict:
    """Call Gemini 2.0 Flash API."""
    if not GEMINI_API_KEY:
        return {'model': 'gemini', 'response': '', 'error': 'API key not configured'}
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.0-flash')
        # Build safe history (last 10 messages)
        safe_history = []
        for msg in history[-10:]:
            role = 'user' if msg.get('role') == 'user' else 'model'
            content = sanitize_input(msg.get('content', ''), max_length=4000)
            if content:
                safe_history.append({'role': role, 'parts': [content]})
        chat = model.start_chat(history=safe_history[:-1] if safe_history else [])
        response = chat.send_message(sanitize_input(prompt, max_length=4000))
        return {'model': 'gemini', 'response': response.text, 'error': None}
    except Exception as e:
        logger.error(f"Gemini API error: {type(e).__name__}")  # Log type, not full error (may contain keys)
        return {'model': 'gemini', 'response': '', 'error': 'Model unavailable'}


def call_nvidia(prompt: str, history: list) -> dict:
    """Call NVIDIA NIM API (Llama 3.3 70B)."""
    if not NVIDIA_API_KEY:
        return {'model': 'nvidia', 'response': '', 'error': 'API key not configured'}
    try:
        messages = []
        for msg in history[-10:]:
            content = sanitize_input(msg.get('content', ''), max_length=4000)
            if content:
                messages.append({'role': msg.get('role', 'user'), 'content': content})
        messages.append({'role': 'user', 'content': sanitize_input(prompt, max_length=4000)})
        r = http_requests.post(
            'https://integrate.api.nvidia.com/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {NVIDIA_API_KEY}',
                'Content-Type': 'application/json'
            },
            json={
                'model': 'meta/llama-3.3-70b-instruct',
                'messages': messages,
                'max_tokens': 1024,
                'temperature': 0.7
            },
            timeout=30
        )
        r.raise_for_status()
        text = r.json()['choices'][0]['message']['content']
        return {'model': 'nvidia', 'response': text, 'error': None}
    except Exception as e:
        logger.error(f"NVIDIA API error: {type(e).__name__}")
        return {'model': 'nvidia', 'response': '', 'error': 'Model unavailable'}


def call_openrouter(prompt: str, history: list, model_id: str, model_key: str) -> dict:
    """Call OpenRouter API."""
    if not OPENROUTER_API_KEY:
        return {'model': model_key, 'response': '', 'error': 'API key not configured'}
    try:
        messages = []
        for msg in history[-10:]:
            content = sanitize_input(msg.get('content', ''), max_length=4000)
            if content:
                messages.append({'role': msg.get('role', 'user'), 'content': content})
        messages.append({'role': 'user', 'content': sanitize_input(prompt, max_length=4000)})
        r = http_requests.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {OPENROUTER_API_KEY}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'http://localhost:5050',
                'X-Title': 'MultiMind'
            },
            json={'model': model_id, 'messages': messages, 'max_tokens': 1024},
            timeout=30
        )
        r.raise_for_status()
        text = r.json()['choices'][0]['message']['content']
        return {'model': model_key, 'response': text, 'error': None}
    except Exception as e:
        logger.error(f"OpenRouter API error ({model_key}): {type(e).__name__}")
        return {'model': model_key, 'response': '', 'error': 'Model unavailable'}


def merge_responses(prompt: str, responses: list) -> str:
    """
    Merge engine: deduplicate and union all model responses.
    Uses Gemini as merge operator (not judge).
    """
    valid = [r for r in responses if r.get('response') and not r.get('error')]
    if not valid:
        return 'All configured models are currently unavailable. Please check your API keys in Settings.'
    if len(valid) == 1:
        return valid[0]['response']

    merge_prompt = (
        "You are a merge operator. Combine these AI responses into one clean answer.\n"
        "RULES:\n"
        "1. If multiple responses say the same thing, include it ONCE only\n"
        "2. If a response adds a unique point, include it\n"
        "3. Do NOT add your own opinions or new information\n"
        "4. Do NOT mention which model said what\n"
        "5. Output ONLY the final merged answer\n\n"
        f"Original question: {sanitize_input(prompt, 500)}\n\n"
    )
    for i, r in enumerate(valid, 1):
        merge_prompt += f"Response {i}:\n{r['response'][:2000]}\n\n"
    merge_prompt += "Merged answer:"

    result = call_gemini(merge_prompt, [])
    if result.get('response'):
        return result['response']
    return max(valid, key=lambda x: len(x.get('response', '')))['response']


def classify_query(text: str) -> str:
    """
    Smart router: classify query complexity locally.
    No API call needed. Zero token cost.
    """
    words = len(text.split())
    complex_keywords = [
        'analyze', 'compare', 'explain', 'write', 'research',
        'design', 'debug', 'code', 'generate', 'create', 'plan',
        'build', 'implement', 'architecture', 'review', 'evaluate'
    ]
    if words < 10:
        return 'tier1'
    if words > 30 or any(k in text.lower() for k in complex_keywords):
        return 'tier3'
    return 'tier2'


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    """Serve main UI. Generate CSRF token for session."""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    onboarding_complete = PROFILE_FILE.exists()
    return render_template(
        'index.html',
        csrf_token=session['csrf_token'],
        onboarding_complete=onboarding_complete
    )


@app.route('/api/csrf-token')
def get_csrf_token():
    """Return CSRF token for frontend use."""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return jsonify({'token': session['csrf_token']})


@app.route('/api/chat', methods=['POST'])
@limiter.limit("30 per minute")
def chat():
    """
    Main chat endpoint.
    SECURITY: Input sanitized, rate limited, CSRF validated.
    """
    if 'csrf_token' not in session:
        abort(403)
    token = request.headers.get('X-CSRF-Token', '')
    if not secrets.compare_digest(token, session.get('csrf_token', '')):
        abort(403)

    data = request.get_json(silent=True)
    if not data:
        abort(400)

    message = sanitize_input(data.get('message', ''), max_length=8000)
    if not message:
        return jsonify({'error': 'Message cannot be empty'}), 400

    history = data.get('history', [])
    if not isinstance(history, list):
        history = []
    # SECURITY: Limit history depth to prevent payload bloat
    history = history[-20:]

    tier_override = data.get('tier_override', '')
    skills_active = data.get('skills_active', [])
    if not isinstance(skills_active, list):
        skills_active = []

    # Build system context with active skills
    system_context = ''
    for skill_name in skills_active[:5]:  # Max 5 skills at once
        skill_name = sanitize_filename(str(skill_name))
        skill_path = SKILLS_DIR / skill_name
        if skill_path.exists() and skill_path.suffix == '.md':
            try:
                skill_content = skill_path.read_text(encoding='utf-8')[:3000]
                system_context += f"\n\n--- SKILL: {skill_name} ---\n{skill_content}"
            except Exception:
                pass

    enriched_prompt = message
    if system_context:
        enriched_prompt = f"{system_context}\n\n---\n\nUser query: {message}"

    # Determine tier
    tier = tier_override if tier_override in ['tier1', 'tier2', 'tier3'] else classify_query(message)

    results = {}
    threads = []

    def run_model(key):
        if key == 'gemini':
            results[key] = call_gemini(enriched_prompt, history)
        elif key == 'nvidia':
            results[key] = call_nvidia(enriched_prompt, history)
        elif key == 'deepseek':
            results[key] = call_openrouter(enriched_prompt, history, 'deepseek/deepseek-chat', 'deepseek')
        elif key == 'mistral':
            results[key] = call_openrouter(enriched_prompt, history, 'mistralai/mistral-7b-instruct', 'mistral')

    # Route based on tier
    models_to_call = {
        'tier1': ['gemini'],
        'tier2': ['gemini', 'nvidia'],
        'tier3': ['gemini', 'nvidia', 'deepseek', 'mistral']
    }.get(tier, ['gemini'])

    for key in models_to_call:
        t = threading.Thread(target=run_model, args=(key,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=35)

    responses = list(results.values())
    final_answer = merge_responses(message, responses)

    return jsonify({
        'final_answer': final_answer,
        'model_responses': [
            {'model': r['model'], 'response': r.get('response', ''), 'error': r.get('error')}
            for r in responses
        ],
        'tier_used': tier,
        'models_used': len([r for r in responses if r.get('response')])
    })


@app.route('/api/conversations', methods=['GET'])
@limiter.limit("60 per minute")
def list_conversations():
    """List all saved conversations."""
    convs = []
    for f in sorted(CONV_DIR.glob('*.json'), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            convs.append({
                'id': data.get('id', f.stem),
                'title': sanitize_input(data.get('title', 'Untitled'), max_length=100),
                'created_at': data.get('created_at', ''),
                'message_count': len(data.get('messages', []))
            })
        except Exception:
            pass
    return jsonify(convs)


@app.route('/api/conversations/<conv_id>', methods=['GET'])
@limiter.limit("60 per minute")
def get_conversation(conv_id):
    """Load a specific conversation."""
    # SECURITY: Validate conv_id to prevent path traversal
    if not re.match(r'^[a-zA-Z0-9_\-]{1,64}$', conv_id):
        abort(400)
    conv_file = CONV_DIR / f'{conv_id}.json'
    if not conv_file.exists():
        abort(404)
    try:
        data = json.loads(conv_file.read_text(encoding='utf-8'))
        return jsonify(data)
    except Exception:
        abort(500)


@app.route('/api/conversations', methods=['POST'])
@limiter.limit("30 per minute")
def save_conversation():
    """Save or update a conversation."""
    if not secrets.compare_digest(
        request.headers.get('X-CSRF-Token', ''),
        session.get('csrf_token', '')
    ):
        abort(403)

    data = request.get_json(silent=True)
    if not data:
        abort(400)

    conv_id = data.get('id') or f"conv_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    # SECURITY: Validate ID format
    if not re.match(r'^[a-zA-Z0-9_\-]{1,64}$', conv_id):
        abort(400)

    # Sanitize title
    title = sanitize_input(data.get('title', 'New Conversation'), max_length=100)
    if not title:
        title = 'New Conversation'

    # Sanitize messages
    messages = []
    for msg in data.get('messages', [])[-200:]:  # Max 200 messages per conversation
        if isinstance(msg, dict):
            messages.append({
                'role': 'user' if msg.get('role') == 'user' else 'assistant',
                'content': sanitize_input(str(msg.get('content', '')), max_length=8000),
                'timestamp': msg.get('timestamp', datetime.now().isoformat())
            })

    conv_data = {
        'id': conv_id,
        'title': title,
        'created_at': data.get('created_at', datetime.now().isoformat()),
        'updated_at': datetime.now().isoformat(),
        'messages': messages
    }

    conv_file = CONV_DIR / f'{conv_id}.json'
    conv_file.write_text(json.dumps(conv_data, ensure_ascii=False, indent=2), encoding='utf-8')
    return jsonify({'id': conv_id, 'status': 'saved'})


@app.route('/api/conversations/<conv_id>', methods=['DELETE'])
@limiter.limit("20 per minute")
def delete_conversation(conv_id):
    """Delete a conversation."""
    if not secrets.compare_digest(
        request.headers.get('X-CSRF-Token', ''),
        session.get('csrf_token', '')
    ):
        abort(403)
    if not re.match(r'^[a-zA-Z0-9_\-]{1,64}$', conv_id):
        abort(400)
    conv_file = CONV_DIR / f'{conv_id}.json'
    if conv_file.exists():
        conv_file.unlink()
    return jsonify({'status': 'deleted'})


@app.route('/api/skills', methods=['GET'])
@limiter.limit("60 per minute")
def list_skills():
    """List all available skill files."""
    skills = []
    for f in SKILLS_DIR.glob('*.md'):
        try:
            content = f.read_text(encoding='utf-8')[:500]  # Preview only
            skills.append({
                'name': f.stem,
                'filename': f.name,
                'preview': sanitize_input(content, max_length=200)
            })
        except Exception:
            pass
    return jsonify(skills)


@app.route('/api/skills/upload', methods=['POST'])
@limiter.limit("10 per minute")
def upload_skill():
    """
    Upload a new skill .md file.
    SECURITY: Extension whitelist, filename sanitization, content size limit.
    """
    if not secrets.compare_digest(
        request.headers.get('X-CSRF-Token', ''),
        session.get('csrf_token', '')
    ):
        abort(403)

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'No filename'}), 400

    # SECURITY: Only allow .md files
    if not f.filename.lower().endswith('.md'):
        return jsonify({'error': 'Only .md files are allowed'}), 400

    safe_name = sanitize_filename(f.filename)
    content = f.read(50 * 1024)  # Max 50KB skill file

    # SECURITY: Validate content is valid UTF-8 text
    try:
        text_content = content.decode('utf-8')
    except UnicodeDecodeError:
        return jsonify({'error': 'Invalid file encoding. Must be UTF-8 text.'}), 400

    skill_path = SKILLS_DIR / safe_name
    skill_path.write_text(text_content, encoding='utf-8')
    logger.info(f"Skill uploaded: {safe_name}")
    return jsonify({'status': 'uploaded', 'filename': safe_name})


@app.route('/api/settings', methods=['GET'])
@limiter.limit("20 per minute")
def get_settings():
    """Return configuration status. NEVER return actual key values."""
    return jsonify({
        'gemini_configured': bool(GEMINI_API_KEY),
        'nvidia_configured': bool(NVIDIA_API_KEY),
        'openrouter_configured': bool(OPENROUTER_API_KEY),
        # SECURITY: Only show masked hint, never full key
        'gemini_hint': f"...{GEMINI_API_KEY[-4:]}" if GEMINI_API_KEY else None,
        'nvidia_hint': f"...{NVIDIA_API_KEY[-4:]}" if NVIDIA_API_KEY else None,
        'openrouter_hint': f"...{OPENROUTER_API_KEY[-4:]}" if OPENROUTER_API_KEY else None,
    })


@app.route('/api/settings', methods=['POST'])
@limiter.limit("5 per minute")
def save_settings():
    """
    Save API keys to .env file.
    SECURITY: Keys validated for basic format, written to local file only.
    """
    if not secrets.compare_digest(
        request.headers.get('X-CSRF-Token', ''),
        session.get('csrf_token', '')
    ):
        abort(403)

    data = request.get_json(silent=True)
    if not data:
        abort(400)

    env_path = BASE_DIR / '.env'
    lines = []

    # SECURITY: Basic API key format validation (alphanumeric + common chars)
    key_pattern = re.compile(r'^[a-zA-Z0-9_\-\.]{10,200}$')

    for env_var, field in [
        ('GEMINI_API_KEY', 'gemini_key'),
        ('NVIDIA_API_KEY', 'nvidia_key'),
        ('OPENROUTER_API_KEY', 'openrouter_key')
    ]:
        val = data.get(field, '').strip()
        if val:
            if not key_pattern.match(val):
                return jsonify({'error': f'Invalid format for {field}'}), 400
            lines.append(f'{env_var}={val}')

    # Preserve SECRET_KEY if already set
    existing_secret = os.getenv('SECRET_KEY', '')
    if existing_secret:
        lines.append(f'SECRET_KEY={existing_secret}')

    env_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    logger.info("Settings saved (keys updated)")
    return jsonify({'status': 'saved', 'message': 'Restart the app to apply new keys.'})


@app.route('/api/profile', methods=['GET'])
@limiter.limit("30 per minute")
def get_profile():
    """Return user profile."""
    if not PROFILE_FILE.exists():
        return jsonify({})
    try:
        data = json.loads(PROFILE_FILE.read_text(encoding='utf-8'))
        return jsonify(data)
    except Exception:
        return jsonify({})


@app.route('/api/profile', methods=['POST'])
@limiter.limit("10 per minute")
def save_profile():
    """Save user profile from onboarding."""
    if not secrets.compare_digest(
        request.headers.get('X-CSRF-Token', ''),
        session.get('csrf_token', '')
    ):
        abort(403)

    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        abort(400)

    # SECURITY: Sanitize all profile fields
    clean = {}
    for key, val in data.items():
        safe_key = re.sub(r'[^a-zA-Z0-9_]', '_', str(key))[:50]
        if isinstance(val, str):
            clean[safe_key] = sanitize_input(val, max_length=500)
        elif isinstance(val, list):
            clean[safe_key] = [sanitize_input(str(v), 200) for v in val[:20]]
        elif isinstance(val, dict):
            clean[safe_key] = {
                re.sub(r'[^a-zA-Z0-9_]', '_', str(k))[:50]: sanitize_input(str(v), 200)
                for k, v in list(val.items())[:20]
            }

    PROFILE_FILE.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding='utf-8')
    return jsonify({'status': 'saved'})


@app.route('/api/onboarding/status')
def onboarding_status():
    """Check if onboarding is complete."""
    return jsonify({'complete': PROFILE_FILE.exists()})


# ── Error Handlers ─────────────────────────────────────────────────────────────
@app.errorhandler(400)
def bad_request(e):
    return jsonify({'error': 'Bad request'}), 400

@app.errorhandler(403)
def forbidden(e):
    return jsonify({'error': 'Forbidden'}), 403

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(429)
def rate_limited(e):
    return jsonify({'error': 'Too many requests. Please slow down.'}), 429

@app.errorhandler(500)
def server_error(e):
    # SECURITY: Never expose internal error details to client
    logger.error(f"Internal error: {e}")
    return jsonify({'error': 'Internal server error'}), 500


# ── Launch ────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("\n╔══════════════════════════════════════╗")
    print("║         MultiMind is starting...     ║")
    print("╠══════════════════════════════════════╣")
    print("║  http://localhost:5050               ║")
    print("╚══════════════════════════════════════╝\n")

    # SECURITY: Debug mode OFF in production
    # Debug=True exposes interactive debugger — dangerous in production
    app.run(
        debug=False,
        host='127.0.0.1',   # SECURITY: Bind to localhost only, not 0.0.0.0
        port=5050,
        threaded=True
    )
