/**
 * NeuConX — Frontend Application
 * 
 * SECURITY NOTES (Principal Architect):
 * 1. CSRF token read from meta tag (not localStorage — XSS resistant)
 * 2. All user content rendered via textContent (not innerHTML) to prevent XSS
 * 3. No eval(), no Function() — strict content policy
 * 4. API keys never stored in JS or localStorage
 * 5. Fetch calls use credentials: 'same-origin' only
 */

'use strict';

// ── SECURITY: Read CSRF token from meta tag ───────────────────────────────
const getCSRFToken = () => {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute('content') : '';
};

// ── State ─────────────────────────────────────────────────────────────────
const state = {
  currentConvId: null,
  messages: [],
  selectedTier: 'auto',
  activeSkills: new Set(),
  isLoading: false,
  onboardingStep: 0,
  onboardingAnswers: {}
};

// ── Onboarding Data ───────────────────────────────────────────────────────
const ONBOARDING_STEPS = [
  { section: 'Welcome', question: null },
  {
    section: 'Identity',
    question: 'What is your full name and what do people usually call you? Where are you currently based (city, country)?'
  },
  {
    section: 'Education',
    question: 'What is your current education? Any degrees, certifications, or programs you are enrolled in right now?'
  },
  {
    section: 'Career',
    question: 'What do you currently do professionally? Job title, company, years of experience, and main technical skills?'
  },
  {
    section: 'Goals',
    question: 'What are your top 3 goals right now — personally or professionally? What are you actively working toward?'
  },
  {
    section: 'Working Style',
    question: 'How do you prefer responses — detailed and thorough, or short and direct? Formal or casual tone?'
  },
  {
    section: 'Current Projects',
    question: 'What projects are you currently working on? Any side projects, businesses, or ongoing work?'
  }
];

// ── Secure Fetch Helper ───────────────────────────────────────────────────
/**
 * SECURITY: Centralized fetch with CSRF header.
 * Always same-origin. Never sends credentials cross-origin.
 */
async function secureFetch(url, options = {}) {
  const defaults = {
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': getCSRFToken(),
      ...options.headers
    }
  };
  const merged = { ...defaults, ...options, headers: { ...defaults.headers, ...options.headers } };
  const response = await fetch(url, merged);
  if (!response.ok) {
    const err = await response.json().catch(() => ({ error: 'Network error' }));
    throw new Error(err.error || `HTTP ${response.status}`);
  }
  return response.json();
}

// ── XSS-Safe DOM Helpers ──────────────────────────────────────────────────
/**
 * SECURITY: Never use innerHTML with user content.
 * All user-provided text rendered via textContent only.
 */
function safeText(text) {
  const el = document.createElement('span');
  el.textContent = text;
  return el.innerHTML; // Now HTML-escaped
}

function setTextContent(el, text) {
  if (el) el.textContent = text;
}

// ── Initialize ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  await loadConversations();
  await loadSkills();
  await loadSettings();
  newChat();
});

// ── Conversations ─────────────────────────────────────────────────────────
async function loadConversations() {
  try {
    const convs = await secureFetch('/api/conversations');
    const list = document.getElementById('conv-list');
    list.innerHTML = '';
    if (!convs.length) {
      const empty = document.createElement('div');
      empty.className = 'conv-item';
      empty.style.opacity = '0.4';
      empty.style.cursor = 'default';
      empty.textContent = 'No conversations yet';
      list.appendChild(empty);
      return;
    }
    convs.forEach(conv => {
      const item = document.createElement('div');
      item.className = 'conv-item';
      item.dataset.id = conv.id;

      const icon = document.createElement('span');
      icon.className = 'conv-item-icon';
      icon.textContent = '💬';

      const title = document.createElement('span');
      title.textContent = conv.title; // textContent — XSS safe
      title.style.flex = '1';
      title.style.overflow = 'hidden';
      title.style.textOverflow = 'ellipsis';
      title.style.whiteSpace = 'nowrap';

      item.appendChild(icon);
      item.appendChild(title);
      item.addEventListener('click', () => loadConversation(conv.id));
      list.appendChild(item);
    });
  } catch (e) {
    console.error('Failed to load conversations:', e.message);
  }
}

