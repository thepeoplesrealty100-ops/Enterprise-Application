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
    wireOpsActions(body);
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
      return `<div style="${cardStyle()}">
        <b>Signed in as ${escapeHtml(me.username)}</b>
        <div style="opacity:.75;margin-top:4px">Roles: ${(me.roles || []).join(', ') || 'none'}</div>
        <div style="opacity:.75">Permissions: ${(me.permissions || []).join(', ') || 'none'}</div>
        <button type="button" data-iam-logout style="${btnStyle('#7f1d1d')};margin-top:8px">Sign out</button>
      </div>`;
    } catch (e) {
      setAuthToken('');
    }
  }
  return `<div style="${cardStyle()}">
    <b>Operator Sign-in</b>
    <p style="opacity:.75;font-size:11px;margin:4px 0 8px">First account created on a fresh install becomes root admin automatically.</p>
    <input id="iam-username" placeholder="username" style="width:100%;margin-bottom:6px;padding:6px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff">
    <input id="iam-password" type="password" placeholder="password (12+ chars)" style="width:100%;margin-bottom:8px;padding:6px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff">
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
    try {
      const r = await api('/api/iam/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) });
      if (r.mfa_required) { msg('MFA required — this UI does not collect a TOTP code yet; use POST /api/iam/auth/login with totp_code via /docs.', false); return; }
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
  const [watch, findings] = await Promise.all([
    api('/api/darkweb/watchlist').catch(() => ({ watchlist: [] })),
    api('/api/darkweb/findings').catch(() => ({ findings: [] })),
  ]);
  const wRows = (watch.watchlist || []).map((w) => `<div style="${cardStyle()}">${escapeHtml(w.identifier)} <span style="opacity:.6">(${escapeHtml(w.identifier_type)})</span></div>`).join('');
  const fRows = (findings.findings || []).map((f) => `<div style="${cardStyle()};border-left:3px solid #fbbf24"><b>${escapeHtml(f.breach_name || f.source)}</b> · ${escapeHtml(f.severity)}</div>`).join('');
  return `<div style="${cardStyle()}"><b>Dark Web Monitoring (live)</b>
    <div style="opacity:.7;font-size:11px;margin-top:4px">HIBP connector ${watch.watchlist?.length ? '' : '— add an identifier to the watchlist to begin.'}</div>
    <input id="darkweb-identifier" placeholder="email to watch" style="width:100%;margin:8px 0;padding:6px;border-radius:6px;border:1px solid #4b5563;background:#111827;color:#fff">
    <div style="display:flex;gap:6px">
      <button type="button" data-darkweb-add style="${btnStyle('#1d4ed8')};flex:1">Add to watchlist</button>
      <button type="button" data-darkweb-scan style="${btnStyle('#166534')};flex:1">Run scan</button>
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
      host.innerHTML = await renderSimpleJsonPanel('Energy Core Status', '/api/qaip/energy-core/status');
    } else if (pageKey === 'admin_logic_core' || pageKey === 'admin_model_chains') {
      host.innerHTML = await renderSimpleJsonPanel("Q'AIP Inference Ledger", '/api/qaip/orbital-comms/stats');
    } else if (pageKey === 'admin_automation_controls') {
      host.innerHTML = await renderSimpleJsonPanel('Resonance Wave Automation (org security settings)', '/api/resonance/settings');
    } else if (pageKey === 'admin_ontology' || pageKey === 'admin_investigation_canvas') {
      host.innerHTML = await renderSimpleJsonPanel('Ontology & Simulation Hub', '/api/aip/ontology');
    } else if (pageKey === 'admin_quantum_nexus') {
      host.innerHTML = await renderSimpleJsonPanel('Quantum Orbital & Event Comms', '/api/qaip/orbital-comms');
    } else if (pageKey === 'admin_predictive_command') {
      host.innerHTML = await renderSimpleJsonPanel('Predictive Command (Ares cross-pillar rollup)', '/api/ares/global-matrix-summary');
    } else if (pageKey === 'admin_cognitive_load_monitor') {
      host.innerHTML = await renderSimpleJsonPanel('Resonance Load Monitor (fleet posture)', '/api/resonance/fleet');
    } else if (pageKey === 'admin_dark_web') {
      host.innerHTML = await renderDarkWebPanelLive();
      wireNewPanelActions(host);
    } else if (pageKey === 'admin_security_training') {
      host.innerHTML = await renderAwarenessPanelLive();
    } else if (pageKey === 'admin_phishing_sim') {
      host.innerHTML = await renderPhishingPanelLive();
    } else if (pageKey === 'admin_cheatsheet_library') {
      host.innerHTML = await renderCheatsheetPanelLive();
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
