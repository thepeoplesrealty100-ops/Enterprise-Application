// integration.js — JAKAL live UI bridge (v2.5 enhanced)
// Same-origin when UI is served from :8000; otherwise 127.0.0.1:8000.

export const BACKEND_BASE = (() => {
  const { hostname, port, origin } = window.location;
  const local = hostname === 'localhost' || hostname === '127.0.0.1';
  if (local && (port === '8000' || port === '')) return '';
  if (local) return 'http://127.0.0.1:8000';
  return origin;
})();

const DEMO_TARGET = 'staging.client.com';

function el(id) {
  return document.getElementById(id);
}

function btnStyle(bg = '#1f2937') {
  return `cursor:pointer;border:1px solid #4b5563;background:${bg};color:#fff;border-radius:6px;padding:4px 10px;font-size:11px;font-weight:600`;
}

function cardStyle() {
  return 'background:rgba(31,41,55,.92);border:1px solid #374151;border-radius:12px;padding:14px;margin:12px 0';
}

function ensureConsole() {
  let c = el('telemetry-console');
  if (c) return c;
  c = document.createElement('div');
  c.id = 'telemetry-console';
  c.style.cssText = [
    'position:fixed', 'right:12px', 'bottom:40px', 'z-index:9998',
    'width:min(420px,92vw)', 'max-height:220px', 'overflow:auto',
    'padding:10px', 'background:rgba(17,24,39,.92)', 'border:1px solid #374151',
    'border-radius:10px', 'font:11px/1.4 ui-monospace,monospace', 'color:#d1d5db'
  ].join(';');
  document.body.appendChild(c);
  return c;
}

export function updateTelemetryConsole(text, colorClass = 'text-gray-300') {
  const container = ensureConsole();
  const row = document.createElement('div');
  row.style.marginBottom = '4px';
  row.style.color = colorClass.includes('red') ? '#f87171'
    : colorClass.includes('emerald') || colorClass.includes('green') ? '#34d399'
    : colorClass.includes('yellow') ? '#fbbf24'
    : '#d1d5db';
  row.textContent = text;
  container.appendChild(row);
  while (container.children.length > 80) container.removeChild(container.firstChild);
  container.scrollTop = container.scrollHeight;
}

function ensurePanel() {
  let bar = el('jakal-live-bar');
  if (bar) return bar;

  bar = document.createElement('div');
  bar.id = 'jakal-live-bar';
  bar.style.cssText = [
    'position:fixed', 'top:0', 'left:0', 'right:0', 'z-index:9999',
    'display:flex', 'flex-wrap:wrap', 'align-items:center', 'gap:8px',
    'padding:8px 12px', 'background:#0f172a', 'border-bottom:1px solid #f97316',
    'font:12px/1.4 Inter,system-ui,sans-serif', 'color:#e5e7eb'
  ].join(';');

  bar.innerHTML = `
    <strong style="color:#f97316">JAKAL LIVE</strong>
    <span id="jakal-conn" style="padding:2px 8px;border-radius:999px;background:#374151">checking…</span>
    <span id="jakal-meta" style="opacity:.85"></span>
    <span style="flex:1"></span>
    <button type="button" id="jakal-btn-health" style="${btnStyle()}">Health</button>
    <button type="button" id="jakal-btn-seed" style="${btnStyle()}">Seed auth</button>
    <button type="button" id="jakal-btn-quantum" style="${btnStyle()}">Quantum</button>
    <button type="button" id="jakal-btn-fabric" style="${btnStyle()}">Fabric</button>
    <button type="button" id="jakal-btn-pentest" style="${btnStyle('#b91c1c')}">Pentest</button>
    <button type="button" id="jakal-btn-ops" style="${btnStyle('#0e7490')}">Live Ops</button>
  `;

  document.body.prepend(bar);
  const app = el('app');
  if (app) app.style.paddingTop = '48px';

  el('jakal-btn-health').onclick = () => refreshHealth();
  el('jakal-btn-seed').onclick = () => seedAuthorization();
  el('jakal-btn-quantum').onclick = () => runQuantumSimulation('bell_state', 512);
  el('jakal-btn-fabric').onclick = () => loadFabric();
  el('jakal-btn-pentest').onclick = () => runDemoPentest();
  el('jakal-btn-ops').onclick = () => toggleOpsDrawer(true);

  ensureConsole();
  ensureOpsDrawer();
  return bar;
}

function ensureOpsDrawer() {
  if (el('jakal-ops-drawer')) return;
  const d = document.createElement('div');
  d.id = 'jakal-ops-drawer';
  d.style.cssText = [
    'position:fixed', 'top:48px', 'right:0', 'bottom:0', 'width:min(440px,100vw)',
    'z-index:9997', 'background:#111827', 'border-left:1px solid #f97316',
    'transform:translateX(100%)', 'transition:transform .25s ease',
    'display:flex', 'flex-direction:column', 'font:12px/1.4 Inter,system-ui,sans-serif', 'color:#e5e7eb'
  ].join(';');
  d.innerHTML = `
    <div style="padding:12px;border-bottom:1px solid #374151;display:flex;align-items:center;gap:8px">
      <strong style="color:#f97316;flex:1">Live Ops</strong>
      <button type="button" id="jakal-ops-refresh" style="${btnStyle()}">Refresh all</button>
      <button type="button" id="jakal-ops-close" style="${btnStyle()}">Close</button>
    </div>
    <div style="padding:8px;display:flex;flex-wrap:wrap;gap:6px;border-bottom:1px solid #374151">
      <button type="button" data-ops-tab="reports" class="ops-tab" style="${btnStyle('#374151')}">Reports</button>
      <button type="button" data-ops-tab="logs" class="ops-tab" style="${btnStyle('#374151')}">Agent logs</button>
      <button type="button" data-ops-tab="approval" class="ops-tab" style="${btnStyle('#374151')}">Approval</button>
      <button type="button" data-ops-tab="diag" class="ops-tab" style="${btnStyle('#374151')}">Diagnostics</button>
      <button type="button" data-ops-tab="quantum" class="ops-tab" style="${btnStyle('#374151')}">Quantum</button>
      <button type="button" data-ops-tab="fabric" class="ops-tab" style="${btnStyle('#374151')}">Fabric</button>
      <button type="button" data-ops-tab="response" class="ops-tab" style="${btnStyle('#374151')}">Response</button>
      <button type="button" data-ops-tab="scripts" class="ops-tab" style="${btnStyle('#374151')}">Scripts</button>
    </div>
    <div id="jakal-ops-body" style="flex:1;overflow:auto;padding:12px"></div>
  `;
  document.body.appendChild(d);
  el('jakal-ops-close').onclick = () => toggleOpsDrawer(false);
  el('jakal-ops-refresh').onclick = () => refreshOpsTab();
  d.querySelectorAll('[data-ops-tab]').forEach((b) => {
    b.onclick = () => {
      window.__opsTab = b.getAttribute('data-ops-tab');
      refreshOpsTab();
    };
  });
  window.__opsTab = 'reports';
}

function toggleOpsDrawer(open) {
  ensureOpsDrawer();
  const d = el('jakal-ops-drawer');
  d.style.transform = open ? 'translateX(0)' : 'translateX(100%)';
  if (open) refreshOpsTab();
}

async function refreshOpsTab() {
  const tab = window.__opsTab || 'reports';
  const body = el('jakal-ops-body');
  if (!body) return;
  body.innerHTML = '<div style="opacity:.7">Loading…</div>';
  try {
    if (tab === 'reports') body.innerHTML = await renderReportsPanel();
    else if (tab === 'logs') body.innerHTML = await renderLogsPanel();
    else if (tab === 'approval') body.innerHTML = await renderApprovalPanel();
    else if (tab === 'diag') body.innerHTML = await renderDiagPanel();
    else if (tab === 'quantum') body.innerHTML = await renderQuantumPanel();
    else if (tab === 'fabric') body.innerHTML = await renderFabricPanel();
    else if (tab === 'response') body.innerHTML = await renderResponseConsolePanel();
    else if (tab === 'scripts') body.innerHTML = await renderScriptLibraryPanel();
    wireOpsActions(body);
    wireResponseConsoleActions(body);
    wireScriptLibraryActions(body);
  } catch (e) {
    body.innerHTML = `<div style="color:#f87171">${escapeHtml(e.message)}</div>`;
  }
}

