/**
 * NeuConX — Frontend (Phase 2+3)
 *
 * SECURITY:
 * - CSRF token from <meta> tag only (never localStorage)
 * - All user content via textContent (never innerHTML) to block XSS
 * - No eval() / Function() anywhere
 * - Fetch: credentials:'same-origin' only
 *
 * Phase 2: Multi-model status display, tier feedback, model response panel
 * Phase 3: Session memory sync, conversation delete, clear memory
 */

'use strict';

// ── CSRF ──────────────────────────────────────────────────────────────────────
// Token injected by Flask into <meta name="csrf-token"> at page load.
// Safety net: if file is served statically (template not rendered),
// the meta will contain literal "{{ csrf_token }}" — detect and auto-fetch.
let _csrfToken = null;

async function ensureCSRFToken() {
  if (_csrfToken) return _csrfToken;
  const meta = document.querySelector('meta[name="csrf-token"]');
  const raw  = meta?.getAttribute('content') || '';
  if (raw && !raw.includes('{{')) {
    _csrfToken = raw;
    return _csrfToken;
  }
  // Not rendered by Flask — fetch fresh token
  console.warn('NeuConX: CSRF not in meta — fetching from /api/csrf-token');
  try {
    const res  = await fetch('/api/csrf-token', { credentials: 'same-origin' });
    const data = await res.json();
    _csrfToken = data.token || '';
    if (meta) meta.setAttribute('content', _csrfToken);
  } catch (e) {
    console.error('NeuConX: CSRF fetch failed', e);
    _csrfToken = '';
  }
  return _csrfToken;
}

const getCSRFToken = () => _csrfToken || '';

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  currentConvId: null,
  messages:      [],
  selectedTier:  'auto',
  activeSkills:  new Set(),
  isLoading:     false,
  onboardingStep: 0,
  onboardingAnswers: {},
  personalized:  true,
  pinnedModel:   null,   // null = auto routing, {provider,modelId} = force specific model
  pdfTheme:      'professional', // theme for pdf_creator skill-generated files
  abortController: null  // for stop button
};

// Model color map
const MODEL_COLORS = {
  gemini:   '#4285F4',
  nvidia:   '#76B900',
  deepseek: '#00C4FF',
  mistral:  '#FF7000',
  groq:     '#F55036',
  cerebras: '#8B5CF6',
  ollama:   '#00e896'
};

// ── Onboarding steps ──────────────────────────────────────────────────────────
const OB_STEPS = [
  { section: 'Welcome',  question: null },
  { section: 'Identity', question: 'Your full name and what city/country are you based in?' },
  { section: 'Education',question: 'Current education — degrees, programs, or certifications you hold or are pursuing?' },
  { section: 'Career',   question: 'What do you do professionally? Job title, company, years of experience, main tech stack?' },
  { section: 'Goals',    question: 'Top 3 goals you are actively working toward right now (personal or professional)?' },
  { section: 'Style',    question: 'How do you prefer responses — detailed or concise? Formal or casual? Any other preferences?' },
  { section: 'Projects', question: 'Current projects you are working on — side projects, startups, ongoing work?' }
];

