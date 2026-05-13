'use strict';

/* ── State ── */
let client = null;
let ticketId = null;
let ticketSubject = '';
let sessionId = null;
let messages = [];     // { role: 'agent'|'copilot'|'error', text: string, id: number }
let msgCounter = 0;
let isLoading = false;

/* ── DOM refs ── */
const threadEl = document.getElementById('thread');
const emptyStateEl = document.getElementById('empty-state');
const sessionBarEl = document.getElementById('session-bar');
const queryInput = document.getElementById('query-input');
const sendBtn = document.getElementById('send-btn');
const resetBtn = document.getElementById('reset-btn');

/* ── marked.js config ── */
marked.setOptions({
  breaks: true,
  gfm: true,
});

/* ── FDK initialisation ── */
document.addEventListener('DOMContentLoaded', () => {
  if (typeof app !== 'undefined') {
    app.initialized().then((_client) => {
      client = _client;

      client.data.get('ticket').then(
        (data) => {
          ticketId = data.ticket.id;
          ticketSubject = data.ticket.subject || '';
          sessionId = `ticket_${ticketId}`;
          updateSessionLabel(ticketId);
        },
        () => {
          sessionId = `session_${Date.now()}`;
          updateSessionLabel('unknown');
        }
      );
    });
  } else {
    // Dev fallback (fdk run without full FDK context)
    sessionId = `ticket_dev_${Date.now()}`;
    updateSessionLabel('dev');
  }

  bindEvents();
});

/* ── UI helpers ── */
function updateSessionLabel(id) {
  sessionBarEl.textContent = `Session: Ticket #${id}`;
}

function hideEmptyState() {
  if (emptyStateEl && emptyStateEl.parentNode) {
    emptyStateEl.parentNode.removeChild(emptyStateEl);
  }
}

function scrollToBottom() {
  threadEl.scrollTop = threadEl.scrollHeight;
}

/* ── Message rendering ── */
function appendAgentMessage(text) {
  hideEmptyState();
  const id = ++msgCounter;
  messages.push({ role: 'agent', text, id });

  const row = document.createElement('div');
  row.className = 'msg-row agent';
  row.dataset.id = id;

  const bubble = document.createElement('div');
  bubble.className = 'bubble-agent';
  bubble.textContent = text;

  row.appendChild(bubble);
  threadEl.appendChild(row);
  scrollToBottom();
  return id;
}

function appendLoadingIndicator() {
  const id = ++msgCounter;

  const row = document.createElement('div');
  row.className = 'msg-row copilot';
  row.dataset.loadingId = id;

  const card = document.createElement('div');
  card.className = 'loading-card';
  card.innerHTML = `
    <div class="dots">
      <span></span><span></span><span></span>
    </div>
    <span>Thinking…</span>
  `;

  row.appendChild(card);
  threadEl.appendChild(row);
  scrollToBottom();
  return id;
}

function replaceLoadingWithResponse(loadingId, responseText) {
  const loadingRow = threadEl.querySelector(`[data-loading-id="${loadingId}"]`);
  if (!loadingRow) return;

  const id = ++msgCounter;
  messages.push({ role: 'copilot', text: responseText, id });

  const row = document.createElement('div');
  row.className = 'msg-row copilot';
  row.dataset.id = id;

  const card = buildCopilotCard(responseText, id);
  row.appendChild(card);

  threadEl.replaceChild(row, loadingRow);
  scrollToBottom();
}

function replaceLoadingWithError(loadingId, errorText) {
  const loadingRow = threadEl.querySelector(`[data-loading-id="${loadingId}"]`);
  if (!loadingRow) return;

  const id = ++msgCounter;
  messages.push({ role: 'error', text: errorText, id });

  const row = document.createElement('div');
  row.className = 'msg-row copilot';
  row.dataset.id = id;

  const card = document.createElement('div');
  card.className = 'card-error';
  card.textContent = errorText;

  row.appendChild(card);
  threadEl.replaceChild(row, loadingRow);
  scrollToBottom();
}

function buildCopilotCard(responseText, id) {
  const card = document.createElement('div');
  card.className = 'card-copilot';

  const header = document.createElement('div');
  header.className = 'card-copilot-header';

  const label = document.createElement('span');
  label.className = 'copilot-label';
  label.textContent = 'FSA Copilot';

  const copyBtn = document.createElement('button');
  copyBtn.className = 'btn-copy';
  copyBtn.dataset.msgId = id;
  copyBtn.innerHTML = `
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="5" y="5" width="9" height="9" rx="1.5" stroke="currentColor" stroke-width="1.5"/>
      <path d="M4 11H3a1.5 1.5 0 0 1-1.5-1.5V3A1.5 1.5 0 0 1 3 1.5h6.5A1.5 1.5 0 0 1 11 3v1" stroke="currentColor" stroke-width="1.5"/>
    </svg>
    Copy
  `;
  copyBtn.addEventListener('click', () => handleCopy(copyBtn, responseText));

  header.appendChild(label);
  header.appendChild(copyBtn);

  const body = document.createElement('div');
  body.className = 'card-copilot-body';

  const rawHtml = marked.parse(responseText);
  body.innerHTML = typeof DOMPurify !== 'undefined'
    ? DOMPurify.sanitize(rawHtml)
    : rawHtml.replace(/<script[\s\S]*?<\/script>/gi, '');

  card.appendChild(header);
  card.appendChild(body);
  return card;
}

