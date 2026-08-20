// integration.js
// Frontend <> Backend integration helpers (module)

// Base backend URL (update for deployed backend)
export const BACKEND_BASE = (() => {
  return (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8000'
    : 'https://your-backend.example.com'; // REPLACE in production
})();

// 1) Agent action POST
export async function triggerAgentAction(action, target) {
  try {
    const res = await fetch(`${BACKEND_BASE}/api/pentest/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, target })
    });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`Agent action failed: ${res.status} ${txt}`);
    }
    const data = await res.json();
    updateTelemetryConsole(`[AGENT] ${action} → ${data.status || 'enqueued'}`);
    return data;
  } catch (err) {
    console.error('triggerAgentAction error', err);
    updateTelemetryConsole(`[ERROR] Agent action failed: ${err.message}`, 'text-red-400');
    throw err;
  }
}

// 2) Quantum simulation trigger
export async function runQuantumSimulation(algorithm = 'bell_state', shots = 1024) {
  try {
    const res = await fetch(`${BACKEND_BASE}/api/quantum/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ algorithm, shots })
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`Quantum simulate failed: ${res.status} ${t}`);
    }
    const result = await res.json();
    updateQuantumQueueTable(result);
    updateTelemetryConsole(`[QUANTUM] ${algorithm} completed`);
    return result;
  } catch (err) {
    console.error('runQuantumSimulation error', err);
    updateTelemetryConsole(`[ERROR] Quantum simulation failed: ${err.message}`, 'text-red-400');
    throw err;
  }
}

// 3) Telemetry SSE with reconnect/backoff
export function startTelemetryStream() {
  if (window.__telemetryEventSource) {
    try { window.__telemetryEventSource.close(); } catch(e) {}
    window.__telemetryEventSource = null;
  }

  let retryDelay = 1000;
  function connect() {
    const url = `${BACKEND_BASE}/api/telemetry/stream`;
    const es = new EventSource(url);
    window.__telemetryEventSource = es;

    es.onopen = () => {
      console.debug('Telemetry SSE open');
      retryDelay = 1000;
    };

    es.onmessage = (evt) => {
      try {
        const log = JSON.parse(evt.data);
        const timestamp = log.timestamp || new Date().toLocaleTimeString();
        const message = `[${timestamp}] ${log.message || evt.data}`;
        updateTelemetryConsole(message, log.level_color || 'text-gray-300');
      } catch (e) {
        updateTelemetryConsole(evt.data, 'text-gray-300');
      }
    };

    es.onerror = (err) => {
      console.warn('Telemetry SSE error - reconnecting', err);
      try { es.close(); } catch(e){}
      setTimeout(connect, retryDelay);
      retryDelay = Math.min(Math.round(retryDelay * 1.8), 30000);
    };
  }
  connect();
}

// UI helper: append to a telemetry container (creates one inside content-area if none)
export function updateTelemetryConsole(text, colorClass = 'text-gray-300') {
  let container = document.querySelector('#telemetry-console');
  if (!container) {
    container = document.createElement('div');
    container.id = 'telemetry-console';
    container.className = 'fixed right-4 bottom-12 max-h-64 w-96 overflow-y-auto p-3 scrollbar-style bg-gray-900/60 rounded';
    document.body.appendChild(container);
  }
  const el = document.createElement('div');
  el.className = `${colorClass} text-sm mb-1`;
  el.innerText = text;
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
}

// UI helper: show quantum result
export function updateQuantumQueueTable(result) {
  let container = document.querySelector('#quantum-results');
  if (!container) {
    container = document.createElement('div');
    container.id = 'quantum-results';
    container.className = 'fixed left-4 bottom-12 max-h-64 w-96 overflow-y-auto p-3 scrollbar-style bg-gray-900/60 rounded';
    document.body.appendChild(container);
  }
  const pre = document.createElement('pre');
  pre.className = 'text-xs text-gray-300';
  pre.innerText = JSON.stringify(result, null, 2);
  container.appendChild(pre);
  container.scrollTop = container.scrollHeight;
}

// Small wiring helpers (scan for buttons with data attributes)
export function wireIntegrationButtons() {
  document.querySelectorAll('[data-agent-action]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const action = btn.dataset.agentAction;
      const target = btn.dataset.target || null;
      triggerAgentAction(action, target).catch(()=>{});
    });
  });

  document.querySelectorAll('[data-quantum-sim]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const algorithm = btn.dataset.quantumAlgorithm || btn.dataset.quantumSim || 'bell_state';
      const shots = parseInt(btn.dataset.shots || '1024', 10);
      runQuantumSimulation(algorithm, shots).catch(()=>{});
    });
  });
}

// Expose a start function to begin SSE and wiring after page load
export function startIntegration() {
  try {
    startTelemetryStream();
    wireIntegrationButtons();
    updateTelemetryConsole('Integration helpers started', 'text-emerald-400');
  } catch (e) {
    console.error('startIntegration failed', e);
  }
}

// Auto-start integration when running on localhost for convenience
if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
  window.addEventListener('load', () => {
    // Dynamically import to keep module boundaries
    import('./integration.js').then(mod => {
      if (mod.startIntegration) mod.startIntegration();
    }).catch(()=>{});
  });
}