async function loadConversation(convId) {
  try {
    const data = await secureFetch(`/api/conversations/${encodeURIComponent(convId)}`);
    state.currentConvId = data.id;
    state.messages = data.messages || [];
    setTextContent(document.getElementById('current-conv-title'), data.title || 'Conversation');
    renderMessages();
    highlightActiveConv(convId);
  } catch (e) {
    console.error('Failed to load conversation:', e.message);
  }
}

function highlightActiveConv(convId) {
  document.querySelectorAll('.conv-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === convId);
  });
}

function newChat() {
  state.currentConvId = null;
  state.messages = [];
  setTextContent(document.getElementById('current-conv-title'), 'New Conversation');
  document.getElementById('messages').innerHTML = '';

  // Restore welcome state
  const welcome = document.createElement('div');
  welcome.id = 'welcome-state';
  welcome.className = 'welcome-state';
  welcome.innerHTML = `
    <div class="welcome-logo">⬡</div>
    <h1 class="welcome-title">NeuConX</h1>
    <p class="welcome-sub">Your personal AI. Multiple minds. One truth.</p>
    <div class="starter-chips">
      <button class="chip" data-prompt="Explain quantum computing simply">Explain quantum computing</button>
      <button class="chip" data-prompt="Write a Python function to sort a list of dicts">Python sort dicts</button>
      <button class="chip" data-prompt="What are the best strategies for managing personal finances?">Personal finance tips</button>
    </div>
  `;
  // SECURITY: Add event listeners instead of onclick attributes
  welcome.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const prompt = chip.dataset.prompt;
      document.getElementById('chat-input').value = prompt;
      sendMessage();
    });
  });
  document.getElementById('messages').appendChild(welcome);
  document.querySelectorAll('.conv-item').forEach(el => el.classList.remove('active'));
}

// ── Skills ────────────────────────────────────────────────────────────────
async function loadSkills() {
  try {
    const skills = await secureFetch('/api/skills');
    const list = document.getElementById('skills-list');
    list.innerHTML = '';
    skills.forEach(skill => {
      const item = document.createElement('div');
      item.className = 'skill-item';

      const toggle = document.createElement('button');
      toggle.className = 'skill-toggle';
      toggle.setAttribute('aria-label', `Toggle ${skill.name} skill`);
      toggle.addEventListener('click', () => {
        const isOn = toggle.classList.toggle('on');
        if (isOn) state.activeSkills.add(skill.filename);
        else state.activeSkills.delete(skill.filename);
        updateActiveSkillsDisplay();
      });

      const name = document.createElement('span');
      name.className = 'skill-name';
      name.textContent = skill.name; // textContent — XSS safe

      item.appendChild(toggle);
      item.appendChild(name);
      list.appendChild(item);
    });
  } catch (e) {
    console.error('Failed to load skills:', e.message);
  }
}

function updateActiveSkillsDisplay() {
  const display = document.getElementById('active-skills-display');
  display.innerHTML = '';
  state.activeSkills.forEach(skill => {
    const tag = document.createElement('span');
    tag.className = 'active-skill-tag';
    tag.textContent = skill.replace('.md', ''); // textContent — XSS safe
    display.appendChild(tag);
  });
}

async function uploadSkill(event) {
  const file = event.target.files[0];
  if (!file) return;

  // SECURITY: Client-side validation (server also validates)
  if (!file.name.toLowerCase().endsWith('.md')) {
    alert('Only .md files are allowed');
    return;
  }
  if (file.size > 50 * 1024) {
    alert('Skill file must be under 50KB');
    return;
  }

  const formData = new FormData();
  formData.append('file', file);
  try {
    const response = await fetch('/api/skills/upload', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRF-Token': getCSRFToken() },
      body: formData
    });
    if (response.ok) {
      await loadSkills();
    } else {
      const err = await response.json();
      alert(err.error || 'Upload failed');
    }
  } catch (e) {
    console.error('Upload error:', e.message);
  }
  event.target.value = ''; // Reset input
}

