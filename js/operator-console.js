/**
 * js/operator-console.js — JAKAL Operator Console (v3.0)
 *
 * A high-end operator surface modeled on the JAKAL design: a dockable,
 * movable, resizable console with a CHAT/PROMPT area, slash-commands and
 * sandbox execution, plus an integrated SAFETY FABRIC side panel. HIGH-risk
 * actions stage an inline APPROVAL instead of executing. Raw HTML from a
 * failed backend is NEVER rendered here.
 *
 * Header controls: dock/float · minimize/expand · clear.
 * Public API: window.JAKAL.requestApproval({...}), window.JAKAL.console.*,
 *             window.JAKAL.log(msg, kind).
 *
 * Self-contained, no dependencies. Drop-in:
 *   <script src="./js/operator-console.js"></script>
 */
(function () {
  "use strict";

  var BASE = window.location.protocol === "file:" ? "http://localhost:8000" : window.location.origin;
  var LS = "jakal_operator_console_v3";
  var DEMO_TARGET = "staging.client.com";
  var mode = "unknown";                 // 'online' | 'offline' | 'unknown'
  var st = { history: [], histIdx: -1, collapsed: false, docked: true, seenAppr: {} };

  function el(id) { return document.getElementById(id); }
  function mk(tag, css, html) { var e = document.createElement(tag); if (css) e.style.cssText = css; if (html != null) e.innerHTML = html; return e; }
  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  function btn(bg) { return "cursor:pointer;border:1px solid #4b5563;background:" + (bg || "#1f2937") + ";color:#e5e7eb;border-radius:6px;padding:4px 9px;font-size:11px;font-weight:600"; }
  function save(o) { try { localStorage.setItem(LS, JSON.stringify(o)); } catch (e) {} }
  function load() { try { return JSON.parse(localStorage.getItem(LS) || "{}"); } catch (e) { return {}; } }
  function looksLikeHtml(t) { if (!t) return false; var h = t.slice(0, 400).toLowerCase(); return h.indexOf("<!doctype html") >= 0 || h.indexOf("<html") >= 0 || h.indexOf("site not found") >= 0 || h.indexOf("<head") >= 0; }

  // ── Hardened fetch: HTML / non-JSON / 404 -> clean bounded error ──────────
  function api(path, options) {
    options = options || {};
    if (mode === "offline") return Promise.reject(Object.assign(new Error("Live backend not connected (demo mode)."), { offline: true, status: 0 }));
    var headers = { Accept: "application/json" };
    if (options.body) headers["Content-Type"] = "application/json";
    return fetch(BASE + path, { method: options.method || "GET", headers: headers, body: options.body }).then(function (res) {
      var ctype = (res.headers.get("content-type") || "").toLowerCase();
      return res.text().then(function (text) {
        if (looksLikeHtml(text) || (ctype && ctype.indexOf("json") < 0)) {
          if (res.status === 404 || looksLikeHtml(text)) { mode = "offline"; badge(); }
          throw Object.assign(new Error("Backend returned a non-JSON " + res.status + " response."), { status: res.status });
        }
        var data = text ? JSON.parse(text) : null;
        if (!res.ok) { var d = data && (data.detail || data.message || data.error); if (d && typeof d !== "string") d = JSON.stringify(d); throw Object.assign(new Error(d || (res.status + " " + res.statusText)), { status: res.status, data: data }); }
        return data;
      });
    }, function (netErr) { mode = "offline"; badge(); throw Object.assign(new Error("Network error reaching backend: " + netErr.message), { offline: true, status: 0 }); });
  }

  function probe() {
    return fetch(BASE + "/health", { headers: { Accept: "application/json" }, cache: "no-store" }).then(function (res) {
      var ctype = (res.headers.get("content-type") || "").toLowerCase();
      return res.text().then(function (text) {
        if (!res.ok || looksLikeHtml(text) || ctype.indexOf("json") < 0) { mode = "offline"; return false; }
        try { var d = JSON.parse(text); if (d && (d.status || d.database)) { mode = "online"; return d; } } catch (e) {}
        mode = "offline"; return false;
      });
    }).catch(function () { mode = "offline"; return false; });
  }

  function badge() { var b = el("op-mode"); if (!b) return; var on = mode === "online"; b.textContent = on ? "live" : (mode === "offline" ? "demo" : "checking…"); b.style.background = on ? "#065f46" : "#374151"; b.style.color = on ? "#a7f3d0" : "#d1d5db"; }

  // ── Chat/log output ──────────────────────────────────────────────────────
  function line(role, text, kind) {
    var out = el("op-out"); if (!out) return;
    var row = mk("div", "margin:4px 0;white-space:pre-wrap;word-break:break-word;line-height:1.55");
    var colors = { out: "#cbd5e1", cmd: "#f97316", ok: "#34d399", err: "#f87171", muted: "#64748b", info: "#60a5fa", warn: "#fbbf24", system: "#94a3b8" };
    var MAX = 6000, t = String(text == null ? "" : text); if (t.length > MAX) t = t.slice(0, MAX) + " … (" + (t.length - MAX) + " more chars truncated)";
    if (role) { var tag = mk("span", "color:#475569;font-weight:700;margin-right:8px", null); tag.textContent = role; row.appendChild(tag); }
    var span = mk("span", "color:" + (colors[kind] || colors.out), null); span.textContent = t; row.appendChild(span);
    out.appendChild(row); while (out.children.length > 500) out.removeChild(out.firstChild); out.scrollTop = out.scrollHeight; return row;
  }
  function print(text, kind) { return line(null, text, kind); }
  function printJson(label, obj) { var pretty; try { pretty = JSON.stringify(obj, null, 2); } catch (e) { pretty = String(obj); } if (label) print(label, "info"); print(pretty, "out"); }

  // ── Floating approval gate (inline in the chat) ──────────────────────────
  function renderApprovalCard(opts) {
    ensure(); if (st.collapsed) toggleCollapse(false);
    var out = el("op-out"); if (!out) return;
    var risk = (opts.risk || "high").toLowerCase();
    var ring = risk === "critical" ? "#ef4444" : risk === "high" ? "#f59e0b" : "#3b82f6";
    var card = mk("div", "margin:8px 0;border:1px solid " + ring + ";border-left:4px solid " + ring + ";border-radius:10px;padding:10px 12px;background:rgba(30,41,59,.55)");
    var id = "appr_" + Math.random().toString(36).slice(2, 9);
    card.innerHTML =
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">' +
        '<span style="font-size:14px">🔐</span><strong style="color:#e5e7eb">' + esc(opts.title || "Approval required") + '</strong>' +
        '<span style="margin-left:auto;font-size:9px;text-transform:uppercase;letter-spacing:.05em;padding:1px 7px;border-radius:999px;background:' + ring + '33;color:' + ring + '">' + esc(risk) + '</span></div>' +
      (opts.detail ? '<div style="color:#94a3b8;font-size:11px;margin:4px 0 8px">' + esc(opts.detail) + '</div>' : '') +
      '<div style="display:flex;gap:8px"><button id="' + id + '_ok" style="' + btn("#059669") + ';flex:1">✓ Approve</button>' +
      '<button id="' + id + '_no" style="' + btn("#b91c1c") + ';flex:1">✕ Deny</button></div>';
    out.appendChild(card); out.scrollTop = out.scrollHeight;
    function resolve(ok) {
      var a = card.querySelector("#" + id + "_ok"), b = card.querySelector("#" + id + "_no");
      a.disabled = b.disabled = true; card.style.opacity = ".7";
      var tag = mk("div", "margin-top:6px;font-size:11px;color:" + (ok ? "#34d399" : "#f87171")); tag.textContent = ok ? "✓ Approved" : "✕ Denied"; card.appendChild(tag);
      try { (ok ? opts.onApprove : opts.onDeny) && (ok ? opts.onApprove : opts.onDeny)(); } catch (e) {}
    }
    el(id + "_ok").onclick = function () { resolve(true); };
    el(id + "_no").onclick = function () { resolve(false); };
  }

  function pollApprovals() {
    if (mode !== "online") return;
    api("/api/capabilities/pending").then(function (d) {
      (d.pending || []).forEach(function (a) {
        if (st.seenAppr[a.approval_id]) return; st.seenAppr[a.approval_id] = true;
        renderApprovalCard({ title: (a.action_id || "action") + " requires approval", risk: a.risk,
          detail: "Requested by " + (a.executor || "system") + " · " + (a.created_at || ""),
          onApprove: function () { api("/api/capabilities/approve/" + a.approval_id, { method: "POST" }).then(function (r) { printJson("approved:", r); }).catch(function (e) { print("[error] " + e.message, "err"); }); },
          onDeny: function () { api("/api/capabilities/deny/" + a.approval_id, { method: "POST" }).catch(function () {}); } });
      });
    }).catch(function () {});
  }

  // ── Command surface (chat + slash-commands) ──────────────────────────────
  var COMMANDS = {
    "/help": "Show operator commands",
    "/status": "Backend + fabric posture",
    "/fleet": "List managed devices (RMM)",
    "/caps": "Capability catalog (7 domains)",
    "/run": "/run <action_id> [k=v ...] — execute a capability (approval-gated)",
    "/isolate": "/isolate <HOST> — network-isolate an endpoint (CRITICAL)",
    "/scan": "/scan <target> — comprehensive pentest scan",
    "/yara": "/yara <path> — YARA memory/disk scan",
    "/patch": "/patch <agent> — CVE scan the endpoint",
    "/redact": "/redact <text> — Safety Fabric PII/secret redaction",
    "/inj": "/inj <text> — prompt-injection scan",
    "/quantum": "/quantum [algo] [shots] — submit a quantum circuit",
    "/clear": "Clear the console",
  };

  function parseKV(args) { var o = {}; args.forEach(function (a) { var i = a.indexOf("="); if (i > 0) { var k = a.slice(0, i), v = a.slice(i + 1); if (/^\d+$/.test(v)) v = parseInt(v, 10); else if (v === "true") v = true; else if (v === "false") v = false; o[k] = v; } }); return o; }

  function execCapability(actionId, payload) {
    api("/api/capabilities/execute", { method: "POST", body: JSON.stringify({ action_id: actionId, payload: payload, executor_id: "operator" }) }).then(function (r) {
      if (r.requires_approval) {
        st.seenAppr[r.approval_id] = true; print("Action " + actionId + " staged for approval.", "warn");
        renderApprovalCard({ title: r.prompt || (actionId + " requires approval"), risk: (r.action && r.action.risk) || "high", detail: actionId,
          onApprove: function () { api("/api/capabilities/approve/" + r.approval_id, { method: "POST" }).then(function (x) { printJson(actionId + " ->", x); }).catch(function (e) { print("[error] " + e.message, "err"); }); },
          onDeny: function () { api("/api/capabilities/deny/" + r.approval_id, { method: "POST" }).then(function () { print("denied.", "muted"); }); } });
      } else if (r.blocked) { print("[blocked by Safety Fabric] " + r.reason, "err"); printJson("guardrail:", r.guardrail); }
      else printJson(actionId + " ->", r);
    }).catch(function (e) { print("[error" + (e.status ? " " + e.status : "") + "] " + e.message, "err"); });
  }

  function run(raw) {
    line("you", raw, "cmd");
    var demo = mode !== "online";
    var slash = raw.charAt(0) === "/";
    var parts = raw.split(/\s+/), c = parts[0].toLowerCase(), args = parts.slice(1);
    var P = Promise.resolve();
    if (!slash) {
      if (demo) { print("(demo) I can run operator commands — type /help. Live actions need a connected backend.", "muted"); return; }
      // Free-text goes to the AI assistant, which can invoke REAL actions
      // (threat-intel, CVE scan, fleet, isolate, dark-web, SOAR). Runs in
      // intent-router mode with no key; upgrades to Claude tool-calling when
      // an Anthropic key is set in Integrations.
      print("thinking…", "muted");
      P = api("/api/capabilities/aisafety/scan", { method: "POST", body: JSON.stringify({ prompt: raw }) }).then(function (s) {
        if (s && s.safe === false) { print("⚠ Safety Fabric flagged this input. Not forwarded.", "warn"); return; }
        return api("/api/assistant/chat", { method: "POST", body: JSON.stringify({ message: raw, executor_id: "operator" }) }).then(function (r) {
          print(r.reply || "(no reply)", "info");
          (r.actions_taken || []).forEach(function (a) { printJson("↳ " + a.tool, a.result); });
          if (r.mode === "router") print("· intent-router mode — add an Anthropic key in Integrations for full AI chat.", "muted");
        });
      }).catch(function (e) { print("[error] " + e.message, "err"); });
      P.catch(function () {}); return;
    }
    switch (c) {
      case "/help":
        print("Operator commands:", "info");
        Object.keys(COMMANDS).forEach(function (k) { print("  " + (k + "         ").slice(0, 10) + " " + COMMANDS[k], "out"); });
        if (demo) print("\n(demo mode — sample output; connect a backend for live actions)", "muted");
        break;
      case "/clear": el("op-out").innerHTML = ""; break;
      case "/status":
        if (demo) { print("Backend: demo mode", "warn"); printJson("fabric (demo):", { posture: { overall_score: 82, overall_level: "Strong" }, capability_count: 7 }); break; }
        P = Promise.all([api("/health").catch(nn), api("/api/fabric/status").catch(nn)]).then(function (r) {
          if (r[0]) print("Backend ONLINE · v" + r[0].version + " · db=" + r[0].database + " · llm=" + r[0].llm_engine, "ok");
          if (r[1]) print("Fabric score=" + (r[1].posture ? r[1].posture.overall_score : "?") + " · " + r[1].capability_count + " capabilities", "ok");
        });
        break;
      case "/caps":
        if (demo) { print("7 domains: fleet_rmm, remote_access, detect_respond, soar_playbooks, patch_vulnerability, dark_web, ai_safety_fabric", "info"); break; }
        P = api("/api/capabilities/catalog").then(function (d) {
          print("Capability catalog — " + d.count + " actions:", "info");
          Object.keys(d.by_category).forEach(function (cat) { print("  " + cat + ":", "warn"); d.by_category[cat].forEach(function (a) { print("    " + a.id + "  [" + a.risk + "]  " + a.name, "out"); }); });
        });
        break;
      case "/run": { var id = args[0]; if (!id) { print("usage: /run <action_id> [k=v ...]", "muted"); break; } if (demo) { printJson("(demo) " + id, parseKV(args.slice(1))); break; } execCapability(id, parseKV(args.slice(1))); break; }
      case "/isolate": { var host = args[0] || "HOST"; if (demo) { printJson("(demo) isolate", { agent_id: host, isolation_status: true }); break; } execCapability("fleet:isolate_host", { agent_id: host, reason: "operator console" }); break; }
      case "/scan": { var tgt = args[0] || DEMO_TARGET; if (demo) { printJson("(demo) scan " + tgt, { findings: 3, top: ["T1190 exposed service", "weak TLS", "default creds"] }); break; } P = api("/api/pentest/run", { method: "POST", body: JSON.stringify({ target: tgt, scan_type: "comprehensive", operator_id: "console", include_quantum_panel: false }) }).then(function (r) { print("test_id=" + r.test_id + " status=" + r.status, "ok"); }); break; }
      case "/yara": { var path = args[0] || "/"; if (demo) { printJson("(demo) yara", { target: path, matches_found: 0, status: "clean" }); break; } execCapability("detect:scan_yara", { agent_id: args[1] || "host", target: path, rule_set: "default" }); break; }
      case "/patch": { if (demo) { printJson("(demo) cve scan", { critical: 0, high: 2 }); break; } execCapability("patch:scan_cve", { agent_id: args[0] || "host" }); break; }
      case "/redact": { var txt = raw.slice(raw.indexOf("/redact") + 7).trim(); if (demo) { print("(demo) redaction runs against the Safety Fabric endpoint when live.", "muted"); break; } P = api("/api/capabilities/aisafety/redact", { method: "POST", body: JSON.stringify({ text: txt }) }).then(j("redacted:")); break; }
      case "/inj": { var t2 = raw.slice(raw.indexOf("/inj") + 4).trim(); if (demo) { print("(demo) injection scan runs live.", "muted"); break; } P = api("/api/capabilities/aisafety/scan", { method: "POST", body: JSON.stringify({ prompt: t2 }) }).then(j("injection scan:")); break; }
      case "/quantum": { var a = args[0] || "bell_state", s = parseInt(args[1] || "512", 10); if (demo) { printJson("(demo) quantum", { circuit: a, shots: s, result: { "00": s / 2, "11": s / 2 } }); break; } P = api("/api/quantum/submit", { method: "POST", body: JSON.stringify({ circuit: a, shots: s, backend: "qiskit_aer" }) }).then(j("quantum:")); break; }
      case "/fleet":
        if (demo) { printJson("(demo) fleet", { devices: [{ hostname: "WIN-OPS-01", os: "Windows", status: "healthy" }, { hostname: "LNX-EDGE-04", os: "Linux", status: "patch-pending" }] }); break; }
        P = api("/api/dashboard/fleet").then(function (dd) { var rows = dd.data || dd.devices || dd.fleet || []; print("fleet (" + rows.length + " devices):", "info"); rows.forEach(function (x) { print("  " + ((x.name || x.hostname || "?") + "               ").slice(0, 15) + " " + ((x.ip || "") + "            ").slice(0, 15) + " " + (x.os || x.os_platform || "") + "  risk " + Math.round((x.risk || 0) * 100) + "%", "out"); }); });
        break;
      default: print('Unknown command: "' + c + '". Type /help.', "err");
    }
    P.catch(function (e) { print("[error" + (e.status ? " " + e.status : "") + "] " + e.message, "err"); if (e.status === 403) print('hint: seed authorization first.', "muted"); });
  }
  function j(label) { return function (o) { printJson(label, o); }; }
  function nn() { return null; }

  // ── Shell: dock/float, move, resize, minimize/expand ─────────────────────
  function applyDock() {
    var w = el("op-console"); if (!w) return;
    if (st.docked) {
      w.style.left = "12px"; w.style.right = "12px"; w.style.bottom = "12px"; w.style.top = "auto"; w.style.width = "auto";
      el("op-side").style.display = window.innerWidth > 900 ? "block" : "none";
      el("op-body").style.maxHeight = "min(42vh,340px)";
    } else {
      w.style.right = "auto"; w.style.width = "min(560px,94vw)";
      var s = load(); if (s.left && s.left !== "auto") { w.style.left = s.left; w.style.top = s.top || "90px"; w.style.bottom = "auto"; } else { w.style.left = "auto"; w.style.right = "12px"; w.style.bottom = "12px"; }
      el("op-side").style.display = "none";
      el("op-body").style.maxHeight = "min(46vh,380px)";
    }
    el("op-dock").textContent = st.docked ? "⤢ float" : "⤓ dock";
    save({ docked: st.docked, collapsed: st.collapsed, left: w.style.left, top: w.style.top });
  }
  function toggleCollapse(force) {
    st.collapsed = force != null ? force : !st.collapsed;
    var body = el("op-body"); if (body) body.style.display = st.collapsed ? "none" : "flex";
    var b = el("op-min"); if (b) b.textContent = st.collapsed ? "▴" : "▾";
    save({ docked: st.docked, collapsed: st.collapsed });
  }
  function toggleDock() { st.docked = !st.docked; applyDock(); }

  function makeDraggable(handle, box) {
    var sx, sy, ox, oy, drag = false;
    function down(e) { if (st.docked) return; drag = true; var pt = e.touches ? e.touches[0] : e; sx = pt.clientX; sy = pt.clientY; var r = box.getBoundingClientRect(); ox = r.left; oy = r.top; box.style.right = "auto"; box.style.bottom = "auto"; box.style.left = ox + "px"; box.style.top = oy + "px"; document.addEventListener("mousemove", move); document.addEventListener("mouseup", up); document.addEventListener("touchmove", move, { passive: false }); document.addEventListener("touchend", up); e.preventDefault(); }
    function move(e) { if (!drag) return; var pt = e.touches ? e.touches[0] : e; var nx = ox + (pt.clientX - sx), ny = oy + (pt.clientY - sy); box.style.left = Math.max(0, Math.min(nx, window.innerWidth - box.offsetWidth)) + "px"; box.style.top = Math.max(0, Math.min(ny, window.innerHeight - box.offsetHeight)) + "px"; if (e.cancelable) e.preventDefault(); }
    function up() { drag = false; document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); document.removeEventListener("touchmove", move); document.removeEventListener("touchend", up); save({ docked: st.docked, collapsed: st.collapsed, left: box.style.left, top: box.style.top }); }
    handle.addEventListener("mousedown", down); handle.addEventListener("touchstart", down, { passive: false });
  }
  function makeResizable(grip, box, body) {
    var sx, sy, sw, sh, rz = false;
    function down(e) { rz = true; var pt = e.touches ? e.touches[0] : e; sx = pt.clientX; sy = pt.clientY; sw = box.offsetWidth; sh = body.offsetHeight; document.addEventListener("mousemove", move); document.addEventListener("mouseup", up); document.addEventListener("touchmove", move, { passive: false }); document.addEventListener("touchend", up); e.preventDefault(); e.stopPropagation(); }
    function move(e) { if (!rz) return; var pt = e.touches ? e.touches[0] : e; if (!st.docked) box.style.width = Math.max(360, Math.min(sw + (pt.clientX - sx), window.innerWidth - 20)) + "px"; var nh = Math.max(140, Math.min(sh + (pt.clientY - sy), window.innerHeight - 120)); body.style.maxHeight = nh + "px"; body.style.height = nh + "px"; if (e.cancelable) e.preventDefault(); }
    function up() { rz = false; document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); document.removeEventListener("touchmove", move); document.removeEventListener("touchend", up); }
    grip.addEventListener("mousedown", down); grip.addEventListener("touchstart", down, { passive: false });
  }

  function ensure() {
    if (el("op-console")) return el("op-console");
    var saved = load(); st.docked = saved.docked !== false; st.collapsed = !!saved.collapsed;
    var wrap = mk("div", "position:fixed;z-index:99998;display:flex;flex-direction:column;background:rgba(10,14,22,.98);border:1px solid #f97316;border-radius:12px;box-shadow:0 14px 46px rgba(0,0,0,.6);font:12px/1.5 ui-monospace,Menlo,monospace;color:#cbd5e1;overflow:hidden");
    wrap.id = "op-console";
    wrap.innerHTML =
      '<div id="op-head" style="display:flex;align-items:center;gap:8px;padding:9px 14px;background:#0f172a;border-bottom:1px solid #1e293b;cursor:move;user-select:none">' +
        '<strong style="color:#e5e7eb;font:600 13px system-ui">Operator console</strong>' +
        '<span id="op-mode" style="font-size:10px;padding:1px 7px;border-radius:999px;background:#374151;color:#d1d5db">checking…</span>' +
        '<span style="flex:1"></span>' +
        '<span class="op-hint" style="font-size:11px;color:#64748b;margin-right:6px">Prompt, slash-commands, sandbox execution</span>' +
        '<button type="button" id="op-dock" title="Dock / float" style="' + btn() + '">⤢ float</button>' +
        '<button type="button" id="op-clear" title="Clear" style="' + btn() + '">🗑</button>' +
        '<button type="button" id="op-min" title="Minimize / expand" style="' + btn() + '">▾</button>' +
      '</div>' +
      '<div id="op-body" style="display:flex;max-height:min(42vh,340px)">' +
        '<div style="flex:1;display:flex;flex-direction:column;min-width:0">' +
          '<div id="op-out" style="flex:1;overflow:auto;padding:12px 16px;min-height:120px"></div>' +
          '<form id="op-form" style="display:flex;gap:8px;padding:10px 12px;border-top:1px solid #1e293b;background:#0b1220">' +
            '<input id="op-input" autocomplete="off" spellcheck="false" placeholder="Ask, or /help   /isolate HOST   /scan" style="flex:1;background:#0f172a;border:1px solid #334155;border-radius:8px;color:#e5e7eb;padding:9px 12px;font:inherit;outline:none" />' +
            '<button type="submit" style="' + btn("#334155") + ';display:inline-flex;align-items:center;gap:6px;padding:8px 16px"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg>Run</button>' +
            '<button type="button" id="op-trash" title="Clear" style="' + btn() + ';padding:8px 10px"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg></button>' +
          '</form>' +
        '</div>' +
        '<div id="op-side" style="width:250px;border-left:1px solid #1e293b;padding:14px 16px;background:#0c1119;overflow:auto">' +
          '<div style="font-weight:700;color:#e5e7eb;margin-bottom:8px">Safety fabric</div>' +
          '<div style="font-size:12px;color:#94a3b8;line-height:1.6">Every line is scanned for destructive shells, jailbreaks, and encoded payloads. HIGH actions stage an approval instead of executing.</div>' +
          '<div id="op-fabric-stat" style="margin-top:14px;display:flex;flex-direction:column;gap:6px"></div>' +
          '<div style="margin-top:14px;font-size:11px;color:#475569;line-height:1.6">Raw HTML from failed backends is never rendered here.</div>' +
        '</div>' +
        '<div id="op-grip" title="Drag to resize" style="position:absolute;right:2px;bottom:2px;width:16px;height:16px;cursor:nwse-resize;color:#475569;font-size:12px;text-align:right;line-height:16px">◢</div>' +
      '</div>';
    document.body.appendChild(wrap);
    el("op-dock").onclick = toggleDock;
    el("op-min").onclick = function () { toggleCollapse(); };
    var clr = function () { el("op-out").innerHTML = ""; system(); };
    el("op-clear").onclick = clr; el("op-trash").onclick = clr;
    el("op-form").onsubmit = function (e) { e.preventDefault(); var inp = el("op-input"), cmd = inp.value.trim(); if (!cmd) return; inp.value = ""; st.history.push(cmd); st.histIdx = st.history.length; run(cmd); };
    el("op-input").addEventListener("keydown", function (e) {
      if (e.key === "ArrowUp" && st.histIdx > 0) { st.histIdx--; e.target.value = st.history[st.histIdx] || ""; e.preventDefault(); }
      else if (e.key === "ArrowDown") { if (st.histIdx < st.history.length - 1) { st.histIdx++; e.target.value = st.history[st.histIdx] || ""; } else { st.histIdx = st.history.length; e.target.value = ""; } e.preventDefault(); }
    });
    makeDraggable(el("op-head"), wrap);
    makeResizable(el("op-grip"), wrap, el("op-body"));
    window.addEventListener("resize", function () { if (st.docked) applyDock(); });
    applyDock(); if (st.collapsed) toggleCollapse(true);
    badge(); system();
    return wrap;
  }

  function system() {
    line("system", "Horizon core online. Safety fabric armed. Fleet heartbeat established. Type /help for operator commands.", "system");
  }
  function fabricStat() {
    if (mode !== "online") return;
    api("/api/fabric/status").then(function (f) {
      var host = el("op-fabric-stat"); if (!host) return;
      var score = (f.posture && f.posture.overall_score) || "?";
      host.innerHTML =
        '<div style="display:flex;justify-content:space-between;font-size:11px"><span style="color:#64748b">Zero-Trust</span><span style="color:#34d399;font-weight:700">' + esc(score) + '</span></div>' +
        '<div style="display:flex;justify-content:space-between;font-size:11px"><span style="color:#64748b">Capabilities</span><span style="color:#e5e7eb">' + esc(f.capability_count || 7) + '</span></div>';
    }).catch(function () {});
  }

  // ── Public API ───────────────────────────────────────────────────────────
  window.JAKAL = window.JAKAL || {};
  window.JAKAL.console = { print: print, printJson: printJson, run: run, open: function () { ensure(); if (st.collapsed) toggleCollapse(false); el("op-input") && el("op-input").focus(); } };
  window.JAKAL.requestApproval = function (opts) { renderApprovalCard(opts || {}); };
  window.JAKAL.log = function (msg, kind) { ensure(); print(msg, kind || "out"); };

  function boot() {
    ensure();
    probe().then(function () { badge(); if (mode !== "online") print("Demo mode — no live backend detected. Slash-commands return sample output.", "muted"); else { print("Live backend connected.", "ok"); fabricStat(); setInterval(pollApprovals, 5000); } });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