function escapeHtml(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function authToken() {
  try { return sessionStorage.getItem('jakal_token') || ''; } catch { return ''; }
}

function setAuthToken(token) {
  try {
    if (token) sessionStorage.setItem('jakal_token', token);
    else sessionStorage.removeItem('jakal_token');
  } catch { /* sessionStorage unavailable (private mode etc.) — token just won't persist */ }
}

async function api(path, options = {}) {
  const url = `${BACKEND_BASE}${path}`;
  const token = authToken();
  const res = await fetch(url, {
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!res.ok) {
    const detail = data?.detail || text || res.statusText;
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

async function renderReportsPanel() {
  const list = await api('/api/reports/list?limit=20');
  const rows = Array.isArray(list) ? list : [];
  if (!rows.length) {
    return '<p style="opacity:.7">No pentest runs yet. Use <b>Pentest</b> on the top bar.</p>';
  }
  const items = rows.map((r) => `
    <div style="${cardStyle()}">
      <div style="display:flex;justify-content:space-between;gap:8px">
        <div><b>#${escapeHtml(r.scan_id)}</b> · ${escapeHtml(r.target)}</div>
        <span style="color:#34d399">${escapeHtml(r.status)}</span>
      </div>
      <div style="opacity:.7;margin-top:4px">${escapeHtml(r.created_at || '')}</div>
      <button type="button" data-export="${escapeHtml(r.scan_id)}" style="${btnStyle()};margin-top:8px">Export markdown</button>
    </div>`).join('');
  return `<h3 style="color:#f97316;margin:0 0 8px">Pentest reports</h3>${items}`;
}

async function renderLogsPanel() {
  const data = await api('/api/agent/logs?limit=40');
  const logs = data.logs || [];
  if (!logs.length) return '<p style="opacity:.7">No agent logs yet.</p>';
  const lines = logs.map((row) => {
    const isObj = row && typeof row === 'object' && !Array.isArray(row);
    if (isObj) {
      return `<div style="border-bottom:1px solid #1f2937;padding:6px 0">
        <span style="opacity:.6">${escapeHtml(row.timestamp)}</span>
        <b> ${escapeHtml(row.event)}</b> — ${escapeHtml(row.action)}
        <span style="color:${row.status === 'success' || row.status === 'approved' ? '#34d399' : '#fbbf24'}"> (${escapeHtml(row.status)})</span>
      </div>`;
    }
    // tuple-ish: id, timestamp, event, action, status, ...
    const ts = row[1]; const event = row[2]; const action = row[3]; const status = row[4];
    return `<div style="border-bottom:1px solid #1f2937;padding:6px 0">
      <span style="opacity:.6">${escapeHtml(ts)}</span>
      <b> ${escapeHtml(event)}</b> — ${escapeHtml(action)}
      <span style="color:#34d399"> (${escapeHtml(status)})</span>
    </div>`;
  }).join('');
  return `<h3 style="color:#f97316;margin:0 0 8px">Agent logs</h3>${lines}`;
}

async function renderApprovalPanel() {
  let status = {};
  let pending = { count: 0, requests: [] };
  try { status = await api('/api/approval/status'); } catch (e) { status = { error: e.message }; }
  try { pending = await api('/api/approval/pending'); } catch (e) { pending = { count: 0, requests: [], error: e.message }; }
  const reqs = pending.requests || [];
  const list = reqs.length
    ? reqs.map((r) => {
        const id = r.request_id || r.id || r[0];
        return `<div style="${cardStyle()}">
          <div><b>${escapeHtml(id)}</b></div>
          <pre style="white-space:pre-wrap;font-size:10px;opacity:.85">${escapeHtml(JSON.stringify(r, null, 2).slice(0, 600))}</pre>
          <div style="display:flex;gap:6px;margin-top:8px">
            <button type="button" data-approve="${escapeHtml(id)}" style="${btnStyle('#166534')}">Approve</button>
            <button type="button" data-deny="${escapeHtml(id)}" style="${btnStyle('#991b1b')}">Deny</button>
          </div>
        </div>`;
      }).join('')
    : '<p style="opacity:.7">No pending approval requests. High-risk payloads stage here.</p>';
  return `<h3 style="color:#f97316;margin:0 0 8px">Human Approval Gate</h3>
    <pre style="font-size:10px;background:#0f172a;padding:8px;border-radius:8px">${escapeHtml(JSON.stringify(status, null, 2))}</pre>
    <p style="margin:8px 0">Pending: <b>${pending.count ?? reqs.length}</b></p>
    ${list}`;
}

async function renderDiagPanel() {
  const checks = [];
  const paths = [
    ['/health', 'Core health'],
    ['/api/health', 'API health'],
    ['/api/llm/health', 'LLM'],
    ['/api/quantum/status', 'Quantum'],
    ['/api/fabric/status', 'Fabric'],
    ['/api/crypto/status', 'Crypto'],
    ['/api/approval/status', 'Approval gate'],
  ];
  for (const [path, label] of paths) {
    try {
      const data = await api(path);
      checks.push({ label, ok: true, data });
    } catch (e) {
      checks.push({ label, ok: false, data: { error: e.message } });
    }
  }
  return `<h3 style="color:#f97316;margin:0 0 8px">Live diagnostics</h3>` + checks.map((c) => `
    <div style="${cardStyle()};border-left:3px solid ${c.ok ? '#34d399' : '#f87171'}">
      <div style="display:flex;justify-content:space-between"><b>${escapeHtml(c.label)}</b><span>${c.ok ? 'OK' : 'FAIL'}</span></div>
      <pre style="font-size:10px;margin:6px 0 0;white-space:pre-wrap">${escapeHtml(JSON.stringify(c.data, null, 2).slice(0, 500))}</pre>
    </div>`).join('');
}

async function renderQuantumPanel() {
  let status = {};
  try { status = await api('/api/quantum/status'); } catch (e) { status = { error: e.message }; }
  return `<h3 style="color:#f97316;margin:0 0 8px">Quantum engine</h3>
    <pre style="font-size:11px;background:#0f172a;padding:10px;border-radius:8px">${escapeHtml(JSON.stringify(status, null, 2))}</pre>
    <button type="button" data-qrun="bell_state" style="${btnStyle('#7c3aed');margin-top:10px}">Run Bell state (512 shots)</button>
    <button type="button" data-qrun="grover" style="${btnStyle('#7c3aed');margin-top:10px;margin-left:6px}">Run Grover</button>
    <div id="jakal-q-result" style="margin-top:12px;font-family:ui-monospace,monospace;font-size:11px"></div>`;
}

async function renderFabricPanel() {
  const data = await api('/api/fabric/status');
  const p = data.posture || {};
  const caps = data.capabilities || [];
  const pillars = Object.entries(p.by_pillar || {}).map(([name, v]) =>
    `<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #1f2937">
      <span>${escapeHtml(name)}</span><span style="color:#f97316">${escapeHtml(v.score)} · ${escapeHtml(v.level)}</span>
    </div>`).join('');
  const cards = caps.map((c) => `
    <div style="${cardStyle()}">
      <div style="display:flex;justify-content:space-between"><b>${escapeHtml(c.label || c.module_key)}</b>
        <span>${escapeHtml(c.maturity)} / ${escapeHtml(c.status)}</span></div>
      <div style="opacity:.75;margin-top:4px">${escapeHtml(c.pillar || '')}</div>
      <div style="opacity:.75;margin-top:4px;font-size:11px">${escapeHtml(c.description || '')}</div>
    </div>`).join('');
  return `<h3 style="color:#f97316;margin:0 0 8px">Unified Security Fabric</h3>
    <div style="${cardStyle()}"><div style="font-size:28px;font-weight:800;color:#f97316">${escapeHtml(p.overall_score ?? '—')}</div>
    <div>${escapeHtml(p.overall_level || '')} · ${data.capability_count || caps.length} capabilities</div>
    <div style="margin-top:8px">${pillars}</div></div>${cards}`;
}

// ─────────────────────────────────────────────────────────────────────────
// v2.6 — Global Settings & Security + remaining ops-module live panels
// ─────────────────────────────────────────────────────────────────────────

async function renderAuthPanel() {
  const token = authToken();
  if (token) {
    try {
      const me = await api('/api/iam/auth/me');
      const mfaSection = me.mfa_enabled
        ? `<div style="${cardStyle()}"><b style="color:#34d399">MFA enabled</b>
             <button type="button" data-mfa-disable style="${btnStyle('#7f1d1d')};margin-top:8px">Disable MFA</button></div>`
        : `<div style="${cardStyle()}"><b>MFA not enabled</b>
             <p style="opacity:.7;font-size:11px;margin:4px 0 8px">Scan the QR with any TOTP authenticator app (Google/Microsoft Authenticator, 1Password, Authy).</p>
             <button type="button" data-mfa-enroll style="${btnStyle('#7c3aed')}">Start MFA enrollment</button>
             <div id="mfa-enroll-out" style="margin-top:10px"></div>
           </div>`;
      return `<div style="${cardStyle()}">
        <b>Signed in as ${escapeHtml(me.username)}</b>
        <div style="opacity:.75;margin-top:4px">Roles: ${(me.roles || []).join(', ') || 'none'}</div>
        <div style="opacity:.75">Permissions: ${(me.permissions || []).join(', ') || 'none'}</div>
        <button type="button" data-iam-logout style="${btnStyle('#7f1d1d')};margin-top:8px">Sign out</button>
      </div>
      ${mfaSection}`;
    } catch (e) {
      setAuthToken('');
    }
  }
  return `<div style="${cardStyle()}">
    <b>Operator Sign-in</b>
    <p style="opacity:.75;font-size:11px;margin:4px 0 8px">First account created on a fresh install becomes root admin automatically.</p>
    <input id="iam-username" placeholder="username" style="width:100%;margin-bottom:6px;padding:6px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff">
    <input id="iam-password" type="password" placeholder="password (12+ chars)" style="width:100%;margin-bottom:8px;padding:6px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff">
    <input id="iam-totp" placeholder="6-digit MFA code (only if you have MFA enabled)" style="width:100%;margin-bottom:8px;padding:6px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff">
    <input id="iam-email" placeholder="email (only needed to register)" style="width:100%;margin-bottom:8px;padding:6px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff">
    <div style="display:flex;gap:6px">
      <button type="button" data-iam-login style="${btnStyle('#1d4ed8')};flex:1">Sign in</button>
      <button type="button" data-iam-register style="${btnStyle('#166534')};flex:1">Register</button>
    </div>
    <div id="iam-auth-msg" style="margin-top:8px;font-size:11px;opacity:.85"></div>
  </div>`;
}

function wireAuthPanel(root) {
  const msg = (t, ok) => { const m = root.querySelector('#iam-auth-msg'); if (m) { m.textContent = t; m.style.color = ok ? '#34d399' : '#f87171'; } };
  const loginBtn = root.querySelector('[data-iam-login]');
  const registerBtn = root.querySelector('[data-iam-register]');
  const logoutBtn = root.querySelector('[data-iam-logout]');
  if (loginBtn) loginBtn.onclick = async () => {
    const username = root.querySelector('#iam-username')?.value || '';
    const password = root.querySelector('#iam-password')?.value || '';
    const totp_code = root.querySelector('#iam-totp')?.value || undefined;
    try {
      const r = await api('/api/iam/auth/login', { method: 'POST', body: JSON.stringify({ username, password, totp_code }) });
      if (r.mfa_required) { msg('This account has MFA enabled — enter the 6-digit code from your authenticator app above, then Sign in again.', false); return; }
      setAuthToken(r.access_token);
      msg('Signed in.', true);
      window.switchSettingsSubTab?.(window.currentSettingsSubTab || 'profile');
    } catch (e) { msg(e.message, false); }
  };
  if (registerBtn) registerBtn.onclick = async () => {
    const username = root.querySelector('#iam-username')?.value || '';
    const password = root.querySelector('#iam-password')?.value || '';
    const email = root.querySelector('#iam-email')?.value || undefined;
    try {
      await api('/api/iam/auth/register', { method: 'POST', body: JSON.stringify({ username, password, email }) });
      msg('Registered — signing in…', true);
      const r = await api('/api/iam/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) });
      setAuthToken(r.access_token);
      window.switchSettingsSubTab?.(window.currentSettingsSubTab || 'profile');
    } catch (e) { msg(e.message, false); }
  };
  if (logoutBtn) logoutBtn.onclick = async () => {
    try { await api('/api/iam/auth/logout', { method: 'POST' }); } catch (_) {}
    setAuthToken('');
    window.switchSettingsSubTab?.(window.currentSettingsSubTab || 'profile');
  };

  const mfaEnrollBtn = root.querySelector('[data-mfa-enroll]');
  if (mfaEnrollBtn) mfaEnrollBtn.onclick = async () => {
    const out = root.querySelector('#mfa-enroll-out');
    try {
      const r = await api('/api/iam/auth/mfa/enroll', { method: 'POST' });
      out.innerHTML = `
        ${r.qr_data_uri ? `<img src="${r.qr_data_uri}" alt="MFA QR code" style="border-radius:8px;background:#fff;padding:8px">` : ''}
        <div style="margin-top:8px;font-size:11px;opacity:.75">Can't scan? Enter manually: <span style="font-family:ui-monospace,monospace;color:#f97316">${escapeHtml(r.secret)}</span></div>
        <input id="mfa-confirm-code" placeholder="Enter the 6-digit code from your app" style="width:100%;margin-top:8px;padding:6px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff">
        <button type="button" data-mfa-confirm style="${btnStyle('#166534')};margin-top:6px">Confirm & enable</button>
        <div id="mfa-confirm-msg" style="margin-top:6px;font-size:11px"></div>`;
      const confirmBtn = out.querySelector('[data-mfa-confirm]');
      confirmBtn.onclick = async () => {
        const totp_code = out.querySelector('#mfa-confirm-code')?.value || '';
        const cmsg = out.querySelector('#mfa-confirm-msg');
        try {
          await api('/api/iam/auth/mfa/confirm', { method: 'POST', body: JSON.stringify({ totp_code }) });
          cmsg.innerHTML = '<span style="color:#34d399">MFA enabled.</span>';
          setTimeout(() => window.switchSettingsSubTab?.(window.currentSettingsSubTab || 'profile'), 800);
        } catch (e) { cmsg.innerHTML = `<span style="color:#f87171">${escapeHtml(e.message)}</span>`; }
      };
    } catch (e) { out.innerHTML = `<span style="color:#f87171">${escapeHtml(e.message)}</span>`; }
  };
  const mfaDisableBtn = root.querySelector('[data-mfa-disable]');
  if (mfaDisableBtn) mfaDisableBtn.onclick = async () => {
    try {
      await api('/api/iam/auth/mfa/disable', { method: 'POST' });
      window.switchSettingsSubTab?.(window.currentSettingsSubTab || 'profile');
    } catch (e) { updateTelemetryConsole(`[MFA ERROR] ${e.message}`, 'text-red-400'); }
  };
}

async function renderRbacPanelLive() {
  const [roles, users] = await Promise.all([
    api('/api/iam/rbac/roles').catch(() => ({ roles: [] })),
    api('/api/iam/rbac/users').catch(() => ({ users: [] })),
  ]);
  const rows = (roles.roles || []).map((r) => `
    <tr style="border-bottom:1px solid #1f2937">
      <td style="padding:6px;color:#f97316;font-weight:700">${escapeHtml(r.label)}</td>
      <td style="padding:6px">${r.assigned_users ?? 0}</td>
      <td style="padding:6px;font-family:ui-monospace,monospace;font-size:11px">${escapeHtml((r.permissions || []).join(', '))}</td>
    </tr>`).join('');
  return `<div style="${cardStyle()}">
    <b>RBAC (live)</b> — ${(users.users || []).length} user(s) provisioned
    <table style="width:100%;margin-top:8px;font-size:12px"><thead><tr style="text-align:left;opacity:.7">
      <th style="padding:6px">Role</th><th style="padding:6px">Assigned</th><th style="padding:6px">Permissions</th>
    </tr></thead><tbody>${rows || '<tr><td style="padding:6px;opacity:.7" colspan="3">No roles yet.</td></tr>'}</tbody></table>
  </div>`;
}

async function renderAuditingPanelLive() {
  let data;
  try { data = await api('/api/iam/audit/log?limit=25'); } catch (e) { return `<div style="${cardStyle()};color:#f87171">${escapeHtml(e.message)} ${e.status === 401 ? '(sign in above to view the audit trail)' : ''}</div>`; }
  const rows = (data.entries || []).map((e) => `
    <div style="border-bottom:1px solid #1f2937;padding:6px 0;font-size:11px">
      <span style="opacity:.6">${escapeHtml(e.timestamp)}</span>
      <b> ${escapeHtml(e.actor_label || 'anonymous')}</b> → ${escapeHtml(e.action)}
      <span style="color:${e.outcome === 'success' ? '#34d399' : e.outcome === 'denied' ? '#f87171' : '#fbbf24'}"> (${escapeHtml(e.outcome)})</span>
    </div>`).join('');
  return `<div style="${cardStyle()}"><b>Audit Log (live)</b> — ${data.count} recent entries<div style="margin-top:8px;max-height:320px;overflow:auto">${rows || '<div style="opacity:.7">No audit entries yet.</div>'}</div></div>`;
}

async function renderApiIntegrationPanelLive() {
  let keys;
  try { keys = await api('/api/iam/api-keys'); } catch (e) {
    return `<div style="${cardStyle()};color:#f87171">${escapeHtml(e.message)} ${e.status === 401 ? '(sign in above to manage API keys)' : ''}</div>`;
  }
  const rows = (keys.keys || []).map((k) => `
    <div style="${cardStyle()}"><b>${escapeHtml(k.label || k.key_id)}</b> · ${escapeHtml(k.status)}
      <div style="opacity:.7;font-size:11px">${escapeHtml(k.key_id)} · created ${escapeHtml(k.created_at)}</div></div>`).join('');
  return `<div style="${cardStyle()}"><b>API Keys (live)</b>
    <input id="apikey-label" placeholder="key label" style="width:100%;margin:8px 0;padding:6px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff">
    <button type="button" data-create-apikey style="${btnStyle('#1d4ed8')}">Generate key</button>
    <div id="apikey-secret" style="margin-top:8px;font-size:11px;word-break:break-all"></div>
  </div>${rows}`;
}

async function renderVaultPanelLive() {
  let items;
  try { items = await api('/api/vault/items'); } catch (e) {
    return `<div style="${cardStyle()};color:#f87171">${escapeHtml(e.message)} ${e.status === 401 ? '(sign in above — vault access is RBAC-gated)' : ''}</div>`;
  }
  const rows = (items.items || []).map((i) => `
    <div style="${cardStyle()}"><b>${escapeHtml(i.title)}</b> · ${escapeHtml(i.classification)}
      <div style="opacity:.7;font-size:11px">item_id=${escapeHtml(i.item_id)} · ${escapeHtml(i.created_at)}</div></div>`).join('');
  return `<div style="${cardStyle()}"><b>Trade Secrets / EAS R&D Vault (live, AES-256-GCM at rest)</b></div>${rows || '<p style="opacity:.7">No vault items yet.</p>'}`;
}

async function renderEasRdPanelLive() {
  let last;
  try { last = await api('/api/vault/eas-rd/last-scan'); } catch (e) { last = { findings: [] }; }
  const findings = (last.findings || []).slice(0, 10).map((f) => `
    <div style="${cardStyle()};border-left:3px solid #f87171">
      <b>${escapeHtml(f.package)}==${escapeHtml(f.version)}</b> — ${escapeHtml(f.id)}
      <div style="opacity:.75;font-size:11px;margin-top:4px">${escapeHtml((f.summary || '').slice(0, 200))}</div>
    </div>`).join('');
  return `<div style="${cardStyle()}">
    <b>EAS R&D — live OSV.dev dependency scan</b>
    <div style="opacity:.7;font-size:11px;margin:4px 0">Last scan: ${escapeHtml(last.scanned_at || 'never')} · ${last.packages_scanned ?? 0} packages · ${(last.findings || []).length} findings</div>
    <button type="button" data-run-eas-scan style="${btnStyle('#1d4ed8')}">Run live scan now</button>
  </div>${findings}`;
}

async function renderDarkWebPanelLive() {
  const [watch, findings, connector] = await Promise.all([
    api('/api/darkweb/watchlist').catch(() => ({ watchlist: [] })),
    api('/api/darkweb/findings').catch(() => ({ findings: [] })),
    api('/api/darkweb/connector-status').catch(() => ({ configured: false })),
  ]);
  const wRows = (watch.watchlist || []).map((w) => `<div style="${cardStyle()}">${escapeHtml(w.identifier)} <span style="opacity:.6">(${escapeHtml(w.identifier_type)})</span></div>`).join('');
  const fRows = (findings.findings || []).map((f) => `<div style="${cardStyle()};border-left:3px solid #fbbf24"><b>${escapeHtml(f.breach_name || f.source)}</b> · ${escapeHtml(f.severity)}</div>`).join('');
  const statusBadge = connector.configured
    ? `<span style="padding:2px 10px;border-radius:999px;font-size:10px;font-weight:700;background:#065f46;color:#34d399">HIBP CONNECTED</span>`
    : `<span style="padding:2px 10px;border-radius:999px;font-size:10px;font-weight:700;background:#7c2d12;color:#fdba74">HIBP NOT CONFIGURED</span>`;
  return `<div style="${cardStyle()}"><div style="display:flex;justify-content:space-between;align-items:center"><b>Dark Web Monitoring (live)</b>${statusBadge}</div>
    <div style="opacity:.7;font-size:11px;margin-top:6px">
      ${connector.configured
        ? 'Live breach checks are enabled — Run scan will query Have I Been Pwned for every watched email.'
        : `Set <code style="background:#111827;padding:1px 5px;border-radius:4px">HIBP_API_KEY</code> in backend/.env to enable live breach checks — get a key at <a href="${escapeHtml(connector.setup_url || 'https://haveibeenpwned.com/API/Key')}" target="_blank" rel="noopener" style="color:#f97316">haveibeenpwned.com/API/Key</a>. Watchlist management and manual findings still work without it.`}
    </div>
    <input id="darkweb-identifier" placeholder="email to watch" style="width:100%;margin:8px 0;padding:6px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff">
    <div style="display:flex;gap:6px">
      <button type="button" data-darkweb-add style="${btnStyle('#1d4ed8')};flex:1">Add to watchlist</button>
      <button type="button" data-darkweb-scan style="${btnStyle('#166534')};flex:1" ${connector.configured ? '' : 'title="HIBP_API_KEY not set — scan will report no connector"'}>Run scan</button>
    </div>
  </div>
  <div style="margin-top:8px"><b style="opacity:.7;font-size:11px">WATCHLIST</b>${wRows || '<p style="opacity:.6;font-size:11px">Empty.</p>'}</div>
  <div style="margin-top:8px"><b style="opacity:.7;font-size:11px">FINDINGS</b>${fRows || '<p style="opacity:.6;font-size:11px">None yet.</p>'}</div>`;
}

async function renderAwarenessPanelLive() {
  const [modules, stats] = await Promise.all([
    api('/api/awareness/training/modules').catch(() => ({ modules: [] })),
    api('/api/awareness/training/stats').catch(() => null),
  ]);
  const rows = (modules.modules || []).map((m) => `
    <div style="${cardStyle()}"><b>${escapeHtml(m.title)}</b>
      <div style="opacity:.7;font-size:11px">${escapeHtml(m.category)} · ${m.duration_min}min · passing score ${m.passing_score}%</div></div>`).join('');
  const statLine = stats ? `${stats.total_completions} completions · ${stats.pass_rate_pct}% pass rate` : 'sign in to view stats';
  return `<div style="${cardStyle()}"><b>Security Awareness Training (live)</b><div style="opacity:.7;font-size:11px">${escapeHtml(statLine)}</div></div>${rows}`;
}

async function renderPhishingPanelLive() {
  const campaigns = await api('/api/awareness/phishing/campaigns').catch(() => ({ campaigns: [] }));
  const rows = await Promise.all((campaigns.campaigns || []).slice(0, 10).map(async (c) => {
    const s = await api(`/api/awareness/phishing/campaigns/${c.campaign_id}/stats`).catch(() => ({}));
    return `<div style="${cardStyle()}"><b>${escapeHtml(c.name)}</b> · ${escapeHtml(c.status)}
      <div style="opacity:.7;font-size:11px">sent ${s.sent ?? 0} · opened ${s.opened ?? 0} · clicked ${s.clicked ?? 0} · reported ${s.reported ?? 0} (${s.click_rate_pct ?? 0}% click rate)</div></div>`;
  }));
  return `<div style="${cardStyle()}"><b>Phishing Campaigns (live)</b></div>${rows.join('') || '<p style="opacity:.7">No campaigns launched yet.</p>'}`;
}

async function renderCheatsheetPanelLive() {
  const stats = await api('/api/cheatsheet/stats').catch(() => ({}));
  return `<div style="${cardStyle()}"><b>CheatSheet Library (live)</b>
    <pre style="font-size:11px;margin-top:8px;white-space:pre-wrap">${escapeHtml(JSON.stringify(stats, null, 2))}</pre></div>`;
}

async function renderSimpleJsonPanel(title, path) {
  try {
    const data = await api(path);
    return `<div style="${cardStyle()}"><b>${escapeHtml(title)} (live)</b>
      <pre style="font-size:11px;margin-top:8px;white-space:pre-wrap">${escapeHtml(JSON.stringify(data, null, 2).slice(0, 2000))}</pre></div>`;
  } catch (e) {
    return `<div style="${cardStyle()};color:#f87171">${escapeHtml(title)}: ${escapeHtml(e.message)}</div>`;
  }
}

function wireNewPanelActions(root) {
  const btn = (sel) => root.querySelector(sel);
  if (btn('[data-create-apikey]')) btn('[data-create-apikey]').onclick = async () => {
    const label = root.querySelector('#apikey-label')?.value || 'unlabeled';
    try {
      const r = await api('/api/iam/api-keys', { method: 'POST', body: JSON.stringify({ label, scopes: [] }) });
      const out = root.querySelector('#apikey-secret');
      if (out) out.innerHTML = `<b style="color:#34d399">Secret (shown once):</b> ${escapeHtml(r.secret)}`;
    } catch (e) { updateTelemetryConsole(`[APIKEY ERROR] ${e.message}`, 'text-red-400'); }
  };
  if (btn('[data-run-eas-scan]')) btn('[data-run-eas-scan]').onclick = async () => {
    updateTelemetryConsole('[EAS R&D] running live OSV.dev scan…');
    try {
      const r = await api('/api/vault/eas-rd/scan', { method: 'POST' });
      updateTelemetryConsole(`[EAS R&D] ${r.packages_scanned} packages, ${r.findings.length} findings`, 'text-emerald-400');
      window.switchSettingsSubTab?.('eas_rd');
    } catch (e) { updateTelemetryConsole(`[EAS R&D ERROR] ${e.message}`, 'text-red-400'); }
  };
  if (btn('[data-darkweb-add]')) btn('[data-darkweb-add]').onclick = async () => {
    const identifier = root.querySelector('#darkweb-identifier')?.value || '';
    try {
      await api('/api/darkweb/watchlist', { method: 'POST', body: JSON.stringify({ identifier, identifier_type: 'email' }) });
      injectPageLive('admin_dark_web');
    } catch (e) { updateTelemetryConsole(`[DARKWEB ERROR] ${e.message}`, 'text-red-400'); }
  };
  if (btn('[data-darkweb-scan]')) btn('[data-darkweb-scan]').onclick = async () => {
    try {
      const r = await api('/api/darkweb/scan', { method: 'POST' });
      updateTelemetryConsole(`[DARKWEB] scanned ${r.watched_identifiers}, ${r.new_findings} new findings`, 'text-emerald-400');
      injectPageLive('admin_dark_web');
    } catch (e) { updateTelemetryConsole(`[DARKWEB ERROR] ${e.message}`, 'text-red-400'); }
  };
}

// ─────────────────────────────────────────────────────────────────────────
// v2.7 — Detection & Response console + Script Library (Live Ops drawer)
// ─────────────────────────────────────────────────────────────────────────

const RISK_COLOR = { LOW: '#34d399', MEDIUM: '#fbbf24', HIGH: '#f97316', CRITICAL: '#f87171' };

async function renderResponseConsolePanel() {
  const [actions, stats, iocs] = await Promise.all([
    api('/api/response/actions?limit=15').catch(() => ({ actions: [] })),
    api('/api/response/stats').catch(() => ({ total: 0, by_type: {} })),
    api('/api/response/ioc?limit=10').catch(() => ({ indicators: [] })),
  ]);
  const ENFORCEABLE = new Set(['isolate_host_staged', 'quarantine_host_staged']);
  const actionRows = (actions.actions || []).map((a) => {
    const canEnforce = ENFORCEABLE.has(a.action_type) && a.status === 'staged' && a.approval_request_id;
    return `
    <div style="${cardStyle()};border-left:3px solid ${RISK_COLOR[a.risk_level] || '#6b7280'}">
      <div style="display:flex;justify-content:space-between"><b>${escapeHtml(a.action_type)}</b><span style="opacity:.7">${escapeHtml(a.status)}</span></div>
      <div style="opacity:.75;font-size:11px;margin-top:2px">${escapeHtml(a.target || '—')} · ${escapeHtml(a.d3fend_technique || '')} · ${escapeHtml(a.created_at)}</div>
      ${canEnforce ? `<button type="button" data-rc-enforce="${escapeHtml(a.approval_request_id)}" style="${btnStyle('#b91c1c')};margin-top:6px">Enforce (after approval)</button>` : ''}
    </div>`;
  }).join('');
  const iocRows = (iocs.indicators || []).map((i) => `
    <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #1f2937;font-size:11px">
      <span>${escapeHtml(i.indicator)}</span><span style="opacity:.6">${escapeHtml(i.indicator_type)} · ${escapeHtml(i.severity)}</span>
    </div>`).join('');
  return `
    <h3 style="color:#f97316;margin:0 0 8px">Detection &amp; Response</h3>
    <div style="${cardStyle()}"><b>${stats.total ?? 0}</b> total actions recorded</div>

    <div style="${cardStyle()}">
      <b>Triage a finding</b>
      <textarea id="rc-finding" rows="2" placeholder="finding_summary (e.g. 'unauthenticated RCE on staging.client.com')" style="width:100%;margin-top:6px;padding:6px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff;font:11px monospace"></textarea>
      <input id="rc-category" placeholder="threat_category (optional)" style="width:100%;margin-top:6px;padding:6px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff">
      <input id="rc-target" placeholder="target (optional, for auto-staged containment)" style="width:100%;margin:6px 0;padding:6px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff">
      <button type="button" data-rc-triage style="${btnStyle('#7c3aed')}">Run triage</button>
      <div id="rc-triage-result" style="margin-top:8px;font-size:11px"></div>
    </div>

    <div style="${cardStyle()}">
      <b>Block an indicator</b>
      <div style="display:flex;gap:6px;margin-top:6px">
        <input id="rc-ioc" placeholder="indicator (IP/domain/hash/url)" style="flex:2;padding:6px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff">
        <select id="rc-ioc-type" style="flex:1;padding:6px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff">
          <option value="ip">ip</option><option value="domain">domain</option><option value="hash_sha256">hash</option><option value="url">url</option><option value="email">email</option>
        </select>
      </div>
      <button type="button" data-rc-block style="${btnStyle('#991b1b')};margin-top:6px">Block indicator</button>
    </div>

    <div style="${cardStyle()}"><b>Active blocklist</b><div style="margin-top:6px">${iocRows || '<p style="opacity:.6;font-size:11px">None blocked yet.</p>'}</div></div>

    <div style="${cardStyle()}">
      <b>Isolate / quarantine a host</b>
      <p style="opacity:.6;font-size:10.5px;margin:4px 0 8px">Always staged behind the Human Approval Gate — never auto-executed.
        Approve at the Approval tab, then click Enforce below once approved.</p>
      <input id="rc-isolate-target" placeholder="target (must be in an active authorized scope)" style="width:100%;margin-bottom:6px;padding:6px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff">
      <input id="rc-isolate-reason" placeholder="reason" style="width:100%;margin-bottom:6px;padding:6px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff">
      <button type="button" data-rc-isolate style="${btnStyle('#b91c1c')}">Stage isolation</button>
      <div id="rc-isolate-result" style="margin-top:6px;font-size:11px"></div>
    </div>

    <h4 style="opacity:.7;font-size:11px;margin:14px 0 6px">RECENT ACTIONS</h4>
    ${actionRows || '<p style="opacity:.6;font-size:11px">No response actions yet.</p>'}
  `;
}

function wireResponseConsoleActions(root) {
  const triageBtn = root.querySelector('[data-rc-triage]');
  if (triageBtn) triageBtn.onclick = async () => {
    const finding_summary = root.querySelector('#rc-finding')?.value || '';
    const threat_category = root.querySelector('#rc-category')?.value || '';
    const target = root.querySelector('#rc-target')?.value || '';
    const out = root.querySelector('#rc-triage-result');
    try {
      const r = await api('/api/response/triage', { method: 'POST', body: JSON.stringify({ finding_summary, threat_category, target }) });
      const playbooks = (r.recommended_playbooks || []).map((p) => `${p.name} (${p.key})`).join(', ') || 'none matched';
      out.innerHTML = `<div style="color:${r.severity >= 0.8 ? '#f87171' : r.severity >= 0.4 ? '#fbbf24' : '#34d399'}">severity=${r.severity}</div>
        <div style="opacity:.8;margin-top:4px">Recommended: ${escapeHtml(playbooks)}</div>
        ${r.auto_staged_approval_request_id ? `<div style="color:#f97316;margin-top:4px">Auto-staged approval: ${escapeHtml(r.auto_staged_approval_request_id)}</div>` : ''}`;
    } catch (e) { out.innerHTML = `<span style="color:#f87171">${escapeHtml(e.message)}</span>`; }
  };
  const blockBtn = root.querySelector('[data-rc-block]');
  if (blockBtn) blockBtn.onclick = async () => {
    const indicator = root.querySelector('#rc-ioc')?.value || '';
    const indicator_type = root.querySelector('#rc-ioc-type')?.value || 'ip';
    try {
      await api('/api/response/ioc/block', { method: 'POST', body: JSON.stringify({ indicator, indicator_type }) });
      updateTelemetryConsole(`[RESPONSE] blocked ${indicator}`, 'text-emerald-400');
      refreshOpsTab();
    } catch (e) { updateTelemetryConsole(`[RESPONSE ERROR] ${e.message}`, 'text-red-400'); }
  };

  const isolateBtn = root.querySelector('[data-rc-isolate]');
  if (isolateBtn) isolateBtn.onclick = async () => {
    const target = root.querySelector('#rc-isolate-target')?.value || '';
    const reason = root.querySelector('#rc-isolate-reason')?.value || '';
    const out = root.querySelector('#rc-isolate-result');
    try {
      const r = await api('/api/response/isolate-host', { method: 'POST', body: JSON.stringify({ target, reason }) });
      out.innerHTML = `<span style="color:#34d399">Staged — approval_request_id=${escapeHtml(r.approval_request_id)}. Approve it in the Approval tab, then Enforce from the list below.</span>`;
      refreshOpsTab();
    } catch (e) { out.innerHTML = `<span style="color:#f87171">${escapeHtml(e.message)}</span>`; }
  };

  root.querySelectorAll('[data-rc-enforce]').forEach((b) => {
    b.onclick = async () => {
      const approvalRequestId = b.getAttribute('data-rc-enforce');
      try {
        const r = await api(`/api/response/actions/${approvalRequestId}/enforce`, { method: 'POST' });
        updateTelemetryConsole(
          `[RESPONSE] enforce ${approvalRequestId} -> ${r.status} via ${r.connector}`,
          r.status === 'enforced' ? 'text-emerald-400' : 'text-yellow-400',
        );
        refreshOpsTab();
      } catch (e) { updateTelemetryConsole(`[ENFORCE ERROR] ${e.message}`, 'text-red-400'); }
    };
  });
}

async function renderScriptLibraryPanel() {
  const [stats, list] = await Promise.all([
    api('/api/cheatsheet/scripts/stats').catch(() => ({})),
    api('/api/cheatsheet/scripts').catch(() => ({ scripts: [] })),
  ]);
  const rows = (list.scripts || []).slice(0, 30).map((s) => `
    <div style="${cardStyle()};border-left:3px solid ${RISK_COLOR[s.risk_level] || '#6b7280'}">
      <div style="display:flex;justify-content:space-between"><b>${escapeHtml(s.title)}</b><span style="opacity:.7">${escapeHtml(s.risk_level)}</span></div>
      <div style="opacity:.75;font-size:11px;margin-top:2px">${escapeHtml(s.phase_label)} · ${escapeHtml(s.language)} · ${s.line_count} lines</div>
      <div style="opacity:.6;font-size:11px;margin-top:2px">${escapeHtml(s.description || '')}</div>
      <button type="button" data-stage-script="${escapeHtml(s.id)}" style="${btnStyle('#1d4ed8')};margin-top:6px">Stage for execution</button>
    </div>`).join('');
  return `
    <h3 style="color:#f97316;margin:0 0 8px">CheatSheet Script Library</h3>
    <div style="${cardStyle()}">${stats.total_scripts ?? 0} real scripts indexed from gacyber_toolkit/ · ${Object.entries(stats.by_risk || {}).map(([k, v]) => `${k}:${v}`).join(' ')}</div>
    <div style="${cardStyle()}">
      <b>Stage target</b> (used for whichever script you click "Stage for execution" on)
      <input id="sl-target" placeholder="target (must be in an active authorized scope)" style="width:100%;margin-top:6px;padding:6px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff">
      <div id="sl-stage-result" style="margin-top:6px;font-size:11px"></div>
    </div>
    ${rows}
  `;
}

function wireScriptLibraryActions(root) {
  root.querySelectorAll('[data-stage-script]').forEach((b) => {
    b.onclick = async () => {
      const scriptId = b.getAttribute('data-stage-script');
      const target = root.querySelector('#sl-target')?.value || '';
      const out = root.querySelector('#sl-stage-result');
      try {
        const r = await api(`/api/cheatsheet/scripts/${scriptId}/stage`, { method: 'POST', body: JSON.stringify({ target }) });
        out.innerHTML = `<span style="color:#34d399">Staged — approval_request_id=${escapeHtml(r.approval_request_id)} (risk=${escapeHtml(r.risk_level)}). Approve it in the Approval tab, then run via /cheatsheet/scripts/${escapeHtml(scriptId)}/run-in-sandbox.</span>`;
      } catch (e) { out.innerHTML = `<span style="color:#f87171">${escapeHtml(e.message)}</span>`; }
    };
  });
}

// ─────────────────────────────────────────────────────────────────────────
// v2.7 — Purpose-built widgets for the pages that were a raw JSON panel
// ─────────────────────────────────────────────────────────────────────────

function gaugeSvg(pct, color, label) {
  const p = Math.max(0, Math.min(100, pct));
  const r = 42, c = 2 * Math.PI * r;
  return `<svg width="110" height="110" viewBox="0 0 110 110" style="flex-shrink:0">
    <circle cx="55" cy="55" r="${r}" fill="none" stroke="#1f2937" stroke-width="10"/>
    <circle cx="55" cy="55" r="${r}" fill="none" stroke="${color}" stroke-width="10" stroke-linecap="round"
      stroke-dasharray="${c}" stroke-dashoffset="${c - (p / 100) * c}" transform="rotate(-90 55 55)"/>
    <text x="55" y="52" text-anchor="middle" fill="#fff" font-size="20" font-weight="700" font-family="ui-monospace,monospace">${Math.round(p)}%</text>
    <text x="55" y="70" text-anchor="middle" fill="#9ca3af" font-size="9">${escapeHtml(label)}</text>
  </svg>`;
}

async function renderEnergyCoreWidget() {
  let data;
  try { data = await api('/api/qaip/energy-core/status'); } catch (e) { return `<div style="${cardStyle()};color:#f87171">${escapeHtml(e.message)}</div>`; }
  const pct = Math.round((data.utilization_pct ?? data.throttle_pct ?? data.usage_pct ?? 0));
  return `<div style="${cardStyle()};display:flex;gap:16px;align-items:center">
      ${gaugeSvg(pct, pct > 85 ? '#f87171' : pct > 60 ? '#fbbf24' : '#34d399', 'THROTTLE')}
      <div style="flex:1"><b style="color:#f97316">Energy Core</b>
        <pre style="font-size:11px;margin-top:8px;white-space:pre-wrap">${escapeHtml(JSON.stringify(data, null, 2).slice(0, 900))}</pre>
      </div>
    </div>`;
}

async function renderInferenceLedgerWidget(title) {
  let data;
  try { data = await api('/api/qaip/orbital-comms/stats'); } catch (e) { return `<div style="${cardStyle()};color:#f87171">${escapeHtml(e.message)}</div>`; }
  const entries = Object.entries(data).filter(([k]) => k !== 'error');
  const rows = entries.map(([k, v]) => `
    <tr style="border-bottom:1px solid #1f2937"><td style="padding:6px;opacity:.75">${escapeHtml(k)}</td>
      <td style="padding:6px;text-align:right;font-family:ui-monospace,monospace">${escapeHtml(typeof v === 'object' ? JSON.stringify(v) : v)}</td></tr>`).join('');
  return `<div style="${cardStyle()}"><b style="color:#f97316">${escapeHtml(title)}</b>
    <table style="width:100%;margin-top:8px;font-size:12px"><tbody>${rows || '<tr><td style="padding:6px;opacity:.6">No ledger entries yet.</td></tr>'}</tbody></table></div>`;
}

async function renderAutomationSettingsWidget() {
  const [policyData, snapshot] = await Promise.all([
    api('/api/resonance/automation-settings').catch((e) => ({ error: e.message, policy: [] })),
    api('/api/resonance/settings').catch(() => null),
  ]);

  const policyRows = (policyData.policy || []).map((p) => {
    const inputId = `policy-input-${p.policy_key}`;
    let control;
    if (p.value_type === 'bool') {
      control = `<button type="button" data-policy-toggle="${escapeHtml(p.policy_key)}" data-current="${p.value}"
        style="${btnStyle(p.value ? '#065f46' : '#374151')};min-width:56px">${p.value ? 'ON' : 'OFF'}</button>`;
    } else {
      control = `<div style="display:flex;gap:6px;align-items:center">
        <input id="${inputId}" type="number" step="any" value="${escapeHtml(p.value)}"
          style="width:90px;padding:4px 8px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff;font-size:12px">
        <button type="button" data-policy-save="${escapeHtml(p.policy_key)}" data-input="${inputId}" style="${btnStyle('#1d4ed8')}">Save</button>
      </div>`;
    }
    return `<div style="padding:10px 0;border-bottom:1px solid #1f2937">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:12px">
        <div><b style="font-size:12.5px">${escapeHtml(p.label || p.policy_key)}</b>
          <div style="opacity:.6;font-size:10.5px;font-family:ui-monospace,monospace">${escapeHtml(p.policy_key)}</div></div>
        ${control}
      </div>
      <div style="opacity:.65;font-size:11px;margin-top:6px;line-height:1.4">${escapeHtml(p.description || '')}</div>
      ${p.updated_by ? `<div style="opacity:.5;font-size:10px;margin-top:4px">last changed by ${escapeHtml(p.updated_by)} · ${escapeHtml(p.updated_at)}</div>` : ''}
    </div>`;
  }).join('');

  const rbacHash = snapshot?.rbac_policy_hash ? String(snapshot.rbac_policy_hash).slice(0, 16) + '…' : '—';

  return `<div style="${cardStyle()}">
      <b style="color:#f97316">Resonance Wave Automation</b>
      <p style="opacity:.7;font-size:11px;margin:6px 0 0">Real, write-controlled automation knobs — each one is read by a real
        enforcement point (Detection &amp; Response triage, the Trade Secrets vault, the script catalog), not decorative.
        Requires the <code style="background:#111827;padding:1px 5px;border-radius:4px">response:manage</code> permission to change.</p>
      <div id="policy-save-msg" style="margin-top:8px;font-size:11px"></div>
      <div style="margin-top:4px">${policyRows || '<p style="opacity:.6;font-size:11px">No policy loaded.</p>'}</div>
    </div>
    <div style="${cardStyle()}">
      <b style="opacity:.8;font-size:12px">Derived security-settings snapshot (read-only, by design)</b>
      <p style="opacity:.6;font-size:10.5px;margin:4px 0 8px">Computed fresh from the real operators/encryption_keys/pqc_audit_log
        tables — never independently editable, so it can't drift from what's actually enforced.</p>
      <div style="font-size:11px;opacity:.8">RBAC policy hash: <span style="font-family:ui-monospace,monospace">${escapeHtml(rbacHash)}</span></div>
      <div style="font-size:11px;opacity:.8;margin-top:2px">${escapeHtml(snapshot?.key_management_status || '—')}</div>
    </div>`;
}

function wireAutomationSettingsActions(root) {
  root.querySelectorAll('[data-policy-toggle]').forEach((b) => {
    b.onclick = async () => {
      const key = b.getAttribute('data-policy-toggle');
      const newValue = b.getAttribute('data-current') !== 'true';
      const msg = root.querySelector('#policy-save-msg');
      try {
        await api(`/api/resonance/automation-settings/${key}`, { method: 'POST', body: JSON.stringify({ value: newValue }) });
        if (msg) msg.innerHTML = `<span style="color:#34d399">Saved ${escapeHtml(key)} = ${newValue}.</span>`;
        root.innerHTML = await renderAutomationSettingsWidget();
        wireAutomationSettingsActions(root);
      } catch (e) { if (msg) msg.innerHTML = `<span style="color:#f87171">${escapeHtml(e.message)}</span>`; }
    };
  });
  root.querySelectorAll('[data-policy-save]').forEach((b) => {
    b.onclick = async () => {
      const key = b.getAttribute('data-policy-save');
      const inputId = b.getAttribute('data-input');
      const raw = root.querySelector(`#${inputId}`)?.value;
      const value = Number(raw);
      const msg = root.querySelector('#policy-save-msg');
      if (Number.isNaN(value)) { if (msg) msg.innerHTML = '<span style="color:#f87171">Not a number.</span>'; return; }
      try {
        await api(`/api/resonance/automation-settings/${key}`, { method: 'POST', body: JSON.stringify({ value }) });
        if (msg) msg.innerHTML = `<span style="color:#34d399">Saved ${escapeHtml(key)} = ${value}.</span>`;
      } catch (e) { if (msg) msg.innerHTML = `<span style="color:#f87171">${escapeHtml(e.message)}</span>`; }
    };
  });
}

async function renderOntologyGraphWidget() {
  let data;
  try { data = await api('/api/cheatsheet/graph'); } catch (e) { return `<div style="${cardStyle()};color:#f87171">${escapeHtml(e.message)}</div>`; }
  const objects = data.objects || [];
  const phases = objects.filter((o) => o.type === 'Phase');
  const cats = objects.filter((o) => o.type === 'Category');
  const nodes = [...phases, ...cats].slice(0, 24);
  const cols = 6;
  const chips = nodes.map((n, i) => {
    const color = n.type === 'Phase' ? '#7c3aed' : '#0e7490';
    return `<span style="display:inline-block;margin:3px;padding:4px 10px;border-radius:999px;background:${color}22;border:1px solid ${color};color:${color};font-size:11px">${escapeHtml(n.label || n.id)}</span>`;
  }).join('');
  return `<div style="${cardStyle()}"><b style="color:#f97316">Ontology &amp; Simulation Hub</b>
    <div style="opacity:.7;font-size:11px;margin:6px 0">${phases.length} phases · ${cats.length} categories · ${(data.links || []).length} links</div>
    <div>${chips}</div></div>`;
}

async function renderQuantumNexusWidget() {
  let data;
  try { data = await api('/api/qaip/orbital-comms'); } catch (e) { return `<div style="${cardStyle()};color:#f87171">${escapeHtml(e.message)}</div>`; }
  const events = Array.isArray(data) ? data : (data.events || data.comms || []);
  const rows = events.slice(0, 12).map((e) => `
    <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #1f2937;font-size:11px">
      <span>${escapeHtml(e.event_type || e.comm_type || 'event')}</span>
      <span style="opacity:.6">${escapeHtml(e.timestamp || e.created_at || '')}</span>
    </div>`).join('');
  return `<div style="${cardStyle()}"><b style="color:#f97316">Quantum Orbital &amp; Event Comms</b>
    <div style="margin-top:6px">${rows || '<p style="opacity:.6;font-size:11px">No orbital comms events yet.</p>'}</div></div>`;
}

async function renderPredictiveCommandWidget() {
  let data;
  try { data = await api('/api/ares/global-matrix-summary'); } catch (e) { return `<div style="${cardStyle()};color:#f87171">${escapeHtml(e.message)}</div>`; }
  const cards = Object.entries(data).filter(([k, v]) => typeof v !== 'object').map(([k, v]) => `
    <div style="${cardStyle()}"><div style="opacity:.7;font-size:11px">${escapeHtml(k)}</div>
      <div style="font-size:20px;font-weight:700;color:#f97316;font-family:ui-monospace,monospace">${escapeHtml(v)}</div></div>`).join('');
  return `<div><b style="color:#f97316">Predictive Command — Ares rollup</b>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-top:8px">${cards || '<p style="opacity:.6;font-size:11px">No rollup data yet.</p>'}</div></div>`;
}

async function renderLoadMonitorWidget() {
  let data;
  try { data = await api('/api/resonance/fleet'); } catch (e) { return `<div style="${cardStyle()};color:#f87171">${escapeHtml(e.message)}</div>`; }
  const hosts = Array.isArray(data) ? data : (data.hosts || data.fleet || []);
  const avgLoad = hosts.length
    ? Math.round(hosts.reduce((s, h) => s + (Number(h.load_pct ?? h.cpu_pct ?? 0)), 0) / hosts.length) : 0;
  const rows = hosts.slice(0, 10).map((h) => `
    <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #1f2937;font-size:11px">
      <span>${escapeHtml(h.name || h.host_id || 'host')}</span><span style="opacity:.7">${escapeHtml(h.load_pct ?? h.cpu_pct ?? h.status ?? '')}</span>
    </div>`).join('');
  return `<div style="${cardStyle()};display:flex;gap:16px;align-items:center">
    ${gaugeSvg(avgLoad, avgLoad > 85 ? '#f87171' : avgLoad > 60 ? '#fbbf24' : '#34d399', 'FLEET LOAD')}
    <div style="flex:1"><b style="color:#f97316">Resonance Load Monitor</b>
      <div style="margin-top:8px">${rows || '<p style="opacity:.6;font-size:11px">No fleet hosts reported yet.</p>'}</div></div></div>`;
}

async function renderInvestigationCanvasWidget() {
  let data;
  try { data = await api('/api/canvas/tasks'); } catch (e) { return `<div style="${cardStyle()};color:#f87171">${escapeHtml(e.message)}</div>`; }
  const tasks = Array.isArray(data) ? data : (data.tasks || []);
  const byStatus = { pending: [], in_progress: [], completed: [] };
  tasks.forEach((t) => { (byStatus[t.status] || (byStatus[t.status] = [])).push(t); });
  const col = (label, items, color) => `<div style="flex:1;min-width:140px">
    <div style="font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:${color};margin-bottom:6px">${label} (${items.length})</div>
    ${items.slice(0, 6).map((t) => `<div style="${cardStyle()};padding:8px 10px;font-size:11px">${escapeHtml(t.title || t.task_id || 'task')}</div>`).join('') || '<div style="opacity:.5;font-size:11px">—</div>'}
  </div>`;
  return `<div><b style="color:#f97316">Ontology Meta-Platform — Investigation Canvas</b>
    <div style="display:flex;gap:12px;margin-top:8px;overflow-x:auto">
      ${col('Pending', byStatus.pending || [], '#9ca3af')}
      ${col('In Progress', byStatus.in_progress || [], '#fbbf24')}
      ${col('Completed', byStatus.completed || [], '#34d399')}
    </div></div>`;
}

function wireOpsActions(root) {
  root.querySelectorAll('[data-export]').forEach((b) => {
    b.onclick = async () => {
      try {
        const id = b.getAttribute('data-export');
        const rep = await api(`/api/reports/export/${id}?format=markdown`);
        updateTelemetryConsole(`[REPORT] ${JSON.stringify(rep).slice(0, 400)}`, 'text-emerald-400');
        alert((rep.content || JSON.stringify(rep)).slice(0, 1500));
      } catch (e) {
        updateTelemetryConsole(`[REPORT ERROR] ${e.message}`, 'text-red-400');
      }
    };
  });
  root.querySelectorAll('[data-approve]').forEach((b) => {
    b.onclick = async () => {
      const id = b.getAttribute('data-approve');
      try {
        await api(`/api/approval/${id}/approve`, {
          method: 'POST',
          body: JSON.stringify({ operator_id: 'system', reason: 'Live Ops approve' }),
        });
        updateTelemetryConsole(`[APPROVAL] approved ${id}`, 'text-emerald-400');
        refreshOpsTab();
      } catch (e) {
        updateTelemetryConsole(`[APPROVAL ERROR] ${e.message}`, 'text-red-400');
      }
    };
  });
  root.querySelectorAll('[data-deny]').forEach((b) => {
    b.onclick = async () => {
      const id = b.getAttribute('data-deny');
      try {
        await api(`/api/approval/${id}/deny`, {
          method: 'POST',
          body: JSON.stringify({ operator_id: 'system', reason: 'Live Ops deny' }),
        });
        updateTelemetryConsole(`[APPROVAL] denied ${id}`, 'text-yellow-400');
        refreshOpsTab();
      } catch (e) {
        updateTelemetryConsole(`[APPROVAL ERROR] ${e.message}`, 'text-red-400');
      }
    };
  });
  root.querySelectorAll('[data-qrun]').forEach((b) => {
    b.onclick = async () => {
      const circuit = b.getAttribute('data-qrun');
      try {
        const r = await runQuantumSimulation(circuit, 512);
        const box = el('jakal-q-result');
        if (box) box.textContent = JSON.stringify(r, null, 2);
      } catch (_) {}
    };
  });
}

/** Inject a live strip into the main content area for key pages */
async function injectPageLive(pageKey) {
  const area = el('content-area');
  if (!area) return;
  let host = el('jakal-page-live');
  if (host) host.remove();
  host = document.createElement('div');
  host.id = 'jakal-page-live';
  host.style.cssText = 'margin-bottom:16px';
  area.insertBefore(host, area.firstChild);

  try {
    if (pageKey === 'admin_fabric' || pageKey === 'admin_horizon_fabric') {
      host.innerHTML = await renderFabricPanel();
    } else if (pageKey === 'admin_diagnostics') {
      host.innerHTML = await renderDiagPanel();
    } else if (pageKey === 'admin_quantum_computer' || pageKey === 'admin_quantum_nexus') {
      host.innerHTML = await renderQuantumPanel();
      wireOpsActions(host);
    } else if (pageKey === 'admin_global_dashboard') {
      const [logs, reports, fabric] = await Promise.all([
        api('/api/agent/logs?limit=8').catch(() => ({ logs: [] })),
        api('/api/reports/list?limit=5').catch(() => []),
        api('/api/fabric/status').catch(() => null),
      ]);
      const score = fabric?.posture?.overall_score ?? '—';
      host.innerHTML = `
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:12px">
          <div style="${cardStyle()}"><div style="opacity:.7">Backend</div><div style="font-size:20px;font-weight:700;color:#34d399">ONLINE 2.5</div></div>
          <div style="${cardStyle()}"><div style="opacity:.7">Fabric posture</div><div style="font-size:20px;font-weight:700;color:#f97316">${escapeHtml(score)}</div></div>
          <div style="${cardStyle()}"><div style="opacity:.7">Recent pentests</div><div style="font-size:20px;font-weight:700">${(reports || []).length}</div></div>
        </div>
        <div style="${cardStyle()}"><b>Latest agent activity</b>
          <div style="margin-top:8px;font-family:ui-monospace,monospace;font-size:11px">
            ${(logs.logs || []).slice(0, 6).map((row) => {
              if (row && typeof row === 'object' && !Array.isArray(row)) {
                return `<div>${escapeHtml(row.timestamp)} · ${escapeHtml(row.event)} · ${escapeHtml(row.status)}</div>`;
              }
              return `<div>${escapeHtml(row[1])} · ${escapeHtml(row[2])} · ${escapeHtml(row[4])}</div>`;
            }).join('') || '<div style="opacity:.6">No logs yet — run a pentest.</div>'}
          </div>
          <button type="button" id="jakal-open-ops" style="${btnStyle('#0e7490');margin-top:10px}">Open Live Ops</button>
        </div>`;
      const btn = el('jakal-open-ops');
      if (btn) btn.onclick = () => toggleOpsDrawer(true);
    } else if (pageKey === 'admin_compliance') {
      try {
        const fw = await api('/api/compliance/axiom/frameworks');
        host.innerHTML = `<div style="${cardStyle()}"><b>Compliance frameworks (live)</b>
          <pre style="font-size:11px;margin-top:8px">${escapeHtml(JSON.stringify(fw, null, 2).slice(0, 1200))}</pre></div>`;
      } catch (e) {
        host.innerHTML = `<div style="${cardStyle()};color:#f87171">${escapeHtml(e.message)}</div>`;
      }
    } else if (pageKey === 'admin_energy_core') {
      host.innerHTML = await renderEnergyCoreWidget();
    } else if (pageKey === 'admin_logic_core') {
      host.innerHTML = await renderInferenceLedgerWidget("Q'AIP Logic Core Manager — inference ledger");
    } else if (pageKey === 'admin_model_chains') {
      host.innerHTML = await renderInferenceLedgerWidget('Model Chains & Inference — ledger');
    } else if (pageKey === 'admin_automation_controls') {
      host.innerHTML = await renderAutomationSettingsWidget();
      wireAutomationSettingsActions(host);
    } else if (pageKey === 'admin_ontology') {
      host.innerHTML = await renderOntologyGraphWidget();
    } else if (pageKey === 'admin_investigation_canvas') {
      host.innerHTML = await renderInvestigationCanvasWidget();
    } else if (pageKey === 'admin_quantum_nexus') {
      host.innerHTML = await renderQuantumNexusWidget();
    } else if (pageKey === 'admin_predictive_command') {
      host.innerHTML = await renderPredictiveCommandWidget();
    } else if (pageKey === 'admin_cognitive_load_monitor') {
      host.innerHTML = await renderLoadMonitorWidget();
    } else if (pageKey === 'admin_cheatsheet_library') {
      const [ontologyPanel, scriptPanel] = await Promise.all([renderCheatsheetPanelLive(), renderScriptLibraryPanel()]);
      host.innerHTML = ontologyPanel + scriptPanel;
      wireScriptLibraryActions(host);
    } else if (pageKey === 'admin_dark_web') {
      host.innerHTML = await renderDarkWebPanelLive();
      wireNewPanelActions(host);
    } else if (pageKey === 'admin_security_training') {
      host.innerHTML = await renderAwarenessPanelLive();
    } else if (pageKey === 'admin_phishing_sim') {
      host.innerHTML = await renderPhishingPanelLive();
    } else {
      host.remove();
    }
  } catch (e) {
    host.innerHTML = `<div style="${cardStyle()};color:#f87171">Live inject failed: ${escapeHtml(e.message)}</div>`;
  }
}

// switchSettingsSubTab() is a separate router from loadPage() (see
// renderGlobalSettingsTab in index.html) so it needs its own hook to
// overlay live data the same way injectPageLive() does for the main pages.
async function injectSettingsLive(tabKey) {
  const container = document.getElementById('settings-content-container');
  if (!container) return;
  let host = document.getElementById('jakal-settings-live');
  if (host) host.remove();
  host = document.createElement('div');
  host.id = 'jakal-settings-live';
  host.style.cssText = 'margin-bottom:16px';
  container.insertBefore(host, container.firstChild);
  try {
    if (tabKey === 'profile' || tabKey === 'login_encryption') {
      host.innerHTML = await renderAuthPanel();
      wireAuthPanel(host);
    } else if (tabKey === 'api_integration') {
      host.innerHTML = await renderApiIntegrationPanelLive();
      wireNewPanelActions(host);
    } else if (tabKey === 'eas_rd') {
      host.innerHTML = await renderEasRdPanelLive();
      wireNewPanelActions(host);
    } else if (tabKey === 'trade_secrets') {
      host.innerHTML = await renderVaultPanelLive();
    } else if (tabKey === 'rbac') {
      host.innerHTML = await renderRbacPanelLive();
    } else if (tabKey === 'auditing') {
      host.innerHTML = await renderAuditingPanelLive();
    } else if (tabKey === 'kms') {
      host.innerHTML = await renderSimpleJsonPanel('Encryption / Key Management', '/api/crypto/status');
    } else {
      host.remove();
    }
  } catch (e) {
    host.innerHTML = `<div style="${cardStyle()};color:#f87171">Live inject failed: ${escapeHtml(e.message)}</div>`;
  }
}

function hookSettingsSubTab() {
  if (window.__jakalSettingsHooked) return;
  const tryHook = () => {
    if (typeof window.switchSettingsSubTab !== 'function') return false;
    if (window.__jakalSettingsHooked) return true;
    const orig = window.switchSettingsSubTab.bind(window);
    window.switchSettingsSubTab = function (tab, shouldRerender = true) {
      const ret = orig(tab, shouldRerender);
      setTimeout(() => injectSettingsLive(tab), 150);
      return ret;
    };
    window.__jakalSettingsHooked = true;
    return true;
  };
  if (!tryHook()) {
    let n = 0;
    const t = setInterval(() => {
      n += 1;
      if (tryHook() || n > 40) clearInterval(t);
    }, 250);
  }
}

function hookLoadPage() {
  if (window.__jakalLoadHooked) return;
  const tryHook = () => {
    if (typeof window.loadPage !== 'function') return false;
    if (window.__jakalLoadHooked) return true;
    const orig = window.loadPage.bind(window);
    window.loadPage = function (pageKey) {
      const ret = orig(pageKey);
      setTimeout(() => injectPageLive(pageKey), 150);
      return ret;
    };
    window.__jakalLoadHooked = true;
    // Current view
    setTimeout(() => injectPageLive('admin_global_dashboard'), 300);
    return true;
  };
  if (!tryHook()) {
    let n = 0;
    const t = setInterval(() => {
      n += 1;
      if (tryHook() || n > 40) clearInterval(t);
    }, 250);
  }
}

export async function refreshHealth() {
  const badge = el('jakal-conn');
  const meta = el('jakal-meta');
  try {
    const h = await api('/health');
    if (badge) {
      badge.textContent = `ONLINE · ${h.version || '?'}`;
      badge.style.background = '#065f46';
      badge.style.color = '#a7f3d0';
    }
    if (meta) meta.textContent = `db=${h.database || '?'} · llm=${h.llm_engine || '?'} · ${h.status || ''}`;
    updateTelemetryConsole(`[HEALTH] ${JSON.stringify(h)}`, 'text-emerald-400');
    return h;
  } catch (e) {
    if (badge) {
      badge.textContent = 'OFFLINE';
      badge.style.background = '#7f1d1d';
      badge.style.color = '#fecaca';
    }
    if (meta) meta.textContent = e.message;
    updateTelemetryConsole(`[HEALTH ERROR] ${e.message}`, 'text-red-400');
    throw e;
  }
}

export async function seedAuthorization() {
  updateTelemetryConsole('[SEED] Adding demo scope + insurance…');
  try {
    const scope = await api('/api/scope/add', {
      method: 'POST',
      body: JSON.stringify({
        client_name: 'Demo Client',
        scope_definition: `${DEMO_TARGET},*.staging.client.com,203.0.113.0/24`,
        start_date: '2026-01-01T00:00:00',
        end_date: '2027-12-31T23:59:59',
        roe_document_path: null,
      }),
    });
    updateTelemetryConsole(`[SEED] scope_id=${scope.scope_id}`, 'text-emerald-400');
    const ins = await api('/api/insurance/add', {
      method: 'POST',
      body: JSON.stringify({
        policy_number: `DEMO-POL-${Date.now()}`,
        provider: 'Demo Underwriter',
        coverage_amount: 1000000,
        expiry: '2027-12-31T23:59:59',
      }),
    });
    updateTelemetryConsole(`[SEED] policy_id=${ins.policy_id}`, 'text-emerald-400');
    return { scope, ins };
  } catch (e) {
    updateTelemetryConsole(`[SEED ERROR] ${e.message}`, 'text-red-400');
    throw e;
  }
}

export async function runQuantumSimulation(algorithm = 'bell_state', shots = 1024) {
  updateTelemetryConsole(`[QUANTUM] submit circuit=${algorithm} shots=${shots}`);
  try {
    const result = await api('/api/quantum/submit', {
      method: 'POST',
      body: JSON.stringify({ circuit: algorithm, shots, backend: 'qiskit_aer' }),
    });
    updateTelemetryConsole(`[QUANTUM] job_id=${result.job_id}`, 'text-emerald-400');
    updateTelemetryConsole(`[QUANTUM] ${JSON.stringify(result.result).slice(0, 500)}`);
    return result;
  } catch (e) {
    updateTelemetryConsole(`[QUANTUM ERROR] ${e.message}`, 'text-red-400');
    throw e;
  }
}

export async function loadFabric() {
  updateTelemetryConsole('[FABRIC] GET /api/fabric/status');
  try {
    const data = await api('/api/fabric/status');
    const score = data?.posture?.overall_score ?? '?';
    const level = data?.posture?.overall_level ?? '';
    updateTelemetryConsole(`[FABRIC] score=${score} ${level} caps=${data?.capability_count ?? '?'}`, 'text-emerald-400');
    return data;
  } catch (e) {
    updateTelemetryConsole(`[FABRIC ERROR] ${e.message}`, 'text-red-400');
    throw e;
  }
}

export async function triggerAgentAction(_action, target = DEMO_TARGET) {
  return runDemoPentest(target);
}

export async function runDemoPentest(target = DEMO_TARGET) {
  updateTelemetryConsole(`[PENTEST] run target=${target}`);
  try {
    const data = await api('/api/pentest/run', {
      method: 'POST',
      body: JSON.stringify({
        target,
        scan_type: 'comprehensive',
        operator_id: 'system',
        include_quantum_panel: false,
      }),
    });
    updateTelemetryConsole(`[PENTEST] test_id=${data.test_id} status=${data.status}`, 'text-emerald-400');
    if (data.report_markdown) {
      updateTelemetryConsole(`[PENTEST] ${String(data.report_markdown).slice(0, 800)}`);
    }
    return data;
  } catch (e) {
    updateTelemetryConsole(`[PENTEST ERROR ${e.status || ''}] ${e.message}`, 'text-red-400');
    if (e.status === 403) {
      updateTelemetryConsole('[HINT] Click Seed auth, then retry.', 'text-yellow-400');
    }
    throw e;
  }
}

export function startTelemetryStream() {
  if (window.__telemetryEventSource) {
    try { window.__telemetryEventSource.close(); } catch (_) {}
    window.__telemetryEventSource = null;
  }
  let retryDelay = 1000;
  function connect() {
    const url = `${BACKEND_BASE}/api/telemetry/stream`;
    const es = new EventSource(url);
    window.__telemetryEventSource = es;
    es.onopen = () => {
      updateTelemetryConsole('[SSE] telemetry connected', 'text-emerald-400');
      retryDelay = 1000;
    };
    es.onmessage = (evt) => {
      try {
        const log = JSON.parse(evt.data);
        updateTelemetryConsole(log.message || evt.data, log.level_color || 'text-gray-300');
      } catch {
        updateTelemetryConsole(evt.data, 'text-gray-300');
      }
    };
    es.onerror = () => {
      try { es.close(); } catch (_) {}
      setTimeout(connect, retryDelay);
      retryDelay = Math.min(Math.round(retryDelay * 1.8), 30000);
    };
  }
  connect();
}

export function wireIntegrationButtons() {
  document.querySelectorAll('[data-agent-action]').forEach((btn) => {
    btn.addEventListener('click', () => {
      runDemoPentest(btn.dataset.target || DEMO_TARGET).catch(() => {});
    });
  });
  document.querySelectorAll('[data-quantum-sim]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const algorithm = btn.dataset.quantumAlgorithm || btn.dataset.quantumSim || 'bell_state';
      const shots = parseInt(btn.dataset.shots || '512', 10);
      runQuantumSimulation(algorithm, shots).catch(() => {});
    });
  });
}

export async function startIntegration() {
  ensurePanel();
  hookLoadPage();
  hookSettingsSubTab();
  const baseLabel = BACKEND_BASE === '' ? window.location.origin : BACKEND_BASE;
  updateTelemetryConsole(`Integration → ${baseLabel}`, 'text-emerald-400');
  try {
    await refreshHealth();
    // Seed once per browser session to avoid spam
    if (!sessionStorage.getItem('jakal_seeded')) {
      await seedAuthorization().catch(() => {});
      sessionStorage.setItem('jakal_seeded', '1');
    }
    startTelemetryStream();
    wireIntegrationButtons();
    loadFabric().catch(() => {});
  } catch (e) {
    updateTelemetryConsole('[BOOT] Backend not reachable on port 8000.', 'text-red-400');
  }
}

if (typeof window !== 'undefined') {
  const boot = () => startIntegration().catch(() => {});
  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    setTimeout(boot, 50);
  } else {
    window.addEventListener('load', boot);
  }
}