// ── Chat ──────────────────────────────────────────────────────────────────
function handleKey(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 200) + 'px';
}

async function sendMessage() {
  if (state.isLoading) return;

  const input = document.getElementById('chat-input');
  const message = input.value.trim();
  if (!message) return;

  // SECURITY: Basic length validation
  if (message.length > 8000) {
    alert('Message too long. Maximum 8000 characters.');
    return;
  }

  input.value = '';
  input.style.height = 'auto';
  state.isLoading = true;
  document.getElementById('send-btn').disabled = true;

  // Remove welcome state
  const welcome = document.getElementById('welcome-state');
  if (welcome) welcome.remove();

  // Add user message
  addMessage('user', message);
  state.messages.push({ role: 'user', content: message, timestamp: new Date().toISOString() });

  // Add thinking indicator
  const thinkingId = addThinking();

  try {
    const payload = {
      message,
      history: state.messages.slice(-20),
      tier_override: state.selectedTier === 'auto' ? null : state.selectedTier,
      skills_active: Array.from(state.activeSkills)
    };

    const data = await secureFetch('/api/chat', {
      method: 'POST',
      body: JSON.stringify(payload)
    });

    removeThinking(thinkingId);

    const answer = data.final_answer || 'No response received.';
    addMessage('ai', answer, data.tier_used, data.models_used);
    state.messages.push({
      role: 'assistant',
      content: answer,
      timestamp: new Date().toISOString()
    });

    // Update right panel
    updateModelResponses(data.model_responses || []);

    // Update tier display
    setTextContent(document.getElementById('tier-display'),
      `${data.tier_used || 'auto'} · ${data.models_used || 0} model${data.models_used !== 1 ? 's' : ''}`);

    // Auto-save conversation
    await saveCurrentConversation();

  } catch (e) {
    removeThinking(thinkingId);
    addMessage('ai', `Error: ${e.message}. Please check your API keys in Settings.`);
    console.error('Chat error:', e.message);
  } finally {
    state.isLoading = false;
    document.getElementById('send-btn').disabled = false;
    input.focus();
  }
}

function sendStarter(prompt) {
  document.getElementById('chat-input').value = prompt;
  sendMessage();
}

function addMessage(role, content, tier, modelsUsed) {
  const messages = document.getElementById('messages');
  const wrapper = document.createElement('div');
  wrapper.className = `message message-${role}`;

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = content; // SECURITY: textContent — never innerHTML

  wrapper.appendChild(bubble);

  if (role === 'ai') {
    const meta = document.createElement('div');
    meta.className = 'message-meta';
    if (tier) {
      const tierSpan = document.createElement('span');
      tierSpan.textContent = `${tier}${modelsUsed ? ` · ${modelsUsed} models` : ''}`;
      meta.appendChild(tierSpan);
    }
    wrapper.appendChild(meta);
  }

  messages.appendChild(wrapper);
  messages.scrollTop = messages.scrollHeight;
}

function addThinking() {
  const id = 'thinking-' + Date.now();
  const messages = document.getElementById('messages');
  const wrapper = document.createElement('div');
  wrapper.className = 'message message-ai';
  wrapper.id = id;

  const indicator = document.createElement('div');
  indicator.className = 'thinking-indicator';
  for (let i = 0; i < 3; i++) {
    const dot = document.createElement('div');
    dot.className = 'thinking-dot';
    indicator.appendChild(dot);
  }

  wrapper.appendChild(indicator);
  messages.appendChild(wrapper);
  messages.scrollTop = messages.scrollHeight;
  return id;
}