// ── Secure fetch ──────────────────────────────────────────────────────────────
async function secureFetch(url, opts = {}) {
  // Always ensure token is ready — handles first load and static-file edge case
  await ensureCSRFToken();
  const res = await fetch(url, {
    credentials: 'same-origin',
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': getCSRFToken(),
      ...(opts.headers || {})
    }
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    throw new Error(e.error || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── DOM helpers (XSS-safe) ────────────────────────────────────────────────────
const setText = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  // Configure markdown renderer
  setupMarked();
  // MUST run first — all secureFetch calls need a valid CSRF token
  await ensureCSRFToken();
  await Promise.all([loadSettings(), loadConversations(), loadSkills(), fetchUsage()]);
  setupStarters();
  // Phase 5: Check RAG status
  await checkRAGStatus();
  // Fetch model counts for header dot tooltips (slightly delayed to not block startup)
  setTimeout(fetchModelCounts, 2000);
});

// ── Starter chips ─────────────────────────────────────────────────────────────
function setupStarters() {
  document.querySelectorAll('.chip[data-prompt]').forEach(chip => {
    chip.addEventListener('click', () => {
      document.getElementById('chat-input').value = chip.dataset.prompt;
      sendMessage();
    });
  });
}

// ── Settings & model status ───────────────────────────────────────────────────
async function loadSettings() {
  try {
    const data = await secureFetch('/api/settings');
    const models = ['gemini', 'nvidia', 'openrouter', 'groq', 'cerebras'];

    // Update status badges in settings modal
    models.forEach(m => {
      const el = document.getElementById(`${m}-status`);
      if (!el) return;
      if (data[`${m}_configured`]) {
        el.textContent = `✓ ${data[`${m}_hint`] || 'configured'}`;
        el.className = 'key-status configured';
      } else {
        el.textContent = '✗ not set';
        el.className = 'key-status missing';
      }
    });

    // Model status dots in header
    updateModelStatusBar(data);

    // Populate model pin dropdown with configured models
    populateModelPinDropdown(data);

    // No-keys warning on welcome screen
    const warn = document.getElementById('no-keys-warning');
    if (warn) warn.classList.toggle('hidden', data.any_configured);

    // Models display in input meta
    const active = models.filter(m => data[`${m}_configured`]);
    setText('models-display', active.length ? `${active.join(' · ')} ready` : 'No models — open Settings');

  } catch (e) {
    console.error('Settings load failed:', e.message);
  }
}

// ── Model quota info (fetched once, updated after each chat) ─────────────────
// Structure: { gemini: { used: 47, limit: 1500, resetIn: '14h' }, ... }
let _usageData = {};

async function fetchUsage() {
  try {
    const data = await secureFetch('/api/usage');
    _usageData = data || {};
  } catch (e) {
    // Non-fatal — tooltips just show less detail
  }
}

// Cache of provider → model count, populated by fetchModelCounts()
let _modelCounts = {};

async function fetchModelCounts() {
  try {
    const counts = await secureFetch('/api/models/counts');
    _modelCounts = counts;
    // Re-render dots if settings data is cached
    if (_lastSettingsData) updateModelStatusBar(_lastSettingsData);
  } catch(e) {}
}

// Cache last settings data so we can re-render dots after counts arrive
let _lastSettingsData = null;

function updateModelStatusBar(data) {
  _lastSettingsData = data;  // cache for re-render
  const bar = document.getElementById('model-status-bar');
  if (!bar) return;
  bar.innerHTML = '';

  const exhausted = data.exhausted_models || [];

  const MODELS = [
    { key: 'gemini',     name: 'Gemini 2.0 Flash',  limit: 1500,  resetLabel: 'Daily',   unit: 'req/day'  },
    { key: 'groq',       name: 'Groq Llama 3.3 70B', limit: 14400, resetLabel: 'Daily',   unit: 'req/day'  },
    { key: 'cerebras',   name: 'Cerebras Llama 3.3', limit: 60,    resetLabel: 'Minute',  unit: 'req/min'  },
    { key: 'nvidia',     name: 'NVIDIA NIM',         limit: 40,    resetLabel: 'Minute',  unit: 'req/min'  },
    { key: 'openrouter', name: 'OpenRouter',         limit: null,  resetLabel: 'Credits', unit: 'credits'  },
    { key: 'ollama',     name: 'Local / LAN Model',  limit: null,  resetLabel: 'None',    unit: 'unlimited'}
  ];

  MODELS.forEach(({ key, name, limit, resetLabel, unit }) => {
    const configured  = data[`${key}_configured`];
    const isExhausted = exhausted.includes(key);
    const usage       = _usageData[key] || {};

    // ── Dot color ──
    let dotColor, statusClass, statusText;
    const modelCount = _modelCounts[key];
    const countLabel = modelCount > 0 ? `${modelCount} Models` : 'Ready';

    if (!configured) {
      dotColor = '#1e2d3d'; statusClass = 'nokey'; statusText = 'No Key';
    } else if (isExhausted) {
      dotColor = '#ff7b00'; statusClass = 'exhausted'; statusText = 'Exhausted';
    } else {
      dotColor = MODEL_COLORS[key] || '#4a6478'; statusClass = 'ready'; statusText = countLabel;
    }

    // ── Wrapper ──
    const wrap = document.createElement('div');
    wrap.className = 'model-dot-wrap';

    // ── Dot ──
    const dot = document.createElement('div');
    dot.className = `model-dot ${configured && !isExhausted ? 'active' : ''}`;
    dot.style.background = dotColor;
    dot.style.color = dotColor;
    wrap.appendChild(dot);

    // ── Tooltip ──
    const tip = document.createElement('div');
    tip.className = 'model-tooltip';

    // Header row
    const header = document.createElement('div');
    header.className = 'tooltip-header';

    const modelName = document.createElement('span');
    modelName.className = 'tooltip-model-name';
    modelName.style.color = dotColor;
    modelName.textContent = name;

    const badge = document.createElement('span');
    badge.className = `tooltip-status-badge ${statusClass}`;
    badge.textContent = statusText;

    header.appendChild(modelName);
    header.appendChild(badge);
    tip.appendChild(header);

    if (configured) {
      // ── Usage bar (if we have data) ──
      const used  = usage.used  ?? null;
      const pct   = (limit && used !== null) ? Math.min(100, Math.round((used / limit) * 100)) : null;
      const remaining = (limit && used !== null) ? Math.max(0, limit - used) : null;

      if (pct !== null) {
        // Bar color: green → yellow → red based on usage
        const barColor = pct > 85 ? '#ff4444' : pct > 60 ? '#ff7b00' : dotColor;

        const row = document.createElement('div');
        row.className = 'tooltip-row';

        const labelRow = document.createElement('div');
        labelRow.className = 'tooltip-label';

        const labelText = document.createElement('span');
        labelText.className = 'tooltip-label-text';
        labelText.textContent = `${resetLabel} usage`;

        const labelVal = document.createElement('span');
        labelVal.className = 'tooltip-label-val';
        labelVal.style.color = barColor;
        labelVal.textContent = `${used} / ${limit} ${unit}`;

        labelRow.appendChild(labelText);
        labelRow.appendChild(labelVal);

        const track = document.createElement('div');
        track.className = 'tooltip-bar-track';

        const fill = document.createElement('div');
        fill.className = 'tooltip-bar-fill';
        fill.style.width = `${pct}%`;
        fill.style.background = `linear-gradient(90deg, ${barColor}99, ${barColor})`;

        track.appendChild(fill);
        row.appendChild(labelRow);
        row.appendChild(track);
        tip.appendChild(row);

        // Remaining counter
        const remRow = document.createElement('div');
        remRow.className = 'tooltip-row';
        const remLabel = document.createElement('div');
        remLabel.className = 'tooltip-label';

        const remText = document.createElement('span');
        remText.className = 'tooltip-label-text';
        remText.textContent = 'Remaining';

        const remVal = document.createElement('span');
        remVal.className = 'tooltip-label-val';
        remVal.style.color = barColor;
        remVal.textContent = `${remaining.toLocaleString()} ${unit}`;

        remLabel.appendChild(remText);
        remLabel.appendChild(remVal);
        remRow.appendChild(remLabel);
        tip.appendChild(remRow);

        if (usage.resetIn) {
          const div = document.createElement('div');
          div.className = 'tooltip-divider';
          tip.appendChild(div);

          const hint = document.createElement('div');
          hint.className = 'tooltip-hint';
          hint.textContent = `Resets in ${usage.resetIn}`;
          tip.appendChild(hint);
        }

      } else {
        // No usage data yet — show model count if available
        const hint = document.createElement('div');
        hint.className = 'tooltip-hint';
        const countText = _modelCounts[key] > 0
          ? ` · ${_modelCounts[key]} models available`
          : '';
        hint.textContent = isExhausted
          ? `Quota exhausted — auto-skipped until restart${countText}`
          : `Free tier · ${unit}${countText}`;
        tip.appendChild(hint);
      }

      // Hint for key format
      if (data[`${key}_hint`]) {
        const div = document.createElement('div');
        div.className = 'tooltip-divider';
        tip.appendChild(div);
        const keyHint = document.createElement('div');
        keyHint.className = 'tooltip-hint';
        keyHint.textContent = `Key: ${data[`${key}_hint`]}`;
        tip.appendChild(keyHint);
      }

    } else {
      // Not configured
      const hint = document.createElement('div');
      hint.className = 'tooltip-hint';
      hint.textContent = 'Not configured · Open Settings to add a free key';
      tip.appendChild(hint);
    }

    wrap.appendChild(tip);
    bar.appendChild(wrap);
  });
}

async function saveSettings() {
  const payload = {
    gemini_key:      document.getElementById('gemini-key')?.value.trim()     || '',
    nvidia_key:      document.getElementById('nvidia-key')?.value.trim()     || '',
    openrouter_key:  document.getElementById('openrouter-key')?.value.trim() || '',
    groq_key:        document.getElementById('groq-key')?.value.trim()       || '',
    cerebras_key:    document.getElementById('cerebras-key')?.value.trim()   || '',
    ollama_model:    document.getElementById('ollama-model')?.value.trim()   || '',
    ollama_base_url: document.getElementById('ollama-url')?.value.trim()     || 'http://localhost:11434',
    // Also send without _key suffix (backend accepts both)
    gemini:     document.getElementById('gemini-key')?.value.trim()     || '',
    groq:       document.getElementById('groq-key')?.value.trim()       || '',
    cerebras:   document.getElementById('cerebras-key')?.value.trim()   || '',
    nvidia:     document.getElementById('nvidia-key')?.value.trim()     || '',
    openrouter: document.getElementById('openrouter-key')?.value.trim() || '',
  };

  const msgEl = document.getElementById('settings-msg');
  try {
    const data = await secureFetch('/api/settings', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
    msgEl.textContent = data.message || 'Saved.';
    msgEl.className = 'settings-msg success';
    msgEl.classList.remove('hidden');
    // Clear inputs
    ['gemini-key','nvidia-key','openrouter-key','groq-key','cerebras-key'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    await loadSettings();
    setTimeout(() => msgEl.classList.add('hidden'), 5000);
  } catch (e) {
    msgEl.textContent = e.message || 'Save failed.';
    msgEl.className = 'settings-msg error';
    msgEl.classList.remove('hidden');
  }
}

function showSettings() {
  document.getElementById('settings-modal').classList.remove('hidden');
  loadEngineSettings();
  loadLocalSettings();
}
function hideSettings()  { document.getElementById('settings-modal').classList.add('hidden'); }

document.addEventListener('click', e => {
  if (e.target === document.getElementById('settings-modal')) hideSettings();
  // Close any open export dropdown menus when clicking elsewhere
  if (!e.target.closest('.export-dropdown')) {
    document.querySelectorAll('.export-menu.open').forEach(m => m.classList.remove('open'));
  }
});

// ── Conversations ─────────────────────────────────────────────────────────────
async function loadConversations() {
  try {
    const convs = await secureFetch('/api/conversations');
    const list  = document.getElementById('conv-list');
    list.innerHTML = '';

    if (!convs.length) {
      const empty = document.createElement('div');
      empty.className = 'conv-item';
      empty.style.cssText = 'opacity:.4;cursor:default;font-size:11px;';
      empty.textContent = 'No conversations yet';
      list.appendChild(empty);
      return;
    }

    convs.forEach(conv => {
      const item = document.createElement('div');
      item.className = 'conv-item';
      item.dataset.id = conv.id;

      // Icon
      const icon = document.createElement('span');
      icon.textContent = '💬';
      icon.style.cssText = 'opacity:.4;flex-shrink:0;font-size:11px;';

      // Body
      const body = document.createElement('div');
      body.className = 'conv-item-body';

      const title = document.createElement('div');
      title.className = 'conv-title';
      title.textContent = conv.title; // textContent — XSS safe

      const meta = document.createElement('div');
      meta.className = 'conv-meta';
      meta.textContent = `${conv.message_count} msgs · ${formatDate(conv.updated_at)}`;

      body.appendChild(title);
      body.appendChild(meta);

      // Delete button
      const del = document.createElement('button');
      del.className = 'conv-delete';
      del.textContent = '×';
      del.title = 'Delete conversation';
      del.addEventListener('click', async e => {
        e.stopPropagation();
        if (!confirm('Delete this conversation?')) return;
        await deleteConversation(conv.id);
      });

      item.appendChild(icon);
      item.appendChild(body);
      item.appendChild(del);
      item.addEventListener('click', () => loadConversation(conv.id));
      list.appendChild(item);
    });
  } catch (e) {
    console.error('Conversations load failed:', e.message);
  }
}

async function loadConversation(id) {
  try {
    const data = await secureFetch(`/api/conversations/${encodeURIComponent(id)}`);
    state.currentConvId = data.id;
    state.messages      = data.messages || [];
    setText('current-conv-title', data.title || 'Conversation');
    renderMessages();
    highlightConv(id);
  } catch (e) {
    console.error('Load conversation failed:', e.message);
  }
}

async function deleteConversation(id) {
  try {
    await secureFetch(`/api/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (state.currentConvId === id) newChat();
    await loadConversations();
  } catch (e) {
    console.error('Delete conversation failed:', e.message);
  }
}

function highlightConv(id) {
  document.querySelectorAll('.conv-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === id);
  });
}

function newChat() {
  state.currentConvId = null;
  state.messages      = [];
  setText('current-conv-title', 'New Conversation');

  const msgs = document.getElementById('messages');
  msgs.innerHTML = '';

  // Re-create welcome state
  const welcome = document.createElement('div');
  welcome.id = 'welcome-state';
  welcome.className = 'welcome-state';
  welcome.innerHTML = `
    <div class="welcome-logo"><img src="/static/NCXLogo.png" alt="" class="welcome-logo-img"></div>
    <h1 class="welcome-title">NeuConX</h1>
    <p class="welcome-sub">Multiple minds. One truth. Always free.</p>
    <div id="no-keys-warning" class="no-keys-banner hidden">
      ⚠️ No API keys configured — open Settings to add free keys.
    </div>
    <div class="starter-chips">
      <button class="chip" data-prompt="Explain quantum entanglement simply">Explain quantum entanglement</button>
      <button class="chip" data-prompt="Write a Python function to flatten a nested list">Flatten nested list in Python</button>
      <button class="chip" data-prompt="What are the top 5 personal finance principles?">Personal finance principles</button>
      <button class="chip" data-prompt="Compare REST vs GraphQL APIs">REST vs GraphQL</button>
    </div>
  `;
  msgs.appendChild(welcome);
  setupStarters();
  loadSettings(); // Re-check no-keys warning
  document.querySelectorAll('.conv-item').forEach(el => el.classList.remove('active'));
}

// ── Skills ────────────────────────────────────────────────────────────────────

// ── Phase 4: Skills System ────────────────────────────────────────────────────

let currentEditingSkill = null;

async function loadSkills() {
  try {
    const skills = await secureFetch('/api/skills');
    const list   = document.getElementById('skills-list');
    list.innerHTML = '';
    skills.forEach(skill => {
      const item = document.createElement('div');
      item.className = 'skill-item';

      const toggle = document.createElement('button');
      toggle.className = 'skill-toggle';
      toggle.setAttribute('aria-label', `Toggle ${skill.name}`);
      toggle.addEventListener('click', () => {
        const on = toggle.classList.toggle('on');
        if (on) state.activeSkills.add(skill.filename);
        else    state.activeSkills.delete(skill.filename);
        updateActiveSkillsDisplay();
      });

      const nameWrap = document.createElement('div');
      nameWrap.style.cssText = 'flex:1;min-width:0;';

      const name = document.createElement('span');
      name.className = 'skill-name';
      name.textContent = skill.name;
      name.title = skill.description || skill.preview;

      const cat = document.createElement('span');
      cat.style.cssText = 'font-size:9px;color:var(--text-dim);display:block;margin-top:1px;';
      cat.textContent = skill.category || 'custom';

      nameWrap.appendChild(name);
      nameWrap.appendChild(cat);

      const editBtn = document.createElement('button');
      editBtn.style.cssText = 'background:none;border:none;color:var(--text-dim);cursor:pointer;font-size:11px;padding:2px 4px;opacity:0;transition:opacity .15s;';
      editBtn.textContent = '✎';
      editBtn.title = 'Edit skill';
      editBtn.addEventListener('click', (e) => { e.stopPropagation(); openSkillEditor(skill.name); });
      item.addEventListener('mouseenter', () => editBtn.style.opacity = '1');
      item.addEventListener('mouseleave', () => editBtn.style.opacity = '0');

      item.appendChild(toggle);
      item.appendChild(nameWrap);

      // PDF theme picker — shown only for the pdf_creator skill
      if (skill.filename === 'pdf_creator.md') {
        const themeSelect = document.createElement('select');
        themeSelect.className = 'pdf-theme-select';
        themeSelect.title = 'Theme for generated PDF files';
        themeSelect.innerHTML = `
          <option value="professional">Clean Pro</option>
          <option value="ncx">NCX Dark</option>
        `;
        themeSelect.value = state.pdfTheme;
        themeSelect.style.display = toggle.classList.contains('on') ? 'block' : 'none';
        themeSelect.onclick = (e) => e.stopPropagation();
        themeSelect.onchange = () => { state.pdfTheme = themeSelect.value; };

        // Show/hide the theme picker alongside the existing toggle handler
        toggle.addEventListener('click', () => {
          themeSelect.style.display = toggle.classList.contains('on') ? 'block' : 'none';
        });

        item.appendChild(themeSelect);
      }

      item.appendChild(editBtn);
      list.appendChild(item);
    });
  } catch (e) {
    console.error('Skills load failed:', e.message);
  }
}

async function openSkillEditor(skillName) {
  try {
    const skill = skillName
      ? await secureFetch(`/api/skills/${encodeURIComponent(skillName)}.md`)
      : { name: 'new_skill', content: '# Skill: New Skill\n\nCategory: custom\nDescription: What this skill does\n\n## Instructions\n\nDescribe the skill behaviour here.' };

    currentEditingSkill = skill.name;

    // Build modal
    const existing = document.getElementById('skill-editor-modal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'skill-editor-modal';
    modal.className = 'modal';
    modal.style.cssText = 'z-index:1100;';

    const card = document.createElement('div');
    card.className = 'modal-card';
    card.style.cssText = 'max-width:680px;width:95%;';

    card.innerHTML = `
      <div class="modal-header">
        <h3>✎ Skill Editor${skill.name ? ' — ' + skill.name : ''}</h3>
        <button class="modal-close" onclick="closeSkillEditor()">×</button>
      </div>
      <div style="display:flex;gap:8px;margin-bottom:10px;align-items:center;">
        <input id="skill-editor-name" class="settings-input" style="width:200px;" 
          value="${skill.name || ''}" placeholder="skill_name">
        <select id="skill-editor-cat" class="settings-input" style="width:140px;background:var(--surface2);">
          ${['writing','coding','research','analysis','creative','productivity','custom']
            .map(c => `<option value="${c}" ${(skill.category||'custom')===c?'selected':''}>${c}</option>`).join('')}
        </select>
        <span style="font-size:10px;color:var(--text-dim);">category</span>
      </div>
      <textarea id="skill-editor-content" style="
        width:100%;height:320px;background:var(--surface2);border:1px solid var(--border);
        border-radius:var(--radius);padding:12px;color:var(--text);font-family:var(--font-mono);
        font-size:12px;resize:vertical;outline:none;line-height:1.6;
      ">${skill.content || ''}</textarea>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;">
        <div style="font-size:10px;color:var(--text-dim);">Markdown format · Max 50KB</div>
        <div style="display:flex;gap:8px;">
          ${skillName ? `<button class="btn-ghost" onclick="deleteSkillFromEditor('${skill.name}')" 
            style="border-color:rgba(255,68,68,.3);color:var(--red);font-size:12px;">🗑 Delete</button>` : ''}
          <button class="btn-primary" onclick="saveSkillFromEditor()" style="font-size:12px;padding:8px 16px;">💾 Save</button>
        </div>
      </div>
      <div id="skill-editor-msg" style="display:none;font-size:11px;margin-top:8px;"></div>
    `;

    modal.appendChild(card);
    document.body.appendChild(modal);
    modal.addEventListener('click', e => { if (e.target === modal) closeSkillEditor(); });
    document.getElementById('skill-editor-content').focus();
  } catch(e) {
    showToast('Failed to open skill editor: ' + e.message);
  }
}

async function saveSkillFromEditor() {
  const name    = document.getElementById('skill-editor-name')?.value.trim().replace(/[^a-zA-Z0-9_\-]/g, '_');
  const cat     = document.getElementById('skill-editor-cat')?.value;
  const content = document.getElementById('skill-editor-content')?.value;
  const msgEl   = document.getElementById('skill-editor-msg');

  if (!name || !content) { showToast('Name and content required'); return; }

  // Prepend category metadata if not present
  let finalContent = content;
  if (!content.toLowerCase().includes('category:')) {
    finalContent = `Category: ${cat}\n` + content;
  }

  try {
    await secureFetch(`/api/skills/${encodeURIComponent(name)}.md`, {
      method: 'PUT',
      body: JSON.stringify({ content: finalContent })
    });
    if (msgEl) { msgEl.textContent = '✓ Saved'; msgEl.style.color = 'var(--green)'; msgEl.style.display='block'; }
    setTimeout(() => closeSkillEditor(), 1200);
    await loadSkills();
    showToast(`Skill "${name}" saved`);
  } catch(e) {
    if (msgEl) { msgEl.textContent = '✗ ' + e.message; msgEl.style.color = 'var(--red)'; msgEl.style.display='block'; }
  }
}

async function deleteSkillFromEditor(skillName) {
  if (!confirm(`Delete skill "${skillName}"? This cannot be undone.`)) return;
  try {
    await secureFetch(`/api/skills/${encodeURIComponent(skillName)}.md`, { method: 'DELETE' });
    closeSkillEditor();
    await loadSkills();
    showToast(`Skill "${skillName}" deleted`);
  } catch(e) {
    showToast('Delete failed: ' + e.message);
  }
}

function closeSkillEditor() {
  document.getElementById('skill-editor-modal')?.remove();
  currentEditingSkill = null;
}


function updateActiveSkillsDisplay() {
  const el = document.getElementById('active-skills-display');
  el.innerHTML = '';
  state.activeSkills.forEach(s => {
    const tag = document.createElement('span');
    tag.className = 'active-skill-tag';
    tag.textContent = s.replace('.md', ''); // textContent — XSS safe
    el.appendChild(tag);
  });
}

async function uploadSkill(event) {
  const file = event.target.files[0];
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.md')) { alert('Only .md files allowed'); return; }
  if (file.size > 50 * 1024) { alert('Max 50KB per skill file'); return; }

  const form = new FormData();
  form.append('file', file);
  try {
    const res = await fetch('/api/skills/upload', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRF-Token': getCSRFToken() },
      body: form
    });
    if (res.ok) await loadSkills();
    else { const e = await res.json(); alert(e.error || 'Upload failed'); }
  } catch (e) {
    console.error('Upload error:', e.message);
  }
  event.target.value = '';
}

// ── Phase 3: Memory ────────────────────────────────────────────────────────────
async function clearMemory() {
  if (!confirm('Clear session memory? The AI will forget recent context.')) return;
  try {
    await secureFetch('/api/memory/clear', { method: 'POST' });
    state.messages = [];
    showToast('Session memory cleared');
  } catch (e) {
    console.error('Clear memory failed:', e.message);
  }
}

// ── Chat ──────────────────────────────────────────────────────────────────────
function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 180) + 'px';
}

async function sendMessage() {
  if (state.isLoading) return;
  const input   = document.getElementById('chat-input');
  const message = input.value.trim();
  if (!message) return;
  if (message.length > 8000) { alert('Message too long (max 8000 chars)'); return; }

  input.value = '';
  input.style.height = 'auto';
  autoResize(input);
  state.isLoading = true;

  // Switch send button → stop button
  setSendMode('stop');

  document.getElementById('welcome-state')?.remove();

  addMessage('user', message);
  state.messages.push({ role: 'user', content: message, timestamp: new Date().toISOString() });

  const thinkId = addThinking();

  // AbortController for stop button
  state.abortController = new AbortController();

  try {
    const tune = autoTuneParams(message);
    const payload = {
      message,
      history:      state.messages.slice(-20),
      tier_override: state.selectedTier === 'auto' ? null : state.selectedTier,
      skills_active: Array.from(state.activeSkills),
      personalized:  state.personalized,
      pinned_model:  state.pinnedModel,
      pdf_theme:     state.pdfTheme,
      autotune:      tune   // {temperature, top_p, context}
    };

    const data = await secureFetch('/api/chat', {
      method: 'POST',
      body:   JSON.stringify(payload),
      signal: state.abortController.signal
    });

    removeThinking(thinkId);

    const answer = data.final_answer || 'No response received.';
    addMessage('ai', answer, data.tier_used, data.models_used, data.models_called, data.personalized, message, data.generated_file);
    state.messages.push({ role: 'assistant', content: answer, timestamp: new Date().toISOString() });

    updateModelResponses(data.model_responses || []);
    setText('tier-display', `${data.tier_used || 'auto'} · ${data.models_used || 0} model${data.models_used !== 1 ? 's' : ''}`);
    setText('models-display', data.models_called?.join(' · ') || '');

    await saveCurrentConversation();
    await Promise.all([loadSettings(), fetchUsage(), checkRAGStatus()]);
    setTimeout(checkMemoryCandidates, 1500);

  } catch (e) {
    removeThinking(thinkId);
    if (e.name === 'AbortError') {
      addMessage('ai', '⏹ Response stopped.');
    } else {
      addMessage('ai', `⚠️ Error: ${e.message}`);
      console.error('Chat error:', e.message);
    }
  } finally {
    state.isLoading = false;
    state.abortController = null;
    setSendMode('send');
    input.focus();
  }
}

function stopQuery() {
  if (state.abortController) {
    state.abortController.abort();
  }
}

function setSendMode(mode) {
  const btn = document.getElementById('send-btn');
  if (!btn) return;
  if (mode === 'stop') {
    btn.textContent   = '⏹';
    btn.title         = 'Stop (cancel request)';
    btn.onclick       = stopQuery;
    btn.disabled      = false;
    btn.style.background = 'rgba(255,68,68,0.25)';
    btn.style.borderColor = 'rgba(255,68,68,0.5)';
    btn.style.color   = '#ff4444';
  } else {
    btn.textContent   = '↑';
    btn.title         = 'Send (Enter)';
    btn.onclick       = sendMessage;
    btn.disabled      = false;
    btn.style.background = '';
    btn.style.borderColor = '';
    btn.style.color   = '';
  }
}

// ── Markdown renderer ─────────────────────────────────────────────────────────
// Configure marked once — used for AI responses only.
// User messages always use textContent (never innerHTML) for XSS safety.
function setupMarked() {
  if (typeof marked === 'undefined') return;
  marked.setOptions({
    breaks:   true,   // single newline → <br>
    gfm:      true,   // GitHub-flavored markdown
    pedantic: false,
    sanitize: false   // we control the source (AI response only, not user input)
  });
}

function renderMarkdown(text) {
  if (typeof marked === 'undefined') return escapeHtml(text);
  try {
    return marked.parse(text);
  } catch(e) {
    return escapeHtml(text);
  }
}

// ── Per-block copy buttons ────────────────────────────────────────────────────
// Adds a small copy icon to every <pre> (code block) and <table> rendered
// inside a markdown container, without touching any other rendering logic.
function addCopyButtons(container) {
  if (!container) return;

  // Code blocks
  container.querySelectorAll('pre').forEach(pre => {
    if (pre.parentElement && pre.parentElement.classList.contains('copyable-block')) return;

    const wrapper = document.createElement('div');
    wrapper.className = 'copyable-block copyable-pre';

    const btn = document.createElement('button');
    btn.className = 'block-copy-btn';
    btn.title = 'Copy code';
    btn.textContent = '⎘';
    btn.onclick = (e) => {
      e.stopPropagation();
      const codeEl = pre.querySelector('code');
      const text = codeEl ? codeEl.innerText : pre.innerText;
      navigator.clipboard.writeText(text).then(() => {
        btn.textContent = '✓';
        btn.classList.add('copied');
        setTimeout(() => { btn.textContent = '⎘'; btn.classList.remove('copied'); }, 1500);
      });
    };

    pre.parentNode.insertBefore(wrapper, pre);
    wrapper.appendChild(pre);
    wrapper.appendChild(btn);
  });

  // Tables — copy as TSV (paste-friendly into Excel/Sheets)
  container.querySelectorAll('table').forEach(table => {
    if (table.parentElement && table.parentElement.classList.contains('copyable-block')) return;

    const wrapper = document.createElement('div');
    wrapper.className = 'copyable-block copyable-table';

    const btn = document.createElement('button');
    btn.className = 'block-copy-btn';
    btn.title = 'Copy table';
    btn.textContent = '⎘';
    btn.onclick = (e) => {
      e.stopPropagation();
      const rows = Array.from(table.querySelectorAll('tr')).map(tr =>
        Array.from(tr.querySelectorAll('th,td')).map(cell => cell.innerText.trim()).join('\t')
      );
      navigator.clipboard.writeText(rows.join('\n')).then(() => {
        btn.textContent = '✓';
        btn.classList.add('copied');
        setTimeout(() => { btn.textContent = '⎘'; btn.classList.remove('copied'); }, 1500);
      });
    };

    table.parentNode.insertBefore(wrapper, table);
    wrapper.appendChild(table);
    wrapper.appendChild(btn);
  });
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ── Standalone markdown block tokenizer (for exports) ─────────────────────────
// The bundled marked.min.js is a custom lightweight parser with only .parse(),
// no .lexer(). This mirrors its block-splitting logic so PDF/DOCX exports get
// real structured tokens (heading/paragraph/ul/ol/table/code/blockquote/hr)
// instead of one giant paragraph.
function simpleMdTokenize(src) {
  const tokens = [];
  const lines = src.split('\n');
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) { i++; continue; }

    // Fenced code block
    if (/^```/.test(line)) {
      const lang = line.slice(3).trim();
      const code = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) { code.push(lines[i]); i++; }
      i++;
      tokens.push({ type: 'code', lang, text: code.join('\n') });
      continue;
    }

    // Heading
    const hm = line.match(/^(#{1,6})\s+(.+)$/);
    if (hm) {
      tokens.push({ type: 'heading', depth: hm[1].length, text: hm[2] });
      i++;
      continue;
    }

    // HR
    if (/^(?:---+|===+|\*\*\*+)\s*$/.test(line.trim())) {
      tokens.push({ type: 'hr' });
      i++;
      continue;
    }

    // Blockquote
    if (/^> /.test(line)) {
      const bq = [];
      while (i < lines.length && /^> /.test(lines[i])) { bq.push(lines[i].slice(2)); i++; }
      tokens.push({ type: 'blockquote', text: bq.join('\n') });
      continue;
    }

    // Unordered list
    if (/^[\-\*\+] /.test(line)) {
      const items = [];
      while (i < lines.length && /^[\-\*\+] /.test(lines[i])) { items.push(lines[i].replace(/^[\-\*\+] /, '')); i++; }
      tokens.push({ type: 'ul', items });
      continue;
    }

    // Ordered list
    if (/^\d+[\.\)] /.test(line)) {
      const items = [];
      while (i < lines.length && /^\d+[\.\)] /.test(lines[i])) { items.push(lines[i].replace(/^\d+[\.\)] /, '')); i++; }
      tokens.push({ type: 'ol', items });
      continue;
    }

    // Table
    if (/\|/.test(line) && i + 1 < lines.length && /\|[\s\-:]+\|/.test(lines[i+1])) {
      const headers = lines[i].split('|').map(c => c.trim()).filter(Boolean);
      i += 2;
      const rows = [];
      while (i < lines.length && /\|/.test(lines[i]) && lines[i].trim()) {
        rows.push(lines[i].split('|').map(c => c.trim()).filter(Boolean));
        i++;
      }
      tokens.push({ type: 'table', headers, rows });
      continue;
    }

    // Paragraph
    const pLines = [];
    while (i < lines.length && lines[i].trim() &&
           !/^#{1,6} /.test(lines[i]) &&
           !/^```/.test(lines[i]) &&
           !/^[\-\*\+] /.test(lines[i]) &&
           !/^\d+[\.\)] /.test(lines[i]) &&
           !/^> /.test(lines[i]) &&
           !/^(?:---+|===+|\*\*\*+)\s*$/.test(lines[i].trim()) &&
           !(/\|/.test(lines[i]) && i + 1 < lines.length && /\|[\s\-:]+\|/.test(lines[i+1]))) {
      pLines.push(lines[i]);
      i++;
    }
    if (pLines.length) tokens.push({ type: 'paragraph', text: pLines.join('\n') });
  }
  return tokens;
}

// ── Export AI message to PDF / DOCX / TXT ─────────────────────────────────────
// Uses simpleMdTokenize() to get structured tokens (headings, paragraphs, lists,
// tables, code blocks) so PDF/DOCX output preserves real document structure
// instead of dumping raw markdown text.

function _exportFilename(ext) {
  const stamp = new Date().toISOString().slice(0,19).replace(/[:T]/g, '-');
  return `neuconx-response-${stamp}.${ext}`;
}

function _downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function exportAsTXT(content) {
  // Strip markdown syntax markers for a clean plain-text read
  const text = content
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/`{1,3}([^`]*)`{1,3}/g, '$1')
    .replace(/^\s*[-*+]\s+/gm, '• ')
    .replace(/^>\s?/gm, '');
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
  _downloadBlob(blob, _exportFilename('txt'));
}

function exportAsPDF(content) {
  if (typeof window.jspdf === 'undefined') {
    showToast('PDF export unavailable — library not loaded');
    return;
  }
  const { jsPDF } = window.jspdf;

  // jsPDF's built-in fonts (helvetica/courier) have no emoji glyphs and no
  // LaTeX renderer — strip/convert so output doesn't show garbled boxes.
  const cleanPdfText = (text) => {
    if (!text) return '';
    return text
      // Common inline LaTeX -> plain text equivalents
      .replace(/\$\\rightarrow\$/g, '->')
      .replace(/\$\\leftrightarrow\$/g, '<->')
      .replace(/\$\\sim\$/g, '~')
      .replace(/\$\\approx\$/g, '~=')
      .replace(/\\rightarrow/g, '->')
      .replace(/\\leftrightarrow/g, '<->')
      .replace(/\\sim/g, '~')
      .replace(/\\approx/g, '~=')
      // Strip any remaining $...$ math delimiters, keep inner text
      .replace(/\$([^$]+)\$/g, '$1')
      // Strip backslash-escaped LaTeX commands like \uparrow, \downarrow
      .replace(/\\[a-zA-Z]+/g, '')
      // Strip emoji and other symbols outside the Basic Latin/Latin-1 + common punctuation range
      // (keeps letters, numbers, standard punctuation; removes pictographic/symbol code points)
      .replace(/[\u{1F000}-\u{1FFFF}]/gu, '')
      .replace(/[\u{2190}-\u{2BFF}]/gu, '') // arrows, misc symbols, dingbats
      .replace(/[\u{2600}-\u{27BF}]/gu, '') // misc symbols & pictographs, dingbats
      .replace(/[\u{FE00}-\u{FE0F}]/gu, '') // variation selectors
      .replace(/\s{2,}/g, ' ')
      .trim();
  };

  const doc = new jsPDF({ unit: 'pt', format: 'a4' });
  const pageW = doc.internal.pageSize.getWidth();
  const pageH = doc.internal.pageSize.getHeight();
  const margin = 48;
  const maxW = pageW - margin * 2;
  let y = margin;

  const ensureSpace = (lineH) => {
    if (y + lineH > pageH - margin) {
      doc.addPage();
      y = margin;
    }
  };

  const writeWrapped = (text, fontSize, style, lineH, color) => {
    doc.setFont('helvetica', style || 'normal');
    doc.setFontSize(fontSize);
    if (color) doc.setTextColor(...color); else doc.setTextColor(20, 20, 20);
    const lines = doc.splitTextToSize(cleanPdfText(text), maxW);
    lines.forEach(line => {
      ensureSpace(lineH);
      doc.text(line, margin, y);
      y += lineH;
    });
  };

  const tokens = simpleMdTokenize(content);

  tokens.forEach(token => {
    switch (token.type) {
      case 'heading': {
        const sizes = { 1: 20, 2: 16, 3: 13, 4: 12, 5: 11, 6: 11 };
        y += 6;
        writeWrapped(token.text, sizes[token.depth] || 12, 'bold', (sizes[token.depth] || 12) + 4, [0, 130, 150]);
        y += 4;
        break;
      }
      case 'paragraph':
        writeWrapped((token.text || '').replace(/\*\*/g, '').replace(/\*/g, ''), 11, 'normal', 15);
        y += 6;
        break;
      case 'ul':
      case 'ol':
        (token.items || []).forEach((item, idx) => {
          const prefix = token.type === 'ol' ? `${idx + 1}. ` : '• ';
          writeWrapped(prefix + String(item).replace(/\*\*/g, '').replace(/\*/g, ''), 11, 'normal', 15);
        });
        y += 6;
        break;
      case 'code':
        ensureSpace(20);
        doc.setFillColor(245, 247, 248);
        doc.setDrawColor(220, 224, 228);
        const codeLines = doc.splitTextToSize(token.text || '', maxW - 12);
        const blockH = codeLines.length * 12 + 10;
        ensureSpace(blockH);
        doc.rect(margin, y - 8, maxW, blockH, 'FD');
        doc.setFont('courier', 'normal');
        doc.setFontSize(9);
        doc.setTextColor(40, 40, 40);
        codeLines.forEach(line => {
          doc.text(line, margin + 6, y);
          y += 12;
        });
        y += 10;
        break;
      case 'table': {
        const cellPad = 4;
        const cols = token.headers.length;
        const colW = maxW / cols;
        const lineH = 11;
        doc.setFontSize(9);

        // Header row (headers rarely wrap, but handle it anyway)
        const headerLines = token.headers.map(cell =>
          doc.splitTextToSize(cleanPdfText(String(cell || '')).replace(/\*\*/g, ''), colW - cellPad * 2)
        );
        const headerRowH = Math.max(...headerLines.map(l => l.length), 1) * lineH + 6;
        ensureSpace(headerRowH);
        doc.setFillColor(0, 180, 200);
        doc.rect(margin, y - 10, maxW, headerRowH, 'F');
        doc.setTextColor(255, 255, 255);
        doc.setFont('helvetica', 'bold');
        headerLines.forEach((cellLines, i) => {
          cellLines.forEach((line, li) => {
            doc.text(line, margin + i * colW + cellPad, y + li * lineH);
          });
        });
        y += headerRowH;

        // Body rows — wrap each cell, size row to tallest cell
        doc.setFont('helvetica', 'normal');
        doc.setTextColor(20, 20, 20);
        (token.rows || []).forEach((row, ri) => {
          const cellLines = row.map(cell =>
            doc.splitTextToSize(cleanPdfText(String(cell || '')).replace(/\*\*/g, ''), colW - cellPad * 2)
          );
          const rowH = Math.max(...cellLines.map(l => l.length), 1) * lineH + 6;
          ensureSpace(rowH);
          if (ri % 2 === 1) {
            doc.setFillColor(245, 247, 248);
            doc.rect(margin, y - 10, maxW, rowH, 'F');
          }
          cellLines.forEach((lines, i) => {
            lines.forEach((line, li) => {
              doc.text(line, margin + i * colW + cellPad, y + li * lineH);
            });
          });
          y += rowH;
        });
        y += 8;
        break;
      }
      case 'blockquote':
        writeWrapped((token.text || '').replace(/\*\*/g, ''), 11, 'italic', 15, [90, 100, 110]);
        y += 6;
        break;
      case 'hr':
        ensureSpace(10);
        doc.setDrawColor(220, 224, 228);
        doc.line(margin, y, pageW - margin, y);
        y += 12;
        break;
      case 'math':
        writeWrapped(token.text || '', 11, 'italic', 15);
        y += 6;
        break;
      default:
        if (token.text) writeWrapped(token.text, 11, 'normal', 15);
    }
  });

  doc.save(_exportFilename('pdf'));
}

async function exportAsDOCX(content) {
  if (typeof docx === 'undefined') {
    showToast('DOCX export unavailable — library not loaded');
    return;
  }
  const { Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell,
          WidthType, BorderStyle, AlignmentType } = docx;

  const tokens = simpleMdTokenize(content);

  const headingMap = {
    1: HeadingLevel.HEADING_1,
    2: HeadingLevel.HEADING_2,
    3: HeadingLevel.HEADING_3,
    4: HeadingLevel.HEADING_4,
    5: HeadingLevel.HEADING_5,
    6: HeadingLevel.HEADING_6,
  };

  // Parse simple **bold** / *italic* into TextRuns
  const toRuns = (text) => {
    const runs = [];
    const re = /(\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`)/g;
    let last = 0, m;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) runs.push(new TextRun(text.slice(last, m.index)));
      if (m[2] !== undefined) runs.push(new TextRun({ text: m[2], bold: true }));
      else if (m[3] !== undefined) runs.push(new TextRun({ text: m[3], italics: true }));
      else if (m[4] !== undefined) runs.push(new TextRun({ text: m[4], font: 'Courier New', shading: { fill: 'F0F0F0' } }));
      last = re.lastIndex;
    }
    if (last < text.length) runs.push(new TextRun(text.slice(last)));
    return runs.length ? runs : [new TextRun(text)];
  };

  const children = [];

  tokens.forEach(token => {
    switch (token.type) {
      case 'heading':
        children.push(new Paragraph({
          children: toRuns(token.text),
          heading: headingMap[token.depth] || HeadingLevel.HEADING_4,
        }));
        break;
      case 'paragraph':
        children.push(new Paragraph({ children: toRuns(token.text || '') }));
        break;
      case 'ul':
      case 'ol':
        (token.items || []).forEach((item, idx) => {
          if (token.type === 'ol') {
            children.push(new Paragraph({
              children: [new TextRun(`${idx + 1}. `), ...toRuns(String(item || ''))],
            }));
          } else {
            children.push(new Paragraph({
              children: toRuns(String(item || '')),
              bullet: { level: 0 },
            }));
          }
        });
        break;
      case 'code':
        (token.text || '').split('\n').forEach(line => {
          children.push(new Paragraph({
            children: [new TextRun({ text: line || ' ', font: 'Courier New', size: 18 })],
            shading: { fill: 'F5F7F8' },
          }));
        });
        break;
      case 'table': {
        const borders = {
          top: { style: BorderStyle.SINGLE, size: 1, color: 'CCCCCC' },
          bottom: { style: BorderStyle.SINGLE, size: 1, color: 'CCCCCC' },
          left: { style: BorderStyle.SINGLE, size: 1, color: 'CCCCCC' },
          right: { style: BorderStyle.SINGLE, size: 1, color: 'CCCCCC' },
        };
        const headerRow = new TableRow({
          children: token.headers.map(cell => new TableCell({
            children: [new Paragraph({ children: toRuns(String(cell || '')) })],
            shading: { fill: '00B4C8' },
            borders,
          })),
        });
        const bodyRows = (token.rows || []).map(row => new TableRow({
          children: row.map(cell => new TableCell({
            children: [new Paragraph({ children: toRuns(String(cell || '')) })],
            borders,
          })),
        }));
        children.push(new Table({
          rows: [headerRow, ...bodyRows],
          width: { size: 100, type: WidthType.PERCENTAGE },
        }));
        children.push(new Paragraph({ text: '' }));
        break;
      }
      case 'blockquote':
        children.push(new Paragraph({
          children: toRuns(token.text || ''),
          indent: { left: 480 },
          style: 'IntenseQuote',
        }));
        break;
      case 'hr':
        children.push(new Paragraph({
          border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: 'CCCCCC' } },
        }));
        break;
      case 'space':
        break;
      default:
        if (token.text) children.push(new Paragraph({ children: toRuns(token.text) }));
    }
  });

  const doc = new Document({
    sections: [{ properties: {}, children }],
  });

  const blob = await Packer.toBlob(doc);
  _downloadBlob(blob, _exportFilename('docx'));
}

// ── STM (Semantic Transformation Modules) ────────────────────────────────────
// Client-side post-processors — zero API cost, run on rendered text
const STM = {
  directMode: (text) => {
    // Strip AI preamble phrases
    return text
      .replace(/^(Sure[,!]?\s*)/i, '')
      .replace(/^(Certainly[,!]?\s*)/i, '')
      .replace(/^(Absolutely[,!]?\s*)/i, '')
      .replace(/^(Of course[,!]?\s*)/i, '')
      .replace(/^(Great question[!.]?\s*)/i, '')
      .replace(/^(That'?s? a great question[!.]?\s*)/i, '')
      .replace(/^(I'?d be happy to help( you)?( with that)?[.!]?\s*)/i, '')
      .replace(/^(Let me help you with that[.!]?\s*)/i, '')
      .replace(/^(Thanks for (asking|sharing)[.!]?\s*)/i, '')
      .replace(/^([A-z])/, c => c.toUpperCase());
  },
  hedgeReducer: (text) => {
    // Remove hedging phrases that weaken responses
    return text
      .replace(/\bI think\s+/gi, '')
      .replace(/\bI believe\s+/gi, '')
      .replace(/\bperhaps\s+/gi, '')
      .replace(/\bmaybe\s+/gi, '')
      .replace(/\bIt seems (like|that)\s+/gi, '')
      .replace(/\bIt appears (that)?\s+/gi, '')
      .replace(/\bprobably\s+/gi, '')
      .replace(/\bIn my opinion,?\s*/gi, '')
      .replace(/^([a-z])/, c => c.toUpperCase());
  },
  casualMode: (text) => {
    // Formality reduction
    return text
      .replace(/\bHowever\b/g, 'But')
      .replace(/\bTherefore\b/g, 'So')
      .replace(/\bFurthermore\b/g, 'Also')
      .replace(/\bAdditionally\b/g, 'Plus')
      .replace(/\bNevertheless\b/g, 'Still')
      .replace(/\bMoreover\b/g, 'Also')
      .replace(/\bUtilize\b/g, 'Use')
      .replace(/\butilize\b/g, 'use')
      .replace(/\bIn order to\b/gi, 'To')
      .replace(/\bDue to the fact that\b/gi, 'Because')
      .replace(/\bAt this point in time\b/gi, 'Now')
      .replace(/\bPrior to\b/gi, 'Before');
  }
};

// Active STM modules state
const stmState = {
  directMode:   false,
  hedgeReducer: false,
  casualMode:   false,
};

function applySTM(text) {
  let result = text;
  if (stmState.directMode)   result = STM.directMode(result);
  if (stmState.hedgeReducer) result = STM.hedgeReducer(result);
  if (stmState.casualMode)   result = STM.casualMode(result);
  return result;
}

function addMessage(role, content, tier, modelsUsed, modelsCalled, personalized, originalPrompt, generatedFile) {
  // Apply STM transforms to AI responses before rendering
  const displayContent = (role === 'ai') ? applySTM(content) : content;

  const msgs    = document.getElementById('messages');
  const wrapper = document.createElement('div');
  wrapper.className = `message message-${role}`;
  // Store raw content for copy/rerun
  wrapper.dataset.content = content;
  wrapper.dataset.prompt  = originalPrompt || '';

  const bubble = document.createElement('div');
  bubble.className = 'bubble';

  if (role === 'ai') {
    bubble.classList.add('bubble-markdown');
    bubble.innerHTML = renderMarkdown(displayContent);
    addCopyButtons(bubble);
  } else {
    bubble.textContent = displayContent;
  }

  wrapper.appendChild(bubble);

  // ── Action bar (both user and AI messages) ────────────────────────────────
  const actions = document.createElement('div');
  actions.className = 'msg-actions';

  // Copy button
  const copyBtn = document.createElement('button');
  copyBtn.className = 'msg-action-btn';
  copyBtn.title     = 'Copy to clipboard';
  copyBtn.textContent = '⎘';
  copyBtn.onclick = () => {
    navigator.clipboard.writeText(content).then(() => {
      copyBtn.textContent = '✓';
      copyBtn.style.color = '#00e896';
      setTimeout(() => { copyBtn.textContent = '⎘'; copyBtn.style.color = ''; }, 2000);
    });
  };
  actions.appendChild(copyBtn);

  if (role === 'user') {
    // Re-run button on user messages — replaces input and re-sends
    const rerunBtn = document.createElement('button');
    rerunBtn.className   = 'msg-action-btn';
    rerunBtn.title       = 'Re-run this prompt';
    rerunBtn.textContent = '↻';
    rerunBtn.onclick = () => {
      const input = document.getElementById('chat-input');
      if (!input || state.isLoading) return;
      
      // 1. Paste the content
      input.value = content;
      autoResize(input);
      input.focus();
      
      // 2. Automatically send the message
      sendMessage(); 
    };
    actions.appendChild(rerunBtn);
  }

  if (role === 'ai') {
    // Export dropdown — PDF / DOCX / TXT
    const exportWrap = document.createElement('div');
    exportWrap.className = 'export-dropdown';

    const exportBtn = document.createElement('button');
    exportBtn.className = 'msg-action-btn';
    exportBtn.title = 'Download as...';
    exportBtn.textContent = '⬇';
    exportBtn.onclick = (e) => {
      e.stopPropagation();
      // Close any other open export menus first
      document.querySelectorAll('.export-menu.open').forEach(m => {
        if (m !== menu) m.classList.remove('open');
      });
      menu.classList.toggle('open');
    };

    const menu = document.createElement('div');
    menu.className = 'export-menu';

    const exportOptions = [
      { label: 'PDF',  ext: 'pdf',  fn: exportAsPDF },
      { label: 'DOCX', ext: 'docx', fn: exportAsDOCX },
      { label: 'TXT',  ext: 'txt',  fn: exportAsTXT },
    ];
    exportOptions.forEach(opt => {
      const item = document.createElement('button');
      item.className = 'export-menu-item';
      item.textContent = opt.label;
      item.onclick = (e) => {
        e.stopPropagation();
        menu.classList.remove('open');
        try {
          opt.fn(content);
          showToast(`Exporting ${opt.label}...`);
        } catch (err) {
          showToast(`Export failed: ${err.message || 'unknown error'}`);
        }
      };
      menu.appendChild(item);
    });

    exportWrap.appendChild(exportBtn);
    exportWrap.appendChild(menu);
    actions.appendChild(exportWrap);

    // Thumbs up
    const upBtn = document.createElement('button');
    upBtn.className   = 'msg-action-btn';
    upBtn.title       = 'Good response';
    upBtn.textContent = '👍';
    upBtn.onclick = () => {
      upBtn.style.color = '#00e896';
      downBtn.style.color = '';
      showToast('Feedback noted ✓');
    };
    // Thumbs down
    const downBtn = document.createElement('button');
    downBtn.className   = 'msg-action-btn';
    downBtn.title       = 'Bad response';
    downBtn.textContent = '👎';
    downBtn.onclick = () => {
      downBtn.style.color = '#ff4444';
      upBtn.style.color = '';
      showToast('Feedback noted ✓');
    };
    actions.appendChild(upBtn);
    actions.appendChild(downBtn);
  }

  wrapper.appendChild(actions);

  // ── Meta row (AI only) ────────────────────────────────────────────────────
  if (role === 'ai') {
    const meta = document.createElement('div');
    meta.className = 'message-meta';

    if (tier) {
      const t = document.createElement('span');
      t.textContent = `${tier}${modelsCalled?.length ? ` · ${modelsCalled.join(', ')}` : ''}`;
      meta.appendChild(t);
    }

    const pb = document.createElement('span');
    if (personalized === false) {
      pb.textContent = '◇ generic';
      pb.style.cssText = 'color:#4a6478;font-size:9px;';
    } else {
      pb.textContent = '✦ personalized';
      pb.style.cssText = 'color:rgba(0,212,255,0.5);font-size:9px;';
    }
    meta.appendChild(pb);

    wrapper.appendChild(meta);
  }

  // ── Generated PDF file card (pdf_creator skill) ────────────────────────────
  if (role === 'ai' && generatedFile && generatedFile.url) {
    wrapper.appendChild(buildGeneratedFileCard(generatedFile));
  }

  msgs.appendChild(wrapper);
  msgs.scrollTop = msgs.scrollHeight;
}

function buildGeneratedFileCard(file) {
  const card = document.createElement('div');
  card.className = 'generated-file-card';

  const header = document.createElement('div');
  header.className = 'generated-file-header';

  const icon = document.createElement('span');
  icon.className = 'generated-file-icon';
  icon.textContent = '📄';

  const info = document.createElement('div');
  info.className = 'generated-file-info';

  const name = document.createElement('div');
  name.className = 'generated-file-name';
  name.textContent = file.filename; // textContent — XSS safe

  const sub = document.createElement('div');
  sub.className = 'generated-file-sub';
  const sizeKb = file.size ? `${Math.max(1, Math.round(file.size / 1024))} KB` : '';
  sub.textContent = [sizeKb, file.theme ? `${file.theme} theme` : ''].filter(Boolean).join(' · ');

  info.appendChild(name);
  info.appendChild(sub);

  const downloadBtn = document.createElement('a');
  downloadBtn.className = 'generated-file-download';
  downloadBtn.href = file.url;
  downloadBtn.download = file.filename;
  downloadBtn.title = 'Download PDF';
  downloadBtn.textContent = '⬇ Download';

  header.appendChild(icon);
  header.appendChild(info);
  header.appendChild(downloadBtn);
  card.appendChild(header);

  // Inline preview — collapsible to avoid pushing the conversation around by default
  const toggle = document.createElement('button');
  toggle.className = 'generated-file-toggle';
  toggle.textContent = 'Show preview';
  toggle.type = 'button';

  const previewWrap = document.createElement('div');
  previewWrap.className = 'generated-file-preview';
  previewWrap.style.display = 'none';

  let loaded = false;
  toggle.onclick = () => {
    const showing = previewWrap.style.display !== 'none';
    if (showing) {
      previewWrap.style.display = 'none';
      toggle.textContent = 'Show preview';
    } else {
      if (!loaded) {
        const iframe = document.createElement('iframe');
        iframe.src = file.url;
        iframe.title = file.filename;
        previewWrap.appendChild(iframe);
        loaded = true;
      }
      previewWrap.style.display = 'block';
      toggle.textContent = 'Hide preview';
    }
  };

  card.appendChild(toggle);
  card.appendChild(previewWrap);

  return card;
}

function addThinking() {
  const id   = `think-${Date.now()}`;
  const msgs = document.getElementById('messages');
  const wrap = document.createElement('div');
  wrap.className = 'message message-ai';
  wrap.id = id;
  const ind = document.createElement('div');
  ind.className = 'thinking-indicator';
  for (let i = 0; i < 3; i++) {
    const d = document.createElement('div');
    d.className = 'thinking-dot';
    ind.appendChild(d);
  }
  wrap.appendChild(ind);
  msgs.appendChild(wrap);
  msgs.scrollTop = msgs.scrollHeight;
  return id;
}

function removeThinking(id) {
  document.getElementById(id)?.remove();
}

function renderMessages() {
  const msgs = document.getElementById('messages');
  msgs.innerHTML = '';
  
  state.messages.forEach(m => {
    const content = (typeof m.content === 'string') ? m.content : String(m.content || '');
    
    // Normalize the API's 'assistant' role to match your UI's 'ai' role
    const uiRole = (m.role === 'assistant') ? 'ai' : m.role;
    
    addMessage(uiRole, content, m.tier, m.modelsUsed, m.modelsCalled, m.personalized, m.prompt);
  });
}

function updateModelResponses(responses) {
  const panel = document.getElementById('model-responses');
  panel.innerHTML = '';

  if (!responses.length) {
    const e = document.createElement('div');
    e.className = 'panel-empty';
    e.textContent = 'No model responses yet.';
    panel.appendChild(e);
    return;
  }

  responses.forEach(r => {
    const card = document.createElement('div');
    card.className = 'model-response-card';
    card.style.borderLeftColor = MODEL_COLORS[r.model] || '#444';

    const header = document.createElement('div');
    header.className = 'model-response-header';

    const name = document.createElement('div');
    name.className = 'model-response-name';
    name.style.color = MODEL_COLORS[r.model] || '#888';
    name.textContent = r.model.toUpperCase(); // textContent — XSS safe

    header.appendChild(name);
    card.appendChild(header);

    if (r.error) {
      const err = document.createElement('div');
      err.className = 'model-error';
      err.textContent = r.error; // textContent — XSS safe
      card.appendChild(err);
    } else {
      const text = document.createElement('div');
      text.className = 'model-response-text bubble-markdown';
      text.innerHTML = renderMarkdown(r.response || '');
      addCopyButtons(text);
      card.appendChild(text);
    }

    panel.appendChild(card);
  });
}

// ── Tier ──────────────────────────────────────────────────────────────────────
function setTier(tier) {
  state.selectedTier = tier;
  document.querySelectorAll('.tier-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.tier === tier));
  const labels = {
    auto:  'Auto routing',
    tier1: 'Quick — 1 model',
    tier2: 'Balanced — 2 models',
    tier3: 'Deep — all models'
  };
  setText('tier-display', labels[tier] || 'Auto routing');
}

// ── Model Pin Selector ────────────────────────────────────────────────────────

const MODEL_DISPLAY_NAMES = {
  gemini:     'Gemini 2.0 Flash',
  groq:       'Groq · Llama 3.3',
  cerebras:   'Cerebras · Llama 3.3',
  nvidia:     'NVIDIA NIM',
  deepseek:   'DeepSeek (OpenRouter)',
  mistral:    'Mistral (OpenRouter)',
};

async function populateModelPinDropdown(settingsData) {
  const select = document.getElementById('model-pin-select');
  if (!select) return;

  // Reset to loading state
  while (select.options.length > 1) select.remove(1);
  const loading = document.createElement('option');
  loading.disabled = true;
  loading.textContent = 'Loading models...';
  select.appendChild(loading);

  try {
    const data = await secureFetch('/api/models/available');
    const models = data.models || [];

    // Clear loading option
    while (select.options.length > 1) select.remove(1);

    if (!models.length) {
      const empty = document.createElement('option');
      empty.disabled = true;
      empty.textContent = 'No models available — check API keys';
      select.appendChild(empty);
      return;
    }

    // Group by provider
    const PROVIDER_ORDER = ['groq', 'cerebras', 'gemini', 'nvidia', 'openrouter', 'ollama'];
    const grouped = {};
    models.forEach(m => {
      if (!grouped[m.provider]) grouped[m.provider] = [];
      grouped[m.provider].push(m);
    });

    const PROVIDER_LABELS = {
      groq:       '⚡ Groq',
      cerebras:   '⚡ Cerebras',
      gemini:     'Gemini',
      nvidia:     'NVIDIA NIM',
      openrouter: 'OpenRouter',
      ollama:     '🖥 Local / LAN',
    };

    // Add optgroups per provider
    PROVIDER_ORDER.forEach(provider => {
      const pModels = grouped[provider];
      if (!pModels?.length) return;

      const group = document.createElement('optgroup');
      group.label = PROVIDER_LABELS[provider] || provider;

      pModels.forEach(m => {
        const opt = document.createElement('option');
        opt.value = JSON.stringify({ provider: m.provider, modelId: m.id });
        opt.textContent = m.id;
        group.appendChild(opt);
      });

      select.appendChild(group);
    });

    // Add any remaining providers not in the order list
    Object.keys(grouped).forEach(provider => {
      if (!PROVIDER_ORDER.includes(provider)) {
        const group = document.createElement('optgroup');
        group.label = provider;
        grouped[provider].forEach(m => {
          const opt = document.createElement('option');
          opt.value = JSON.stringify({ provider: m.provider, modelId: m.id });
          opt.textContent = m.id;
          group.appendChild(opt);
        });
        select.appendChild(group);
      }
    });

  } catch (e) {
    // Clear loading option, show error
    while (select.options.length > 1) select.remove(1);
    const err = document.createElement('option');
    err.disabled = true;
    err.textContent = 'Failed to load models';
    select.appendChild(err);
    console.error('Model listing failed:', e.message);
  }
}

function toggleModelPin(checkbox) {
  const select    = document.getElementById('model-pin-select');
  const label     = document.getElementById('model-pin-label');
  const tierSel   = document.querySelector('.tier-selector');

  if (checkbox.checked) {
    // Show dropdown, dim tier buttons
    select.classList.remove('hidden');
    select.value = '';
    state.pinnedModel = null;
    label.textContent = 'Pin:';
    label.className   = 'model-pin-label pinned';
    tierSel?.classList.add('pinned');
    setText('tier-display', 'Pinned model mode');
  } else {
    // Hide dropdown, restore auto routing
    select.classList.add('hidden');
    state.pinnedModel = null;
    label.textContent = 'Auto';
    label.className   = 'model-pin-label';
    tierSel?.classList.remove('pinned');
    updateTierDisplay();
  }
}

function selectPinnedModel(rawValue) {
  const label = document.getElementById('model-pin-label');
  if (!rawValue) {
    state.pinnedModel = null;
    label.textContent = 'Pin:';
    setText('tier-display', 'Pinned model mode — select a model');
    return;
  }
  try {
    const { provider, modelId } = JSON.parse(rawValue);
    state.pinnedModel = { provider, modelId };
    label.textContent = modelId.split('/').pop().split('-').slice(0,3).join('-');
    setText('tier-display', `Pinned: ${modelId}`);
    setText('models-display', `1 model · ${provider}`);

    // Warn if large model on free tier — these can take 30-120 seconds
    const m = modelId.toLowerCase();
    const isLarge = m.includes('550b') || m.includes('405b') || m.includes('141b') ||
                    m.includes('ultra') || m.includes('super') || m.includes('70b') ||
                    m.includes('72b') || m.includes('671b');
    if (isLarge && modelId.endsWith(':free')) {
      showToast(`⚠ ${modelId} is a large model on free tier — responses may take 30–120 seconds. Be patient!`);
    } else {
      showToast(`Pinned to ${modelId}`);
    }
  } catch(e) {
    state.pinnedModel = null;
  }
}

function updateTierDisplay() {
  if (state.pinnedModel) {
    setText('tier-display', `Pinned: ${state.pinnedModel.modelId || state.pinnedModel}`);
  } else {
    const labels = {
      auto: 'Auto routing', tier1: 'Quick — 1 model',
      tier2: 'Balanced — 2 models', tier3: 'Deep — all models'
    };
    setText('tier-display', labels[state.selectedTier] || 'Auto routing');
  }
}

// ── Personalization toggle ────────────────────────────────────────────────────
function togglePersonalization(checkbox) {
  state.personalized = checkbox.checked;

  const label = document.getElementById('persona-label');
  const hint  = document.getElementById('persona-hint');

  if (state.personalized) {
    label.textContent = '✦ Personalized';
    label.className   = 'persona-label persona-on';
    hint.textContent  = 'Profile + memory';
    hint.className    = 'persona-hint';
  } else {
    label.textContent = '◇ Generalized';
    label.className   = 'persona-label persona-off';
    hint.textContent  = 'No profile context';
    hint.className    = 'persona-hint off';
  }
  updateInputPlaceholder();
}

function updateInputPlaceholder() {
  const input = document.getElementById('chat-input');
  if (!input) return;
  const pinLabel = state.pinnedModel
    ? state.pinnedModel.modelId?.split('/').pop() || state.pinnedModel.modelId
    : null;
  input.placeholder = pinLabel
    ? `Message NeuConX... (${pinLabel})`
    : state.personalized
      ? 'Message NeuConX...'
      : 'Message NeuConX... (generic mode)';
}

// ── Save conversation ─────────────────────────────────────────────────────────
async function saveCurrentConversation() {
  if (!state.messages.length) return;
  try {
    const title = state.messages[0]?.content?.slice(0, 50) || 'Conversation';
    const data  = await secureFetch('/api/conversations', {
      method: 'POST',
      body: JSON.stringify({
        id:         state.currentConvId,
        title,
        messages:   state.messages,
        created_at: new Date().toISOString()
      })
    });
    if (data.id && !state.currentConvId) {
      state.currentConvId = data.id;
      setText('current-conv-title', title);
      await loadConversations();
      highlightConv(data.id);
    }
  } catch (e) {
    console.error('Save conversation failed:', e.message);
  }
}

// ── Right panel ───────────────────────────────────────────────────────────────
function toggleRightPanel() {
  document.getElementById('right-panel').classList.toggle('hidden');
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function showToast(msg) {
  const t = document.createElement('div');
  t.style.cssText = `
    position:fixed;bottom:24px;left:50%;transform:translateX(-50%);
    background:#1a2530;border:1px solid #1e2d3d;color:#c8d6e5;
    padding:8px 18px;border-radius:20px;font-size:12px;
    font-family:'JetBrains Mono',monospace;z-index:9999;
    animation:fadeUp .25s ease;
  `;
  t.textContent = msg; // textContent — XSS safe
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}

// ── Utility ───────────────────────────────────────────────────────────────────
function formatDate(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('en-CA', { month: 'short', day: 'numeric' });
  } catch { return ''; }
}

// ── Onboarding ────────────────────────────────────────────────────────────────
let obStep = 0;

function showObStep(n) {
  const total    = OB_STEPS.length - 1;
  const pct      = (n / total) * 100;
  document.getElementById('onboarding-fill').style.width = `${pct}%`;
  setText('onboarding-step-label', `${n} / ${total}`);

  const step = OB_STEPS[n];
  if (n === 0) {
    setText('ob-title', 'Welcome to NeuConX');
    document.getElementById('ob-question-wrap').classList.add('hidden');
    document.getElementById('ob-back').classList.add('hidden');
    setText('ob-next', 'Get Started →');
  } else {
    setText('ob-title', `${n}. ${step.section}`);
    document.getElementById('ob-question-wrap').classList.remove('hidden');
    setText('ob-question', step.question);
    document.getElementById('ob-answer').value = state.onboardingAnswers[step.section.toLowerCase()] || '';
    document.getElementById('ob-back').classList.remove('hidden');
    setText('ob-next', n === total ? 'Complete ✓' : 'Next →');
  }
}

function onboardingNext() {
  if (obStep === 0) { obStep = 1; showObStep(1); return; }

  const ans = document.getElementById('ob-answer')?.value.trim() || '';
  if (!ans) {
    const ta = document.getElementById('ob-answer');
    ta.style.borderColor = 'rgba(255,68,68,0.5)';
    setTimeout(() => { ta.style.borderColor = ''; }, 1500);
    return;
  }

  state.onboardingAnswers[OB_STEPS[obStep].section.toLowerCase()] = ans;

  if (obStep < OB_STEPS.length - 1) { obStep++; showObStep(obStep); }
  else completeOnboarding();
}

function onboardingBack() {
  if (obStep > 1) { obStep--; showObStep(obStep); }
}

async function completeOnboarding() {
  try {
    await secureFetch('/api/profile', {
      method: 'POST',
      body: JSON.stringify(state.onboardingAnswers)
    });
  } catch (e) {
    console.error('Profile save failed:', e.message);
  }
  document.getElementById('onboarding-overlay').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  await Promise.all([loadConversations(), loadSkills(), loadSettings()]);
}

// Init onboarding if visible
if (!document.getElementById('onboarding-overlay')?.classList.contains('hidden')) {
  showObStep(0);
}


// ── Phase 5: RAG Memory Search ────────────────────────────────────────────────

let ragStatus = { available: false, count: 0 };

async function checkRAGStatus() {
  try {
    const data = await secureFetch('/api/memory/status');
    ragStatus = { available: data.rag_available, count: data.embeddings_count };
    updateRAGIndicator();
  } catch(e) {}
}

function updateRAGIndicator() {
  const memBtn = document.querySelector('.icon-btn[onclick="clearMemory()"]');
  if (memBtn && ragStatus.available) {
    memBtn.textContent = `🧠 Memory (${ragStatus.count} stored)`;
  }
}

async function openMemorySearch() {
  const existing = document.getElementById('memory-search-modal');
  if (existing) { existing.remove(); return; }

  const modal = document.createElement('div');
  modal.id = 'memory-search-modal';
  modal.className = 'modal';
  modal.style.zIndex = '1100';

  const card = document.createElement('div');
  card.className = 'modal-card';
  card.style.maxWidth = '600px';

  card.innerHTML = `
    <div class="modal-header">
      <h3>🔍 Memory Search</h3>
      <button class="modal-close" onclick="document.getElementById('memory-search-modal')?.remove()">×</button>
    </div>
    <p style="font-size:11px;color:var(--text-dim);margin-bottom:14px;">
      ${ragStatus.available 
        ? `Semantic search across ${ragStatus.count} stored messages.` 
        : '⚠️ ChromaDB not installed. Install with: pip install chromadb sentence-transformers'}
    </p>
    <div class="input-row" style="margin-bottom:14px;">
      <input id="mem-search-input" class="settings-input" placeholder="Search your conversation history..." 
        style="flex:1;" onkeydown="if(event.key==='Enter') searchMemory()">
      <button class="btn-primary" onclick="searchMemory()" style="padding:8px 16px;font-size:12px;">Search</button>
    </div>
    <div id="mem-search-results" style="display:flex;flex-direction:column;gap:8px;max-height:400px;overflow-y:auto;"></div>
  `;

  modal.appendChild(card);
  document.body.appendChild(modal);
  modal.addEventListener('click', e => { if(e.target===modal) modal.remove(); });
  document.getElementById('mem-search-input')?.focus();
}

async function searchMemory() {
  const query   = document.getElementById('mem-search-input')?.value.trim();
  const results = document.getElementById('mem-search-results');
  if (!query || !results) return;

  results.innerHTML = '<div style="font-size:11px;color:var(--text-dim);text-align:center;padding:20px;">Searching...</div>';

  try {
    const data = await secureFetch('/api/memory/search', {
      method: 'POST',
      body: JSON.stringify({ query, n: 8 })
    });

    results.innerHTML = '';
    if (!data.results?.length) {
      results.innerHTML = '<div style="font-size:11px;color:var(--text-dim);text-align:center;padding:20px;">No relevant memories found.</div>';
      return;
    }

    data.results.forEach(r => {
      const card = document.createElement('div');
      card.style.cssText = 'background:var(--surface2);border-radius:8px;padding:10px 12px;border-left:2px solid;';
      card.style.borderLeftColor = r.role === 'user' ? 'var(--cyan)' : 'var(--green)';

      const meta = document.createElement('div');
      meta.style.cssText = 'font-size:9px;color:var(--text-dim);margin-bottom:4px;display:flex;justify-content:space-between;';
      const relPct = Math.round(r.relevance * 100);
      meta.innerHTML = `<span>${r.role} · ${r.timestamp?.slice(0,10) || 'unknown date'}</span><span style="color:${relPct>70?'var(--green)':'var(--text-dim)'};">${relPct}% match</span>`;

      const content = document.createElement('div');
      content.style.cssText = 'font-size:11px;color:var(--text-mid);line-height:1.5;';
      content.textContent = r.content;

      card.appendChild(meta);
      card.appendChild(content);
      results.appendChild(card);
    });
  } catch(e) {
    results.innerHTML = `<div style="font-size:11px;color:var(--red);text-align:center;padding:20px;">${e.message}</div>`;
  }
}


// ── Phase 6: Memory Confirmation UI ──────────────────────────────────────────

async function checkMemoryCandidates() {
  try {
    const data = await secureFetch('/api/memory/candidates');
    const pending = data.pending || [];
    if (pending.length > 0) {
      showMemoryCandidates(pending);
    }
  } catch(e) {}
}

function showMemoryCandidates(candidates) {
  const existing = document.getElementById('memory-candidates-bar');
  if (existing) existing.remove();

  const bar = document.createElement('div');
  bar.id = 'memory-candidates-bar';
  bar.style.cssText = `
    position:fixed;bottom:20px;right:20px;z-index:900;
    background:var(--surface);border:1px solid rgba(0,232,150,.3);
    border-radius:12px;padding:14px 16px;max-width:300px;
    box-shadow:0 8px 32px rgba(0,0,0,.6);animation:fadeUp .3s ease;
    font-family:var(--font-mono);
  `;

  const header = document.createElement('div');
  header.style.cssText = 'font-size:11px;color:var(--green);font-weight:600;margin-bottom:10px;display:flex;align-items:center;gap:6px;';
  header.innerHTML = '🧠 <span>Remember these?</span>';

  const closeBtn = document.createElement('button');
  closeBtn.style.cssText = 'background:none;border:none;color:var(--text-dim);cursor:pointer;font-size:14px;margin-left:auto;';
  closeBtn.textContent = '×';
  closeBtn.addEventListener('click', () => bar.remove());
  header.appendChild(closeBtn);
  bar.appendChild(header);

  candidates.slice(0, 3).forEach(c => {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:6px;';
    row.id = `candidate-${c.id}`;

    const fact = document.createElement('span');
    fact.style.cssText = 'flex:1;font-size:10px;color:var(--text-mid);line-height:1.4;';
    fact.textContent = c.fact;

    const confirmBtn = document.createElement('button');
    confirmBtn.style.cssText = 'background:rgba(0,232,150,.15);border:1px solid rgba(0,232,150,.3);color:var(--green);border-radius:6px;padding:2px 8px;font-size:10px;cursor:pointer;flex-shrink:0;';
    confirmBtn.textContent = '✓';
    confirmBtn.title = 'Remember this';
    confirmBtn.addEventListener('click', () => confirmCandidate(c.id));

    const rejectBtn = document.createElement('button');
    rejectBtn.style.cssText = 'background:rgba(255,68,68,.1);border:1px solid rgba(255,68,68,.2);color:var(--red);border-radius:6px;padding:2px 8px;font-size:10px;cursor:pointer;flex-shrink:0;';
    rejectBtn.textContent = '✗';
    rejectBtn.title = 'Forget this';
    rejectBtn.addEventListener('click', () => rejectCandidate(c.id));

    row.appendChild(fact);
    row.appendChild(confirmBtn);
    row.appendChild(rejectBtn);
    bar.appendChild(row);
  });

  if (candidates.length > 3) {
    const more = document.createElement('div');
    more.style.cssText = 'font-size:9px;color:var(--text-dim);margin-top:4px;text-align:right;';
    more.textContent = `+${candidates.length - 3} more`;
    bar.appendChild(more);
  }

  document.body.appendChild(bar);
  setTimeout(() => bar?.remove(), 15000); // Auto-dismiss after 15s
}

async function confirmCandidate(id) {
  try {
    await secureFetch(`/api/memory/candidates/${id}/confirm`, { method: 'POST' });
    document.getElementById(`candidate-${id}`)?.remove();
    showToast('✓ Remembered');
  } catch(e) {}
}

async function rejectCandidate(id) {
  try {
    await secureFetch(`/api/memory/candidates/${id}/reject`, { method: 'POST' });
    document.getElementById(`candidate-${id}`)?.remove();
  } catch(e) {}
}

// ── Phase 7: Profile viewer ────────────────────────────────────────────────────

async function openProfileViewer() {
  try {
    const data = await secureFetch('/api/profile/learned');
    const existing = document.getElementById('profile-modal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'profile-modal';
    modal.className = 'modal';
    modal.style.zIndex = '1100';

    const card = document.createElement('div');
    card.className = 'modal-card';
    card.style.maxWidth = '560px';

    const facts = data.learned_facts || [];
    const ob    = data.onboarding || {};

    card.innerHTML = `
      <div class="modal-header">
        <h3>👤 My Profile</h3>
        <button class="modal-close" onclick="document.getElementById('profile-modal')?.remove()">×</button>
      </div>
      <div style="display:flex;flex-direction:column;gap:16px;max-height:500px;overflow-y:auto;">
        <div>
          <div style="font-size:10px;color:var(--cyan);font-weight:600;letter-spacing:1px;text-transform:uppercase;margin-bottom:8px;">Onboarding Answers</div>
          ${Object.entries(ob).map(([k, v]) => `
            <div style="background:var(--surface2);border-radius:8px;padding:8px 12px;margin-bottom:6px;">
              <div style="font-size:9px;color:var(--text-dim);margin-bottom:3px;">${k.replace(/_/g,' ')}</div>
              <div style="font-size:11px;color:var(--text-mid);">${typeof v === 'string' ? v : JSON.stringify(v)}</div>
            </div>
          `).join('') || '<div style="font-size:11px;color:var(--text-dim);">No onboarding data yet.</div>'}
        </div>
        <div>
          <div style="font-size:10px;color:var(--green);font-weight:600;letter-spacing:1px;text-transform:uppercase;margin-bottom:8px;">
            AI-Learned Facts (${facts.length})
          </div>
          <div id="learned-facts-list">
            ${facts.map((f, i) => `
              <div style="display:flex;align-items:center;gap:8px;background:var(--surface2);border-radius:8px;padding:8px 12px;margin-bottom:6px;" id="fact-${i}">
                <span style="font-size:11px;color:var(--text-mid);flex:1;">${f}</span>
                <button onclick="deleteLearnedFact(${i})" style="background:none;border:none;color:var(--text-dim);cursor:pointer;font-size:13px;" title="Forget this">×</button>
              </div>
            `).join('') || '<div style="font-size:11px;color:var(--text-dim);">No learned facts yet. Chat more to build your profile!</div>'}
          </div>
        </div>
      </div>
    `;

    modal.appendChild(card);
    document.body.appendChild(modal);
    modal.addEventListener('click', e => { if(e.target===modal) modal.remove(); });
  } catch(e) {
    showToast('Failed to load profile: ' + e.message);
  }
}

async function deleteLearnedFact(idx) {
  try {
    await secureFetch(`/api/profile/learned/${idx}`, { method: 'DELETE' });
    document.getElementById(`fact-${idx}`)?.remove();
    showToast('Fact removed from memory');
  } catch(e) {
    showToast('Failed to delete: ' + e.message);
  }
}

// ── Reset Functions ────────────────────────────────────────────────────────────

function showResetMsg(text, isError = false) {
  const el = document.getElementById('reset-msg');
  if (!el) return;
  el.textContent = text;
  el.className = `settings-msg ${isError ? 'error' : 'success'}`;
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 4000);
}

async function resetOnboarding() {
  if (!confirm('Reset onboarding? You\'ll redo the 7-step setup on next page load.')) return;
  try {
    const d = await secureFetch('/api/reset/onboarding', { method: 'POST' });
    showResetMsg('✓ ' + d.message);
    setTimeout(() => location.reload(), 1500);
  } catch(e) { showResetMsg('✗ ' + e.message, true); }
}

async function resetSessionMemory() {
  try {
    const d = await secureFetch('/api/reset/memory', { method: 'POST' });
    state.messages = [];
    showResetMsg('✓ ' + d.message);
    showToast('Session memory cleared');
  } catch(e) { showResetMsg('✗ ' + e.message, true); }
}

async function resetConversations() {
  if (!confirm('Delete ALL conversations permanently? This cannot be undone.')) return;
  try {
    const d = await secureFetch('/api/reset/conversations', { method: 'POST' });
    showResetMsg('✓ ' + d.message);
    newChat();
    await loadConversations();
    showToast(d.message);
  } catch(e) { showResetMsg('✗ ' + e.message, true); }
}

async function resetLearnedProfile() {
  if (!confirm('Delete all AI-learned facts? Your onboarding answers are kept.')) return;
  try {
    const d = await secureFetch('/api/reset/profile', { method: 'POST' });
    showResetMsg('✓ ' + d.message);
    showToast('Learned profile cleared');
  } catch(e) { showResetMsg('✗ ' + e.message, true); }
}

async function resetAPIKeys() {
  if (!confirm('Remove all API keys from .env? You\'ll need to re-enter them.')) return;
  try {
    const d = await secureFetch('/api/reset/keys', { method: 'POST' });
    showResetMsg('✓ ' + d.message);
    await loadSettings();
    showToast('API keys wiped');
  } catch(e) { showResetMsg('✗ ' + e.message, true); }
}

async function factoryReset() {
  if (!confirm('☢ FULL FACTORY RESET\n\nThis will permanently delete:\n• All conversations\n• Your profile & onboarding\n• All API keys\n• Session memory\n\nAre you absolutely sure?')) return;
  if (!confirm('Last chance — this cannot be undone. Continue?')) return;
  try {
    const d = await secureFetch('/api/reset/factory', { method: 'POST' });
    showResetMsg('✓ ' + d.message);
    showToast('Factory reset complete — reloading...');
    setTimeout(() => location.reload(), 2000);
  } catch(e) { showResetMsg('✗ ' + e.message, true); }
}

// ── Feature 1: Settings Tab Switching ─────────────────────────────────────────
function switchSettingsTab(tab, btn) {
  document.querySelectorAll('.stab-content').forEach(el => {
    el.classList.remove('active');
    el.classList.add('hidden');
  });
  document.querySelectorAll('.stab').forEach(b => b.classList.remove('active'));
  const el = document.getElementById('stab-' + tab);
  if (el) { el.classList.add('active'); el.classList.remove('hidden'); }
  if (btn) btn.classList.add('active');
  // Load models for judge dropdown when engine tab opened
  if (tab === 'engine') loadJudgeModels();
}

// ── Feature 1: API Key Validation ─────────────────────────────────────────────
async function validateKey(provider) {
  const input  = document.getElementById(provider + '-key');
  const badge  = document.getElementById(provider + '-val-count');
  const btn    = document.querySelector(`button[onclick="validateKey('${provider}')"]`);
  if (!input || !badge) return;

  const key = input.value.trim();
  if (!key) { showToast('Enter an API key first'); return; }

  btn?.classList.add('loading');
  btn && (btn.textContent = '...');
  badge.className = 'val-count hidden';

  try {
    const data = await secureFetch('/api/keys/validate', {
      method: 'POST',
      body: JSON.stringify({ provider, key })
    });

    badge.classList.remove('hidden');
    if (data.valid) {
      const models = data.models || [];
      badge.className = 'val-count';
      badge.textContent = `${data.count} models`;
      // Tooltip: show model list on hover
      badge.title = models.slice(0,30).join('\n') + (models.length > 30 ? `\n...+${models.length-30} more` : '');
    } else {
      badge.className = 'val-count error';
      badge.textContent = data.error || 'Invalid';
      badge.title = data.error || '';
    }
  } catch(e) {
    badge.classList.remove('hidden');
    badge.className = 'val-count error';
    badge.textContent = 'Error';
    badge.title = e.message;
  } finally {
    btn?.classList.remove('loading');
    btn && (btn.textContent = 'Validate');
  }
}

function clearValidation(provider) {
  const badge = document.getElementById(provider + '-val-count');
  if (badge) badge.className = 'val-count hidden';
}

// ── Feature 5: Ollama validation ──────────────────────────────────────────────
async function validateOllama() {
  const urlEl    = document.getElementById('ollama-url');
  const result   = document.getElementById('ollama-val-result');
  if (!result) return;

  result.className = 'val-count';
  result.textContent = '...';
  result.classList.remove('hidden');

  try {
    const data = await secureFetch('/api/keys/validate', {
      method: 'POST',
      body: JSON.stringify({
        provider: 'ollama',
        key: 'local',
        base_url: urlEl?.value || 'http://localhost:11434'
      })
    });

    if (data.valid) {
      result.className = 'val-count';
      result.textContent = `✓ Connected · ${data.count} model${data.count !== 1 ? 's' : ''}`;
      result.title = (data.models || []).join('\n');
    } else {
      result.className = 'val-count error';
      result.textContent = '✗ ' + (data.error || 'Connection failed');
    }
  } catch(e) {
    result.className = 'val-count error';
    result.textContent = '✗ ' + e.message;
  }
}

// ── Feature 4: Merge Engine toggle + Judge ────────────────────────────────────
function toggleMergeEngine(checkbox) {
  const judgeConfig = document.getElementById('judge-config');
  if (judgeConfig) {
    judgeConfig.classList.toggle('hidden', checkbox.checked);
  }
  if (!checkbox.checked) {
    loadJudgeModels();
  }
}

async function loadJudgeModels() {
  const select = document.getElementById('judge-model-select');
  if (!select) return;

  // Get current judge provider
  const provider = document.getElementById('judge-provider-select')?.value || 'openrouter';
  updateJudgeProvider(provider);
}

async function updateJudgeProvider(provider) {
  const modelRow = document.getElementById('judge-model-row');
  const select   = document.getElementById('judge-model-select');
  if (!select) return;

  if (provider === 'ollama') {
    if (modelRow) modelRow.style.display = 'flex';
    select.innerHTML = '<option value="">Using default Ollama model from Local tab</option>';
    return;
  }

  // Fetch live models for this provider
  if (modelRow) modelRow.style.display = 'flex';
  select.innerHTML = '<option>Loading...</option>';

  try {
    const data = await secureFetch('/api/models/available');
    const models = (data.models || []).filter(m => m.provider === provider);
    select.innerHTML = models.length
      ? models.map(m => `<option value="${m.id}">${m.id}</option>`).join('')
      : '<option value="">— no models found, check API key —</option>';
  } catch(e) {
    select.innerHTML = '<option value="">Error loading models</option>';
  }
}

async function saveEngineSettings() {
  const enabled  = document.getElementById('merge-engine-toggle')?.checked ?? true;
  const provider = document.getElementById('judge-provider-select')?.value || 'groq';
  const model    = document.getElementById('judge-model-select')?.value || '';
  const msgEl    = document.getElementById('engine-msg');

  try {
    await secureFetch('/api/neuconx-settings', {
      method: 'POST',
      body: JSON.stringify({
        merge_engine_enabled: enabled,
        judge_provider:       provider,
        judge_model:          model
      })
    });
    if (msgEl) {
      msgEl.textContent = '✓ Engine settings saved';
      msgEl.className = 'settings-msg success';
      msgEl.classList.remove('hidden');
      setTimeout(() => msgEl.classList.add('hidden'), 3000);
    }
    showToast(enabled ? 'Merge engine enabled' : `AI Judge: ${provider}`);
  } catch(e) {
    if (msgEl) {
      msgEl.textContent = '✗ ' + e.message;
      msgEl.className = 'settings-msg error';
      msgEl.classList.remove('hidden');
    }
  }
}

// Load engine settings when settings modal opens
async function loadEngineSettings() {
  try {
    const data = await secureFetch('/api/neuconx-settings');
    const toggle = document.getElementById('merge-engine-toggle');
    const freeToggle = document.getElementById('free-models-toggle');
    const judgeConfig = document.getElementById('judge-config');
    const providerSel = document.getElementById('judge-provider-select');

    if (toggle) toggle.checked = data.merge_engine_enabled !== false;
    if (freeToggle) freeToggle.checked = data.free_models_only !== false;
    if (judgeConfig) judgeConfig.classList.toggle('hidden', data.merge_engine_enabled !== false);
    if (providerSel && data.judge_provider) providerSel.value = data.judge_provider;
  } catch(e) {}
}

// Load Ollama settings
async function loadLocalSettings() {
  const settings = await secureFetch('/api/settings').catch(() => ({}));
  const urlEl   = document.getElementById('ollama-url');
  const modelEl = document.getElementById('ollama-model');
  if (urlEl && settings.ollama_base_url) urlEl.value = settings.ollama_base_url;
  if (modelEl && settings.ollama_model)  modelEl.value = settings.ollama_model;
}




// ── Free Models Only toggle ───────────────────────────────────────────────────
async function saveFreeModelsToggle(checkbox) {
  const enabled = checkbox.checked;
  try {
    await secureFetch('/api/neuconx-settings', {
      method: 'POST',
      body: JSON.stringify({ free_models_only: enabled })
    });
    showToast(enabled
      ? '🆓 Free Models Only — only free-tier models will be used'
      : '💳 All Models — paid models now available in dropdown'
    );
    // Refresh model dropdown if pin selector is open
    const pinToggle = document.getElementById('model-pin-toggle');
    if (pinToggle?.checked) populateModelPinDropdown({});
    // Refresh model counts in dots
    await fetchModelCounts();
  } catch(e) {
    showToast('Failed to save: ' + e.message);
    checkbox.checked = !enabled; // revert
  }
}

// ── STM Toggle ────────────────────────────────────────────────────────────────
function toggleSTM(module, btn) {
  stmState[module] = !stmState[module];
  btn.classList.toggle('active', stmState[module]);
  const labels = {
    directMode:   stmState.directMode   ? 'Direct ✓'  : 'Direct',
    hedgeReducer: stmState.hedgeReducer ? 'No Hedge ✓' : 'No Hedge',
    casualMode:   stmState.casualMode   ? 'Casual ✓'  : 'Casual',
  };
  btn.textContent = labels[module];
  showToast(stmState[module]
    ? `STM: ${module} ON — applies to new responses`
    : `STM: ${module} OFF`
  );
}

// ── AutoTune — context-adaptive temperature ───────────────────────────────────
// Classifies query context and returns optimal temperature.
// Applied client-side to inform server via payload (server uses it if supported).
const AUTOTUNE_CONTEXTS = {
  code: {
    patterns: [/\bcode\b/i,/\bfunction\b/i,/\bclass\b/i,/\bscript\b/i,
               /\bdebug\b/i,/\bimplement\b/i,/\brefactor\b/i,/\bapi\b/i,
               /\bsql\b/i,/\bbash\b/i,/\bpython\b/i,/\bjavascript\b/i],
    params: { temperature: 0.2, top_p: 0.85 }
  },
  creative: {
    patterns: [/\bwrite\b/i,/\bstory\b/i,/\bpoem\b/i,/\bcreat\b/i,
               /\bimagine\b/i,/\bfiction\b/i,/\bnovel\b/i,/\bessay\b/i,
               /\blyric\b/i,/\bart\b/i],
    params: { temperature: 0.9, top_p: 0.95 }
  },
  analytical: {
    patterns: [/\banalyze\b/i,/\bcompare\b/i,/\bexplain\b/i,/\bwhy\b/i,
               /\bhow does\b/i,/\bresearch\b/i,/\bevaluate\b/i,/\bassess\b/i,
               /\bdifference\b/i,/\bpros and cons\b/i,/\badvantage\b/i],
    params: { temperature: 0.4, top_p: 0.9 }
  },
  conversational: {
    patterns: [/\bhello\b/i,/\bhi\b/i,/\bthanks\b/i,/\bwhat is\b/i,
               /\bwho is\b/i,/\bwhen\b/i,/\bwhere\b/i,/\bquick\b/i],
    params: { temperature: 0.7, top_p: 0.9 }
  }
};

function autoTuneParams(message) {
  const scores = {};
  for (const [ctx, cfg] of Object.entries(AUTOTUNE_CONTEXTS)) {
    scores[ctx] = cfg.patterns.filter(p => p.test(message)).length;
  }
  const best = Object.entries(scores).sort((a,b) => b[1]-a[1])[0];
  if (best[1] === 0) return { temperature: 0.7, top_p: 0.9, context: 'conversational' };
  return { ...AUTOTUNE_CONTEXTS[best[0]].params, context: best[0] };
}

// ── STM Panel toggle ──────────────────────────────────────────────────────────
function toggleSTMPanel() {
  const pills = document.getElementById('stm-pills');
  const btn   = document.getElementById('stm-toggle-btn');
  if (!pills) return;
  const open = pills.classList.toggle('hidden') === false;
  // classList.toggle returns true if class was added (hidden), false if removed (visible)
  const visible = !pills.classList.contains('hidden');
  btn.classList.toggle('active', visible);
}

// Save Ollama / LAN settings
async function saveLocalSettings() {
  const url   = document.getElementById('ollama-url')?.value.trim()   || '';
  const model = document.getElementById('ollama-model')?.value.trim() || '';
  const msgEl = document.getElementById('local-settings-msg');

  try {
    await secureFetch('/api/settings', {
      method: 'POST',
      body: JSON.stringify({
        ollama_base_url: url,
        ollama_model:    model,
        gemini: '', groq: '', cerebras: '', nvidia: '', openrouter: ''
      })
    });
    if (msgEl) {
      msgEl.textContent = '✓ Local model settings saved';
      msgEl.className = 'settings-msg success';
      msgEl.classList.remove('hidden');
      setTimeout(() => msgEl.classList.add('hidden'), 3000);
    }
    showToast('Local model saved');
    await loadSettings();
  } catch(e) {
    if (msgEl) {
      msgEl.textContent = '✗ ' + e.message;
      msgEl.className = 'settings-msg error';
      msgEl.classList.remove('hidden');
    }
  }
}