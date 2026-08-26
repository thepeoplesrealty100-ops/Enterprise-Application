// integration.js — live JAKAL UI ↔ API bridge (v2.5)
// Prefer same-origin (UI served from :8000). Fall back to 127.0.0.1:8000.

export const BACKEND_BASE = (() => {
  const { hostname, port, protocol, origin } = window.location;
  const local = hostname === 'localhost' || hostname === '127.0.0.1';
  // UI served by FastAPI itself
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

function ensureConsole() {
  let c = el('telemetry-console');
  if (c) return c;
  c = document.createElement('div');
  c.id = 'telemetry-console';
  c.style.cssText = [
    'position:fixed', 'right:12px', 'bottom:40px', 'z-index:9998',
    'width:min(420px,92vw)', 'max-height:280px', 'overflow:auto',
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
    <button type="button" id="jakal-btn-health" style="${btnStyle()}">Refresh health</button>
    <button type="button" id="jakal-btn-seed" style="${btnStyle()}">Seed scope+insurance</button>
    <button type="button" id="jakal-btn-quantum" style="${btnStyle()}">Run quantum job</button>
    <button type="button" id="jakal-btn-fabric" style="${btnStyle()}">Fabric status</button>
    <button type="button" id="jakal-btn-pentest" style="${btnStyle('#b91c1c')}">Run pentest (${DEMO_TARGET})</button>
  `;

  document.body.prepend(bar);
  const app = el('app');
  if (app) app.style.paddingTop = '48px';

  el('jakal-btn-health').onclick = () => refreshHealth();
  el('jakal-btn-seed').onclick = () => seedAuthorization();
  el('jakal-btn-quantum').onclick = () => runQuantumSimulation('bell_state', 512);
  el('jakal-btn-fabric').onclick = () => loadFabric();
  el('jakal-btn-pentest').onclick = () => runDemoPentest();

  ensureConsole();
  return bar;
}

async function api(path, options = {}) {
  const url = `${BACKEND_BASE}${path}`;
  const res = await fetch(url, {
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
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
    if (meta) {
      meta.textContent = `db=${h.database || '?'} · llm=${h.llm_engine || '?'} · ${h.status || ''}`;
    }
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
    updateTelemetryConsole(`[SEED] Ready — pentest target ${DEMO_TARGET}`);
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
    const score = data?.posture?.overall_score ?? data?.overall_score ?? '?';
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
      updateTelemetryConsole('[HINT] Click Seed scope+insurance, then retry.', 'text-yellow-400');
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
  const baseLabel = BACKEND_BASE === '' ? window.location.origin : BACKEND_BASE;
  updateTelemetryConsole(`Integration → ${baseLabel}`, 'text-emerald-400');
  try {
    await refreshHealth();
    await seedAuthorization().catch(() => {});
    startTelemetryStream();
    wireIntegrationButtons();
    loadFabric().catch(() => {});
  } catch (e) {
    updateTelemetryConsole(`[BOOT] Backend not reachable. Is docker compose up on port 8000?`, 'text-red-400');
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
