/**
 * js/jakal-integrations.js — JAKAL live tools (v1.0)
 *
 * Additive, non-destructive. Adds two REAL, backend-wired panels reachable
 * from a small launcher (bottom-left, clear of the Operator Console):
 *   • Threat Intelligence — live IP/domain/URL/hash enrichment (Target A).
 *       Feodo + Tor work with no key; VirusTotal/AbuseIPDB/OTX enrich when
 *       configured. Calls GET /api/threatintel/lookup.
 *   • Integrations (API-Key Vault) — enter/save/test/remove provider keys.
 *       Calls /api/integrations/*. Keys are encrypted server-side and never
 *       returned. Saving a key immediately activates the matching module.
 *
 * Falls back gracefully (honest "backend offline") when the API is down.
 */
(function () {
  "use strict";
  var BASE = window.location.protocol === "file:" ? "http://localhost:8000" : window.location.origin;

  function api(path, opts) {
    opts = opts || {};
    var h = { Accept: "application/json" };
    if (opts.body) h["Content-Type"] = "application/json";
    return fetch(BASE + path, { method: opts.method || "GET", headers: h, body: opts.body }).then(function (r) {
      var ct = (r.headers.get("content-type") || "").toLowerCase();
      return r.text().then(function (t) {
        if (/^\s*<(!doctype|html)/i.test(t) || (ct && ct.indexOf("json") < 0)) throw new Error("backend unavailable (non-JSON " + r.status + ")");
        var d = t ? JSON.parse(t) : null;
        if (!r.ok) throw Object.assign(new Error((d && d.detail) || ("HTTP " + r.status)), { data: d });
        return d;
      });
    });
  }
  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  var C = { bg:"#0b0f17", panel:"#111827", panel2:"#161d2b", line:"#1f2937", line2:"#2b3648",
            ink:"#e8ebf0", ink2:"#aeb7c6", mut:"#7c8598", accent:"#f5920b",
            good:"#34d399", warn:"#f5b23a", crit:"#f26262", info:"#5aa9f2" };
  var VC = { malicious: C.crit, suspicious: C.warn, clean: C.good };

  // ── styles (scoped, injected once) ─────────────────────────────────────
  var css = document.createElement("style");
  css.textContent = [
    ".jkx-launch{position:fixed;left:16px;top:70px;z-index:99990;display:flex;gap:8px;font-family:ui-sans-serif,system-ui,sans-serif}",
    ".jkx-launch button{background:"+C.panel+";color:"+C.ink+";border:1px solid "+C.line2+";border-radius:10px;padding:9px 13px;font-size:12.5px;font-weight:600;cursor:pointer;box-shadow:0 8px 24px -12px #000}",
    ".jkx-launch button:hover{border-color:"+C.accent+"}",
    ".jkx-ov{position:fixed;inset:0;z-index:99991;background:rgba(3,6,12,.66);display:flex;align-items:flex-start;justify-content:center;padding:40px 16px;overflow:auto}",
    ".jkx-modal{width:100%;max-width:720px;background:linear-gradient(180deg,#0c111a,#0a0e15);border:1px solid "+C.line2+";border-radius:16px;box-shadow:0 30px 70px -30px #000;color:"+C.ink+";font-family:ui-sans-serif,system-ui,sans-serif}",
    ".jkx-top{display:flex;align-items:center;gap:10px;padding:13px 18px;border-bottom:1px solid "+C.line+";font-family:ui-monospace,monospace;font-size:12.5px;color:"+C.mut+"}",
    ".jkx-top .t{color:"+C.accent+";font-weight:700;letter-spacing:.04em}",
    ".jkx-x{margin-left:auto;background:none;border:0;color:"+C.mut+";font-size:20px;cursor:pointer;line-height:1}",
    ".jkx-body{padding:18px}",
    ".jkx-row{display:flex;gap:10px;flex-wrap:wrap}",
    ".jkx-in{flex:1;min-width:200px;background:#0a0f17;border:1px solid "+C.line2+";border-radius:10px;padding:11px 13px;color:"+C.ink+";font-family:ui-monospace,monospace;font-size:14px}",
    ".jkx-btn{background:"+C.accent+";color:#1a1204;border:none;border-radius:10px;padding:11px 18px;font-weight:700;font-size:13px;cursor:pointer}",
    ".jkx-btn.sec{background:#141c28;color:"+C.ink+";border:1px solid "+C.line2+"}",
    ".jkx-btn.danger{background:#2a1414;color:#f4b0b0;border:1px solid #6b2a2a}",
    ".jkx-btn:disabled{opacity:.5;cursor:default}",
    ".jkx-verdict{display:flex;align-items:center;gap:13px;padding:13px 15px;border-radius:11px;margin-top:14px;border:1px solid}",
    ".jkx-ball{width:48px;height:48px;border-radius:12px;display:grid;place-items:center;font-family:ui-monospace,monospace;font-weight:700;font-size:17px;flex:none}",
    ".jkx-src{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:9px;margin-top:14px}",
    ".jkx-card{background:#0a0f17;border:1px solid "+C.line+";border-radius:10px;padding:11px 12px}",
    ".jkx-card .s{font-family:ui-monospace,monospace;font-size:10px;color:"+C.mut+";text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px}",
    ".jkx-card .v{font-weight:600;font-size:13.5px}",
    ".jkx-card .sub{font-family:ui-monospace,monospace;font-size:10.5px;color:"+C.mut+";margin-top:3px}",
    ".jkx-note{font-family:ui-monospace,monospace;font-size:11px;color:"+C.mut+";margin-top:12px}",
    ".jkx-int{display:flex;align-items:center;gap:11px;padding:11px 0;border-bottom:1px solid "+C.line+"}",
    ".jkx-int .meta{flex:1;min-width:0}",
    ".jkx-int .nm{font-weight:600;font-size:13.5px}",
    ".jkx-int .d{font-family:ui-monospace,monospace;font-size:10.5px;color:"+C.mut+"}",
    ".jkx-pill{font-family:ui-monospace,monospace;font-size:10px;font-weight:700;text-transform:uppercase;padding:3px 8px;border-radius:99px;white-space:nowrap}",
    ".jkx-msg{font-family:ui-monospace,monospace;font-size:11.5px;margin-top:10px;min-height:16px}"
  ].join("\n");
  document.head.appendChild(css);

  function overlay(build) {
    var ov = document.createElement("div"); ov.className = "jkx-ov";
    ov.onclick = function (e) { if (e.target === ov) ov.remove(); };
    var m = document.createElement("div"); m.className = "jkx-modal";
    ov.appendChild(m); document.body.appendChild(ov); build(m, ov); return m;
  }

  // ── Threat Intelligence panel ──────────────────────────────────────────
  function openIntel() {
    overlay(function (m) {
      m.innerHTML =
        '<div class="jkx-top"><span class="t">◇ THREAT INTELLIGENCE</span><span>· live indicator enrichment</span>' +
        '<button class="jkx-x">×</button></div><div class="jkx-body">' +
        '<div class="jkx-row"><input class="jkx-in" id="jkx-ind" placeholder="IP · domain · URL · file hash (e.g. 162.243.103.246)"/>' +
        '<button class="jkx-btn" id="jkx-go">Check indicator</button></div>' +
        '<div id="jkx-res"></div></div>';
      m.querySelector(".jkx-x").onclick = function () { m.parentNode.remove(); };
      var input = m.querySelector("#jkx-ind"), res = m.querySelector("#jkx-res"), go = m.querySelector("#jkx-go");
      function run() {
        var v = input.value.trim(); if (!v) return;
        res.innerHTML = '<div class="jkx-note">querying live threat feeds…</div>'; go.disabled = true;
        api("/api/threatintel/lookup?indicator=" + encodeURIComponent(v)).then(function (d) {
          go.disabled = false;
          if (!d.ok) { res.innerHTML = '<div class="jkx-note" style="color:'+C.crit+'">'+esc(d.error||"lookup failed")+'</div>'; return; }
          var col = VC[d.verdict] || C.mut;
          var srcs = (d.sources || []).map(function (s) {
            var mal = s.malicious ? C.crit : (s.suspicious ? C.warn : (s.error ? C.mut : C.good));
            return '<div class="jkx-card"><div class="s">'+esc(s.source)+(s.keyless?' · keyless':'')+'</div>' +
              '<div class="v" style="color:'+mal+'">'+esc(s.error?("error"):(s.summary||""))+'</div>' +
              (s.detail?('<div class="sub">'+esc(Object.keys(s.detail).slice(0,3).map(function(k){return k+": "+s.detail[k];}).join(" · "))+'</div>'):'') +
              '</div>';
          }).join("");
          res.innerHTML =
            '<div class="jkx-verdict" style="border-color:'+col+';background:'+col+'1f">' +
            '<div class="jkx-ball" style="background:'+col+'22;color:'+col+'">'+ (d.score||0) +'</div>' +
            '<div><div style="font-weight:700;color:'+col+';font-size:15px">'+esc(d.verdict.toUpperCase())+' — '+esc(d.confidence)+' confidence</div>' +
            '<div style="font-family:ui-monospace,monospace;font-size:11.5px;color:'+C.ink2+'">'+esc(d.indicator)+' · type: '+esc(d.indicator_type)+ (d.malicious_sources&&d.malicious_sources.length?(' · flagged by '+esc(d.malicious_sources.join(", "))):'') +'</div></div></div>' +
            '<div class="jkx-src">'+srcs+'</div>' +
            (d.note?('<div class="jkx-note">'+esc(d.note)+'</div>'):'');
        }).catch(function (e) { go.disabled = false; res.innerHTML = '<div class="jkx-note" style="color:'+C.crit+'">'+esc(e.message)+'</div>'; });
      }
      go.onclick = run; input.addEventListener("keydown", function (e) { if (e.key === "Enter") run(); });
      setTimeout(function(){ input.focus(); }, 50);
    });
  }

  // ── Integrations (API-Key Vault) panel ─────────────────────────────────
  function openIntegrations() {
    overlay(function (m) {
      m.innerHTML =
        '<div class="jkx-top"><span class="t">⚙ INTEGRATIONS</span><span>· API-key vault (encrypted at rest)</span>' +
        '<button class="jkx-x">×</button></div><div class="jkx-body" id="jkx-ilist">' +
        '<div class="jkx-note">loading…</div></div>';
      m.querySelector(".jkx-x").onclick = function () { m.parentNode.remove(); };
      var list = m.querySelector("#jkx-ilist");
      function render() {
        api("/api/integrations/status").then(function (d) {
          list.innerHTML = (d.integrations || []).map(function (i) {
            var col = i.configured ? C.good : C.mut;
            return '<div class="jkx-int" data-p="'+esc(i.provider)+'">' +
              '<div class="meta"><div class="nm">'+esc(i.label)+' <span class="jkx-pill" style="background:'+col+'22;color:'+col+'">'+(i.configured?("● "+(i.source||"set")):"not set")+'</span></div>' +
              '<div class="d">'+esc(i.kind)+' · '+esc((i.indicators||[]).join("/")||"—")+' · '+esc(i.free)+'</div></div>' +
              '<input class="jkx-in" style="max-width:230px" type="password" placeholder="'+esc(i.secret_label||"API key")+'" data-k="'+esc(i.provider)+'"/>' +
              '<button class="jkx-btn sec" data-save="'+esc(i.provider)+'">Save</button>' +
              '<button class="jkx-btn sec" data-test="'+esc(i.provider)+'">Test</button>' +
              (i.configured?'<button class="jkx-btn danger" data-del="'+esc(i.provider)+'">✕</button>':'') +
              '</div>';
          }).join("") + '<div class="jkx-msg" id="jkx-imsg"></div>' +
          '<div class="jkx-note">Keys are encrypted server-side (AES-256-GCM) and never displayed. Saving a key activates the matching module immediately.</div>';
          var msg = list.querySelector("#jkx-imsg");
          function say(t, ok){ msg.style.color = ok?C.good:C.crit; msg.textContent = t; }
          list.querySelectorAll("[data-save]").forEach(function (b) { b.onclick = function () {
            var p = b.getAttribute("data-save"), inp = list.querySelector('[data-k="'+p+'"]'), v = inp.value.trim();
            if (!v) { say("Enter a value for "+p+" first.", false); return; }
            b.disabled = true;
            api("/api/integrations/key", { method:"POST", body: JSON.stringify({ provider:p, secret:v }) })
              .then(function(){ say("Saved "+p+" — module activated.", true); render(); })
              .catch(function(e){ b.disabled=false; say("Save failed: "+e.message, false); });
          }; });
          list.querySelectorAll("[data-test]").forEach(function (b) { b.onclick = function () {
            var p = b.getAttribute("data-test"); b.disabled = true; say("Testing "+p+"…", true);
            api("/api/integrations/test/"+p, { method:"POST" })
              .then(function(r){ b.disabled=false; say(r.message || (r.ok?"ok":"failed"), r.ok); })
              .catch(function(e){ b.disabled=false; say("Test failed: "+e.message, false); });
          }; });
          list.querySelectorAll("[data-del]").forEach(function (b) { b.onclick = function () {
            var p = b.getAttribute("data-del"); b.disabled = true;
            api("/api/integrations/key/"+p, { method:"DELETE" })
              .then(function(){ say("Removed "+p+".", true); render(); })
              .catch(function(e){ b.disabled=false; say("Remove failed: "+e.message, false); });
          }; });
        }).catch(function (e) { list.innerHTML = '<div class="jkx-note" style="color:'+C.crit+'">Backend offline — '+esc(e.message)+'</div>'; });
      }
      render();
    });
  }

  // ── Fleet + Asset detail (Target B) ────────────────────────────────────
  function openFleet() {
    overlay(function (m) {
      m.innerHTML =
        '<div class="jkx-top"><span class="t">\u25a4 FLEET</span><span>· managed endpoints (live agents)</span>' +
        '<button class="jkx-x">\u00d7</button></div><div class="jkx-body" id="jkx-fleet"><div class="jkx-note">loading…</div></div>';
      m.querySelector(".jkx-x").onclick = function () { m.parentNode.remove(); };
      var host = m.querySelector("#jkx-fleet");
      api("/api/agents").then(function (d) {
        if (!d.agents || !d.agents.length) {
          host.innerHTML = '<div class="jkx-note">No agents enrolled yet. Run the JAKAL agent on an endpoint:<br><br>'+
            '<span style="color:'+C.accent+'">python agent/jakal_agent.py --server '+esc(BASE)+'</span><br><br>'+
            'It registers, reports inventory, and appears here as a live device.</div>';
          return;
        }
        host.innerHTML = '<div class="jkx-note" style="margin-bottom:10px">'+d.online+' of '+d.count+' online</div>' +
          d.agents.map(function (a) {
            var col = a.status === "online" ? C.good : C.mut;
            return '<div class="jkx-int" data-a="'+esc(a.agent_id)+'" style="cursor:pointer">' +
              '<div class="meta"><div class="nm">'+esc(a.hostname||a.agent_id)+' <span class="jkx-pill" style="background:'+col+'22;color:'+col+'">'+esc(a.status)+'</span></div>' +
              '<div class="d">'+esc(a.os||"")+' · '+esc(a.ip||"")+' · '+esc(a.agent_id)+'</div></div>' +
              '<button class="jkx-btn sec" data-open="'+esc(a.agent_id)+'">Open</button></div>';
          }).join("");
        host.querySelectorAll("[data-open]").forEach(function (b) { b.onclick = function () { openAsset(b.getAttribute("data-open")); }; });
      }).catch(function (e) { host.innerHTML = '<div class="jkx-note" style="color:'+C.crit+'">Backend offline — '+esc(e.message)+'</div>'; });
    });
  }

  function openAsset(agentId) {
    overlay(function (m) {
      m.innerHTML = '<div class="jkx-top"><span class="t">\u25a4 ASSET</span><span id="jkx-atitle">· '+esc(agentId)+'</span>' +
        '<button class="jkx-x">\u00d7</button></div><div class="jkx-body" id="jkx-adet"><div class="jkx-note">loading…</div></div>';
      m.querySelector(".jkx-x").onclick = function () { m.parentNode.remove(); };
      var host = m.querySelector("#jkx-adet");
      function render() {
        api("/api/agents/" + encodeURIComponent(agentId)).then(function (a) {
          var inv = a.inventory || {}; var v = a.vulnerabilities || {};
          var col = a.status === "online" ? C.good : C.mut;
          var actions = ["fleet:ping","fleet:collect_diagnostics","fleet:isolate_host"];
          host.innerHTML =
            '<div style="display:flex;align-items:center;gap:12px;margin-bottom:14px"><div style="width:42px;height:42px;border-radius:11px;background:#141c28;border:1px solid '+C.line2+';display:grid;place-items:center;color:'+C.info+'">\u25a4</div>' +
            '<div><div style="font-weight:700;font-size:16px">'+esc(a.hostname||a.agent_id)+'</div><div style="font-family:ui-monospace,monospace;font-size:11.5px;color:'+C.mut+'">'+esc(a.os||"")+' '+esc(a.os_version||"")+' · '+esc(a.ip||"")+'</div></div>' +
            '<span class="jkx-pill" style="margin-left:auto;background:'+col+'22;color:'+col+'">'+esc(a.status)+'</span></div>' +
            '<div class="jkx-src">' +
            card("Logged-in user", (inv.users||[]).join(", ")||"—") +
            card("Open ports", (inv.ports||[]).join(", ")||"—") +
            card("Software tracked", (inv.software||[]).length+" pkgs") +
            card("Open CVEs", (v.critical!=null?(v.critical+" crit / "+v.high+" high"):"—"), v.critical>0?C.crit:(v.high>0?C.warn:C.good)) +
            '</div>' +
            '<div class="jkx-note" style="margin-top:14px;color:'+C.ink2+'">Top vulnerabilities (live OSV.dev):</div>' +
            '<div style="margin-top:6px">' + ((v.findings||[]).slice(0,6).map(function (f) {
              var fc = f.severity==="CRITICAL"?C.crit:(f.severity==="HIGH"?C.warn:C.mut);
              return '<div style="display:flex;gap:10px;font-family:ui-monospace,monospace;font-size:11.5px;padding:5px 0;border-bottom:1px solid '+C.line+'"><span style="color:'+fc+';min-width:70px">'+esc(f.severity)+'</span><span style="color:'+C.ink2+';flex:1">'+esc(f.package)+' '+esc(f.version)+'</span><span style="color:'+C.mut+'">'+esc(f.cve_id)+(f.cvss?(" · "+f.cvss):"")+'</span></div>';
            }).join("") || '<div class="jkx-note">No known CVEs in reported inventory.</div>') + '</div>' +
            '<div class="jkx-row" style="margin-top:16px">' + actions.map(function (id) {
              var danger = id==="fleet:isolate_host";
              return '<button class="jkx-btn '+(danger?"danger":"sec")+'" data-act="'+id+'">'+esc(id.split(":")[1].replace(/_/g," "))+'</button>';
            }).join("") + '</div><div class="jkx-msg" id="jkx-amsg"></div>';
          var msg = host.querySelector("#jkx-amsg");
          host.querySelectorAll("[data-act]").forEach(function (b) { b.onclick = function () {
            var id = b.getAttribute("data-act"); b.disabled = true; msg.style.color=C.ink2; msg.textContent = "running "+id+"…";
            api("/api/capabilities/execute", { method:"POST", body: JSON.stringify({ action_id:id, payload:{ agent_id:agentId } }) })
              .then(function (r) {
                b.disabled=false;
                if (r.requires_approval) { msg.style.color=C.warn; msg.textContent = "Approval required: "+(r.prompt||id)+" (approval_id "+r.approval_id+")"; }
                else { msg.style.color=(r.status==="not_connected"?C.warn:C.good); msg.textContent = id+" → "+(r.status||(r.ok?"ok":"done")); setTimeout(render, 800); }
              }).catch(function (e) { b.disabled=false; msg.style.color=C.crit; msg.textContent = e.message; });
          }; });
        }).catch(function (e) { host.innerHTML = '<div class="jkx-note" style="color:'+C.crit+'">'+esc(e.message)+'</div>'; });
      }
      function card(label, val, vcol) { return '<div class="jkx-card"><div class="s">'+esc(label)+'</div><div class="v"'+(vcol?(' style="color:'+vcol+'"'):"")+'>'+esc(val)+'</div></div>'; }
      render();
    });
  }

  // ── launcher ───────────────────────────────────────────────────────────
  function mount() {
    if (document.querySelector(".jkx-launch")) return;
    var w = document.createElement("div"); w.className = "jkx-launch";
    var a = document.createElement("button"); a.type="button"; a.textContent = "◇ Threat Intel"; a.onclick = openIntel;
    var b = document.createElement("button"); b.type="button"; b.textContent = "⚙ Integrations"; b.onclick = openIntegrations;
    w.appendChild(a); w.appendChild(b); document.body.appendChild(w);
  }
  // expose for nav integration if desired
  window.JAKAL = window.JAKAL || {};
  window.JAKAL.openThreatIntel = openIntel;
  window.JAKAL.openIntegrations = openIntegrations;
  window.JAKAL.openFleet = openFleet;
  window.JAKAL.openAsset = openAsset;

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount); else mount();
})();