/* ── Copy to clipboard ── */
async function handleCopy(btn, text) {
  const plain = stripMarkdown(text);
  try {
    await navigator.clipboard.writeText(plain);
    showCopied(btn);
  } catch {
    // Fallback for environments without clipboard API
    const ta = document.createElement('textarea');
    ta.value = plain;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    showCopied(btn);
  }
}

function showCopied(btn) {
  btn.classList.add('copied');
  btn.innerHTML = `
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M3 8l4 4 6-7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    Copied!
  `;
  setTimeout(() => {
    btn.classList.remove('copied');
    btn.innerHTML = `
      <svg width="12" height="12" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect x="5" y="5" width="9" height="9" rx="1.5" stroke="currentColor" stroke-width="1.5"/>
        <path d="M4 11H3a1.5 1.5 0 0 1-1.5-1.5V3A1.5 1.5 0 0 1 3 1.5h6.5A1.5 1.5 0 0 1 11 3v1" stroke="currentColor" stroke-width="1.5"/>
      </svg>
      Copy
    `;
  }, 2000);
}

/* Strip markdown syntax for plain-text clipboard copy */
function stripMarkdown(text) {
  return text
    .replace(/#{1,6}\s+/g, '')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/`{1,3}([^`]+)`{1,3}/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/^[-*+]\s+/gm, '• ')
    .replace(/^\d+\.\s+/gm, '')
    .replace(/^>\s+/gm, '')
    .trim();
}

/* ── Network call ── */
async function sendToN8N(query) {
  let webhookUrl;

  if (client) {
    const iparams = await client.iparams.get('webhook_url');
    webhookUrl = iparams.webhook_url;
  } else {
    // Dev fallback — will show network error, which is expected without real FDK
    webhookUrl = 'https://saiplatform.app.n8n.cloud/webhook/freshdesk-copilot';
  }

  const payload = {
    query,
    sessionId: sessionId || `session_${Date.now()}`,
    ticketSubject: ticketSubject || '',
  };

  const response = await fetch(webhookUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(30000),
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  const data = await response.json();

  if (!data.response) {
    throw new Error('Empty response from copilot service');
  }

  return data.response;
}

/* ── Send flow ── */
async function handleSend() {
  const query = queryInput.value.trim();
  if (!query || isLoading) return;

  isLoading = true;
  queryInput.value = '';
  autoResizeTextarea();
  sendBtn.disabled = true;

  appendAgentMessage(query);
  const loadingId = appendLoadingIndicator();

  try {
    const responseText = await sendToN8N(query);
    replaceLoadingWithResponse(loadingId, responseText);
  } catch (err) {
    const isTimeout = err.name === 'TimeoutError' || err.message.includes('timeout');
    const errorMsg = isTimeout
      ? 'The copilot service took too long to respond (>30s). Please try again.'
      : 'Unable to reach the copilot service. Please try again or contact the team if the issue persists.';
    replaceLoadingWithError(loadingId, errorMsg);
  } finally {
    isLoading = false;
    updateSendBtn();
  }
}

/* ── Session reset ── */
function handleReset() {
  messages = [];
  msgCounter = 0;

  // Clear thread and restore empty state
  threadEl.innerHTML = '';
  const newEmpty = document.createElement('div');
  newEmpty.className = 'empty-state';
  newEmpty.id = 'empty-state';
  newEmpty.innerHTML = `
    <svg width="36" height="36" viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="3" y="3" width="30" height="22" rx="4" fill="#D5E4F0"/>
      <path d="M3 21l7 7V21H3Z" fill="#D5E4F0"/>
      <rect x="9" y="10" width="18" height="2" rx="1" fill="#1F5C99"/>
      <rect x="9" y="15" width="12" height="2" rx="1" fill="#2D7DD2"/>
    </svg>
    <p>Paste the customer's question<br>to get a draft response.</p>
  `;
  threadEl.appendChild(newEmpty);

  // New session ID scoped to ticket
  if (ticketId) {
    sessionId = `ticket_${ticketId}_reset_${Date.now()}`;
  } else {
    sessionId = `session_reset_${Date.now()}`;
  }
}

/* ── Textarea auto-resize ── */
function autoResizeTextarea() {
  queryInput.style.height = 'auto';
  const max = 90;
  queryInput.style.height = Math.min(queryInput.scrollHeight, max) + 'px';
}

function updateSendBtn() {
  sendBtn.disabled = !queryInput.value.trim() || isLoading;
}

/* ── Event binding ── */
function bindEvents() {
  queryInput.addEventListener('input', () => {
    autoResizeTextarea();
    updateSendBtn();
  });

  queryInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });

  sendBtn.addEventListener('click', handleSend);
  resetBtn.addEventListener('click', handleReset);
}