function removeThinking(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function renderMessages() {
  const messages = document.getElementById('messages');
  messages.innerHTML = '';
  state.messages.forEach(msg => {
    addMessage(msg.role, msg.content);
  });
}

function updateModelResponses(responses) {
  const panel = document.getElementById('model-responses');
  panel.innerHTML = '';

  const colors = { gemini: '#4285F4', nvidia: '#76B900', deepseek: '#00C4FF', mistral: '#FF7000' };

  responses.forEach(r => {
    const card = document.createElement('div');
    card.className = 'model-response-card';
    card.style.borderLeftColor = colors[r.model] || '#444';

    const name = document.createElement('div');
    name.className = 'model-response-name';
    name.style.color = colors[r.model] || '#888';
    name.textContent = r.model.toUpperCase(); // textContent — XSS safe

    card.appendChild(name);

    if (r.error) {
      const err = document.createElement('div');
      err.className = 'model-error';
      err.textContent = r.error; // textContent — XSS safe
      card.appendChild(err);
    } else {
      const text = document.createElement('div');
      text.className = 'model-response-text';
      text.textContent = r.response || ''; // textContent — XSS safe
      card.appendChild(text);
    }

    panel.appendChild(card);
  });

  if (!responses.length) {
    const empty = document.createElement('div');
    empty.className = 'panel-empty';
    empty.textContent = 'No model responses yet.';
    panel.appendChild(empty);
  }
}

// ── Tier Selection ────────────────────────────────────────────────────────
function setTier(tier) {
  state.selectedTier = tier;
  document.querySelectorAll('.tier-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tier === tier);
  });
  const labels = { auto: 'Auto routing', tier1: 'Quick — 1 model', tier2: 'Balanced — 2 models', tier3: 'Deep — all models' };
  setTextContent(document.getElementById('tier-display'), labels[tier] || 'Auto routing');
}

