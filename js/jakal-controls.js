/**
 * js/jakal-controls.js — JAKAL reusable operator controls (v1.0)
 *
 * Additive, theme-matched control layer (does NOT alter existing layout):
 *   • A ⚙ cog injected into each module header that opens a data-driven
 *     "Actions & Settings" popover, populated from the backend capability
 *     catalog (7 domains). Each action renders the exact control its ui hint
 *     asks for — primary/danger button, dot toggle, radial group, or slider.
 *   • High-risk actions route through the Command Console's floating approval
 *     gate (window.JAKAL.requestApproval) instead of firing blind.
 *   • Factory helpers on window.JAKAL.controls for reuse anywhere.
 */
(function () {
  "use strict";
  var BASE = window.location.protocol === "file:" ? "http://localhost:8000" : window.location.origin;
  var _catalog = null, _mode = "unknown";

  function api(path, opts) {
    opts = opts || {};
    var h = { Accept: "application/json" }; if (opts.body) h["Content-Type"] = "application/json";
    return fetch(BASE + path, { method: opts.method || "GET", headers: h, body: opts.body }).then(function (r) {
      var ct = (r.headers.get("content-type") || "").toLowerCase();
      return r.text().then(function (t) {
        if (/^\s*<(!doctype|html)/i.test(t) || (ct && ct.indexOf("json") < 0)) throw new Error("non-JSON " + r.status);
        var d = t ? JSON.parse(t) : null; if (!r.ok) throw Object.assign(new Error((d && d.detail) || r.status), { status: r.status, data: d }); return d;
      });
    });
  }
  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  function log(m, k) { if (window.JAKAL && window.JAKAL.log) window.JAKAL.log(m, k); }

  // View → relevant capability domains (so the cog shows the right actions)
  var VIEW_DOMAINS = {
    admin_global_dashboard: ["fleet_rmm", "remote_access", "msp_multitenant"],
    admin_diagnostics: ["fleet_rmm", "detect_respond"],
    admin_fabric: ["detect_respond", "soar_playbooks"],
    admin_compliance: ["patch_vulnerability", "documentation_vault"],
    admin_dark_web: ["dark_web", "documentation_vault"],
    admin_horizon_fabric: ["ai_safety_fabric"],
    admin_automation_controls: ["soar_playbooks"],
    admin_security_training: ["human_layer"],
    admin_phishing_sim: ["human_layer"],
    client_settings: ["msp_multitenant", "documentation_vault"],
  };

  var RISK_COLOR = { low: "#3b82f6", medium: "#f59e0b", high: "#f59e0b", critical: "#ef4444" };
  function btnStyleFor(a) {
    var b = (a.ui && a.ui.button) || "secondary";
    if (b === "danger") return "background:#7f1d1d;border-color:#b91c1c;color:#fecaca";
    if (b === "primary") return "background:#c2410c;border-color:#f97316;color:#fff";
    if (b === "dot") return "background:#065f46;border-color:#059669;color:#a7f3d0";
    return "background:#1f2937;border-color:#374151;color:#e5e7eb";
  }

  // ── Factories (reusable anywhere) ────────────────────────────────────────
  var controls = {
    cog: function (onClick, title) {
      var b = document.createElement("button");
      b.className = "jk-cog"; b.title = title || "Actions & settings"; b.type = "button";
      b.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>';
      b.onclick = onClick; return b;
    },
    dot: function (on, onToggle) {
      var d = document.createElement("span"); d.className = "jk-dot " + (on ? "on" : "off");
      d.setAttribute("role", "button"); d.tabIndex = 0;
      d.onclick = function () { var now = !d.classList.contains("on"); d.className = "jk-dot " + (now ? "on" : "off"); onToggle && onToggle(now); };
      return d;
    },
    segmented: function (options, onPick, active) {
      var w = document.createElement("div"); w.className = "jk-seg";
      options.forEach(function (o) { var b = document.createElement("button"); b.textContent = o; if (o === active) b.className = "active"; b.onclick = function () { [].forEach.call(w.children, function (c) { c.className = ""; }); b.className = "active"; onPick && onPick(o); }; w.appendChild(b); });
      return w;
    },
    radial: function (name, options, onPick, active) {
      var w = document.createElement("div"); w.className = "jk-radial";
      options.forEach(function (o) { var l = document.createElement("label"); var i = document.createElement("input"); i.type = "radio"; i.name = name; i.value = o; if (o === active) i.checked = true; i.onchange = function () { onPick && onPick(o); }; l.appendChild(i); l.appendChild(document.createTextNode(o)); w.appendChild(l); });
      return w;
    },
    slider: function (min, max, value, onChange) {
      var wrap = document.createElement("div"); wrap.style.cssText = "display:flex;align-items:center;gap:10px;width:100%";
      var s = document.createElement("input"); s.type = "range"; s.min = min; s.max = max; s.value = value; s.className = "jk-slider";
      var bubble = document.createElement("span"); bubble.style.cssText = "min-width:44px;text-align:right;color:#f97316;font-weight:700;font-size:12px"; bubble.textContent = value;
      function fill() { s.style.setProperty("--fill", ((s.value - min) / (max - min) * 100) + "%"); bubble.textContent = s.value; }
      s.oninput = function () { fill(); onChange && onChange(+s.value); }; fill();
      wrap.appendChild(s); wrap.appendChild(bubble); return wrap;
    },
    popover: function (x, y, title) {
      closePopover();
      var p = document.createElement("div"); p.className = "jk-pop"; p.id = "jk-active-pop";
      p.style.left = Math.max(12, Math.min(x, window.innerWidth - 440)) + "px"; p.style.top = Math.max(12, Math.min(y, window.innerHeight - 360)) + "px";
      p.innerHTML = '<div style="display:flex;align-items:center;margin-bottom:10px"><strong style="color:#f97316">' + esc(title) + '</strong><button id="jk-pop-x" style="margin-left:auto;background:none;border:0;color:#9ca3af;cursor:pointer;font-size:16px">×</button></div><div id="jk-pop-body"></div>';
      document.body.appendChild(p);
      p.querySelector("#jk-pop-x").onclick = closePopover;
      setTimeout(function () { document.addEventListener("mousedown", outside); }, 0);
      function outside(e) { if (!p.contains(e.target)) { closePopover(); document.removeEventListener("mousedown", outside); } }
      return p;
    },
  };
  function closePopover() { var e = document.getElementById("jk-active-pop"); if (e) e.remove(); }

  // ── Build an action row (data-driven from its ui hint) ───────────────────
  function actionRow(a) {
    var row = document.createElement("div");
    row.style.cssText = "border:1px solid #1f2937;border-radius:10px;padding:10px;margin-bottom:8px;background:rgba(17,24,39,.6)";
    var head = document.createElement("div"); head.style.cssText = "display:flex;align-items:center;gap:8px;margin-bottom:6px";
    head.innerHTML = '<span style="font-weight:700;color:#e5e7eb">' + esc(a.name) + '</span>' +
      '<span style="font-size:9px;text-transform:uppercase;padding:1px 6px;border-radius:999px;background:' + (RISK_COLOR[a.risk] || "#374151") + '33;color:' + (RISK_COLOR[a.risk] || "#9ca3af") + '">' + esc(a.risk) + '</span>' +
      '<code style="margin-left:auto;font-size:10px;color:#6b7280">' + esc(a.id) + '</code>';
    row.appendChild(head);
    var desc = document.createElement("div"); desc.style.cssText = "font-size:11px;color:#9ca3af;margin-bottom:8px"; desc.textContent = a.description; row.appendChild(desc);

    var params = {};
    var ui = a.ui || {};
    if (ui.slider) { var lbl = document.createElement("div"); lbl.style.cssText = "font-size:10px;color:#6b7280;margin-bottom:3px"; lbl.textContent = ui.slider.field; row.appendChild(lbl); row.appendChild(controls.slider(ui.slider.min, ui.slider.max, ui.slider.value, function (v) { params[ui.slider.field] = v; })); params[ui.slider.field] = ui.slider.value; }
    if (ui.radial) { var rl = document.createElement("div"); rl.style.cssText = "font-size:10px;color:#6b7280;margin:8px 0 3px"; rl.textContent = ui.radial.field; row.appendChild(rl); row.appendChild(controls.radial(a.id, ui.radial.options, function (o) { params[ui.radial.field] = o; }, ui.radial.options[0])); params[ui.radial.field] = ui.radial.options[0]; }

    if (ui.toggle) {
      var tw = document.createElement("div");
      tw.style.cssText = "display:flex;align-items:center;gap:8px;margin:6px 0";
      var lbl = document.createElement("span"); lbl.style.cssText = "font-size:11px;color:#9ca3af"; lbl.textContent = "enabled";
      tw.appendChild(controls.dot(true, function (on) { params.enabled = on; }));
      tw.appendChild(lbl); row.appendChild(tw); params.enabled = true;
    }
    var run = document.createElement("button");
    run.type = "button"; run.textContent = "Run"; run.style.cssText = "margin-top:10px;cursor:pointer;border:1px solid;border-radius:8px;padding:6px 14px;font-size:12px;font-weight:600;" + btnStyleFor(a);
    run.onclick = function () { execAction(a, params); };
    var wrap = document.createElement("div"); wrap.style.cssText = "display:flex;align-items:center;gap:8px";
    wrap.appendChild(run);
    if (ui.cog) { wrap.appendChild(controls.cog(function () { log("settings for " + a.id + " — permission: " + a.permission_required, "muted"); }, "Action settings")); }
    row.appendChild(wrap);
    return row;
  }

  function execAction(a, params) {
    closePopover();
    if (_mode !== "online") { log("(demo) " + a.id + " " + JSON.stringify(params), "warn"); return; }
    api("/api/capabilities/execute", { method: "POST", body: JSON.stringify({ action_id: a.id, payload: params, executor_id: "operator" }) }).then(function (r) {
      if (r.requires_approval && window.JAKAL && window.JAKAL.requestApproval) {
        window.JAKAL.requestApproval({ title: r.prompt || (a.name + " requires approval"), risk: a.risk, detail: a.id,
          onApprove: function () { api("/api/capabilities/approve/" + r.approval_id, { method: "POST" }).then(function (res) { if (window.JAKAL.console) window.JAKAL.console.printJson(a.id + " ->", res); }); },
          onDeny: function () { api("/api/capabilities/deny/" + r.approval_id, { method: "POST" }); } });
      } else if (r.blocked) { log("[blocked] " + a.id + ": " + r.reason, "err"); }
      else if (window.JAKAL && window.JAKAL.console) window.JAKAL.console.printJson(a.id + " ->", r);
    }).catch(function (e) { log("[error] " + a.id + ": " + e.message, "err"); });
  }

  function openActionsPopover(ev, viewKey) {
    var domains = VIEW_DOMAINS[viewKey] || null;
    var p = controls.popover(ev.clientX + 8, ev.clientY + 14, "Actions & Settings");
    var body = p.querySelector("#jk-pop-body");
    body.innerHTML = '<div style="color:#6b7280;font-size:11px">loading capability catalog…</div>';
    ensureCatalog().then(function () {
      body.innerHTML = "";
      var cats = domains || Object.keys(_catalog.by_category);
      cats.forEach(function (cat) {
        var acts = (_catalog.by_category[cat] || []);
        if (!acts.length) return;
        var h = document.createElement("div"); h.style.cssText = "text-transform:uppercase;letter-spacing:.05em;font-size:10px;color:#f97316;margin:6px 0 8px;font-weight:700"; h.textContent = cat.replace(/_/g, " "); body.appendChild(h);
        acts.forEach(function (a) { body.appendChild(actionRow(a)); });
      });
      if (!body.children.length) body.innerHTML = '<div style="color:#6b7280;font-size:11px">No mapped actions for this module.</div>';
    }).catch(function (e) { body.innerHTML = '<div style="color:#f87171;font-size:11px">Catalog unavailable (' + esc(e.message) + '). Connect the backend for live actions.</div>'; });
  }

  function ensureCatalog() {
    if (_catalog) return Promise.resolve(_catalog);
    return api("/api/capabilities/catalog").then(function (d) { _catalog = d; _mode = "online"; return d; });
  }

  // ── Inject the cog into the current module header ────────────────────────
  function injectCog() {
    var title = document.getElementById("view-title") || document.querySelector("#content-area h1, #content-area h2");
    if (!title) return;
    if (title.parentElement && title.parentElement.querySelector(".jk-cog")) return; // already there
    // Read the active page at CLICK time (not injection time) so the popover
    // always reflects the module currently on screen.
    var cog = controls.cog(function (ev) { openActionsPopover(ev, window.__jakalCurrentPage || ""); }, "Module actions & settings");
    cog.style.marginLeft = "12px"; cog.style.verticalAlign = "middle";
    title.appendChild(cog);
  }

  // Hook page changes so the cog follows the active module.
  function hook() {
    var orig = window.loadPage;
    if (typeof orig === "function" && !orig.__jkWrapped) {
      window.loadPage = function (k) { window.__jakalCurrentPage = k; var r = orig.apply(this, arguments); setTimeout(injectCog, 400); return r; };
      window.loadPage.__jkWrapped = true;
    }
    probe(); setTimeout(injectCog, 800);
  }
  function probe() { api("/health").then(function () { _mode = "online"; }).catch(function () { _mode = "offline"; }); }

  window.JAKAL = window.JAKAL || {};
  window.JAKAL.controls = controls;

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", hook); else hook();
})();