// ── Save Conversation ─────────────────────────────────────────────────────
async function saveCurrentConversation() {
  if (!state.messages.length) return;
  try {
    const title = state.messages[0]?.content?.slice(0, 50) || 'New Conversation';
    const payload = {
      id: state.currentConvId,
      title,
      messages: state.messages,
      created_at: new Date().toISOString()
    };
    const data = await secureFetch('/api/conversations', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
    if (data.id && !state.currentConvId) {
      state.currentConvId = data.id;
      setTextContent(document.getElementById('current-conv-title'), title);
      await loadConversations();
      highlightActiveConv(data.id);
    }
  } catch (e) {
    console.error('Failed to save conversation:', e.message);
  }
}

// ── Settings ──────────────────────────────────────────────────────────────
async function loadSettings() {
  try {
    const data = await secureFetch('/api/settings');
    const statuses = { gemini: 'gemini-status', nvidia: 'nvidia-status', openrouter: 'openrouter-status' };
    Object.entries(statuses).forEach(([key, elId]) => {
      const el = document.getElementById(elId);
      if (el) {
        if (data[`${key}_configured`]) {
          el.textContent = `✓ configured ${data[`${key}_hint`] || ''}`;
          el.className = 'key-status configured';
        } else {
          el.textContent = '✗ not set';
          el.className = 'key-status missing';
        }
      }
    });
    const models = Object.entries({ gemini: data.gemini_configured, nvidia: data.nvidia_configured, openrouter: data.openrouter_configured })
      .filter(([, v]) => v).map(([k]) => k);
    setTextContent(document.getElementById('models-display'), models.length ? `${models.join(', ')} active` : 'No models configured');
  } catch (e) {
    console.error('Failed to load settings:', e.message);
  }
}

async function saveSettings() {
  const payload = {
    gemini_key: document.getElementById('gemini-key').value.trim(),
    nvidia_key: document.getElementById('nvidia-key').value.trim(),
    openrouter_key: document.getElementById('openrouter-key').value.trim()
  };

  const msgEl = document.getElementById('settings-msg');
  try {
    const data = await secureFetch('/api/settings', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
    msgEl.textContent = data.message || 'Saved successfully.';
    msgEl.className = 'settings-msg success';
    msgEl.classList.remove('hidden');
    // Clear inputs after save
    ['gemini-key', 'nvidia-key', 'openrouter-key'].forEach(id => {
      document.getElementById(id).value = '';
    });
    await loadSettings();
    setTimeout(() => msgEl.classList.add('hidden'), 4000);
  } catch (e) {
    msgEl.textContent = e.message || 'Failed to save settings.';
    msgEl.className = 'settings-msg error';
    msgEl.classList.remove('hidden');
  }
}

function showSettings() {
  document.getElementById('settings-modal').classList.remove('hidden');
}
function hideSettings() {
  document.getElementById('settings-modal').classList.add('hidden');
}

// Close modal on outside click
document.addEventListener('click', (e) => {
  const modal = document.getElementById('settings-modal');
  if (e.target === modal) hideSettings();
});

// ── Right Panel ───────────────────────────────────────────────────────────
function toggleRightPanel() {
  const panel = document.getElementById('right-panel');
  panel.classList.toggle('hidden');
}

// ── Memory Confirmation ───────────────────────────────────────────────────
function useMemory() {
  document.getElementById('memory-confirm-card').classList.add('hidden');
}
function skipMemory() {
  document.getElementById('memory-confirm-card').classList.add('hidden');
}

// ── Onboarding ────────────────────────────────────────────────────────────
let currentStep = 0;

function onboardingNext() {
  if (currentStep === 0) {
    // Welcome step — just move forward
    currentStep = 1;
    showOnboardingStep(1);
    return;
  }

  // Save answer
  const answer = document.getElementById('ob-answer')?.value?.trim() || '';
  if (!answer && currentStep > 0) {
    document.getElementById('ob-answer').style.borderColor = 'rgba(255,77,77,0.5)';
    setTimeout(() => {
      if (document.getElementById('ob-answer'))
        document.getElementById('ob-answer').style.borderColor = '';
    }, 1500);
    return;
  }

  const step = ONBOARDING_STEPS[currentStep];
  state.onboardingAnswers[step.section.toLowerCase()] = answer;

  if (currentStep < ONBOARDING_STEPS.length - 1) {
    currentStep++;
    showOnboardingStep(currentStep);
  } else {
    completeOnboarding();
  }
}

function onboardingBack() {
  if (currentStep > 1) {
    currentStep--;
    showOnboardingStep(currentStep);
  }
}

function showOnboardingStep(step) {
  const total = ONBOARDING_STEPS.length - 1;
  const progress = ((step) / total) * 100;
  document.getElementById('onboarding-fill').style.width = `${progress}%`;
  setTextContent(document.getElementById('onboarding-step'), `${step} / ${total}`);

  const stepData = ONBOARDING_STEPS[step];
  const content = document.getElementById('onboarding-content');
  const questionWrap = document.getElementById('ob-question-wrap');

  if (step === 0) {
    setTextContent(document.getElementById('ob-title'), 'Welcome to NeuConX');
    setTextContent(document.querySelector('#ob-subtitle') || document.createElement('p'),
      'Before we begin, I need to understand you deeply.');
    questionWrap.classList.add('hidden');
    document.getElementById('ob-back').classList.add('hidden');
    setTextContent(document.getElementById('ob-next'), 'Get Started →');
  } else {
    const title = document.getElementById('ob-title');
    if (title) setTextContent(title, `Section ${step}: ${stepData.section}`);
    questionWrap.classList.remove('hidden');
    setTextContent(document.getElementById('ob-question'), stepData.question);
    document.getElementById('ob-answer').value = state.onboardingAnswers[stepData.section.toLowerCase()] || '';
    document.getElementById('ob-back').classList.remove('hidden');
    const isLast = step === ONBOARDING_STEPS.length - 1;
    setTextContent(document.getElementById('ob-next'), isLast ? 'Complete Setup ✓' : 'Next →');
  }
}

async function completeOnboarding() {
  try {
    await secureFetch('/api/profile', {
      method: 'POST',
      body: JSON.stringify(state.onboardingAnswers)
    });
    document.getElementById('onboarding-overlay').classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');
    await loadConversations();
    await loadSkills();
  } catch (e) {
    console.error('Onboarding save failed:', e.message);
    // Still let user in even if save fails
    document.getElementById('onboarding-overlay').classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');
  }
}

// Initialize onboarding if needed
if (document.getElementById('onboarding-overlay') &&
    !document.getElementById('onboarding-overlay').classList.contains('hidden')) {
  showOnboardingStep(0);
}
