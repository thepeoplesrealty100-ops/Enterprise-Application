/**
 * js/jakal-live-data.js — bridges live backend data into the existing module UIs.
 *
 * Non-destructive: when a backend is connected it replaces the Global Fleet
 * mock array (window.globalDashboardState.devices) with the real managed
 * devices from /api/dashboard/fleet, then lets the app's own renderer draw
 * them. Falls back silently to the built-in mock when offline.
 *
 * Also syncs fabric posture score + agent activity feed when DOM hooks exist.
 * Handoff note (Claude): prefer Claude LLM (LLM_ENGINE=claude, CLAUDE_API_KEY).
 * Ollama is offline/dev fallback only.
 */
(function () {
  "use strict";
  var BASE = window.location.protocol === "file:" ? "http://localhost:8000" : window.location.origin;
  var online = null;

  function api(path) {
    return fetch(BASE + path, { headers: { Accept: "application/json" } }).then(function (r) {
      var ct = (r.headers.get("content-type") || "").toLowerCase();
      return r.text().then(function (t) {
        if (/^\s*<(!doctype|html)/i.test(t) || (ct && ct.indexOf("json") < 0)) throw new Error("non-JSON");
        return t ? JSON.parse(t) : null;
      });
    });
  }

  function mapDevice(d) {
    var risk = typeof d.risk === "number" ? d.risk : (typeof d.risk_score === "number" ? d.risk_score : 0);
    if (risk > 1) risk = risk / 100;
    var status = d.status || (risk >= 0.6 ? "Critical" : risk >= 0.35 ? "Warning" : "Healthy");
    if (status !== "Healthy" && status !== "Warning" && status !== "Critical") {
      status = risk >= 0.6 ? "Critical" : risk >= 0.35 ? "Warning" : "Healthy";
    }
    var riskLabel = risk >= 0.6 ? "High" : risk >= 0.35 ? "Medium" : "Low";
    var tags = Array.isArray(d.tags) ? d.tags : [];
    var type = tags.indexOf("server") >= 0 ? "Server" : tags.indexOf("iot") >= 0 ? "IoT"
      : tags.indexOf("laptop") >= 0 ? "Laptop" : tags.indexOf("kubernetes") >= 0 ? "Cloud" : "Workstation";
    var backendId = d.id != null ? d.id : null;
    return {
      id: backendId != null ? String(backendId) : ("dev-" + Math.random().toString(36).slice(2, 7)),
      backendId: backendId,
      name: d.name || d.hostname || "Unknown",
      user: d.user || "—",
      client: d.client || (tags.indexOf("finance") >= 0 ? "Beta Corp" : tags.indexOf("engineering") >= 0 ? "Alpha Inc" : "Managed"),
      type: type,
      os: d.os || d.os_fingerprint || "Unknown",
      status: status,
      risk: riskLabel,
      location: d.location || "—",
      ip: d.ip || d.ip_address || "",
      login: d.login || "live",
      tags: tags,
    };
  }

  function refreshFleet() {
    if (!window.globalDashboardState) return;
    api("/api/dashboard/fleet").then(function (r) {
      online = true;
      var rows = (r && (r.data || r.devices || r.fleet)) || [];
      if (!rows.length) return;
      window.globalDashboardState.devices = rows.map(mapDevice);
      window.__jkFleetLive = true;
      try {
        if (window.renderFleetSummaryBanner) window.renderFleetSummaryBanner();
        if (window.renderDeviceFleetTable) window.renderDeviceFleetTable();
        else if (window.switchDashboardTab && document.getElementById("device-list-table")) {
          window.switchDashboardTab("fleet");
        }
      } catch (e) {}
      if (window.JAKAL && window.JAKAL.log) window.JAKAL.log("Fleet synced: " + rows.length + " managed devices (live).", "muted");
    }).catch(function () { online = false; });
  }

  function refreshFabricCard() {
    api("/api/dashboard/fabric/status").catch(function () {
      return api("/api/fabric/status");
    }).then(function (f) {
      if (!f) return;
      var score = f.overall_score;
      if (score == null && f.posture) score = f.posture.overall_score;
      if (score == null && f.fabric && f.fabric.posture) score = f.fabric.posture.overall_score;
      window.__jkFabricLive = f;
      var el = document.getElementById("jakal-fabric-score-live");
      if (el && score != null) el.textContent = String(score);
      document.querySelectorAll("[data-live-fabric-score]").forEach(function (node) {
        if (score != null) node.textContent = String(score);
      });
    }).catch(function () {});
  }

  function refreshAgentActivity() {
    api("/api/agent/logs?limit=12").then(function (r) {
      var logs = (r && (r.logs || r.data || r)) || [];
      if (!Array.isArray(logs)) return;
      window.__jkAgentLogs = logs;
      var host = document.getElementById("jakal-agent-activity-live");
      if (!host) return;
      if (!logs.length) {
        host.innerHTML = '<p class="text-xs text-gray-500">No agent logs yet.</p>';
        return;
      }
      host.innerHTML = logs.slice(0, 10).map(function (row) {
        var ts = row.timestamp || row[1] || "";
        var evt = row.event || row[2] || "EVENT";
        var action = row.action || row[3] || "";
        var status = row.status || row[4] || "";
        var ok = String(status).toLowerCase().indexOf("success") >= 0 || String(status).toLowerCase() === "approved";
        return '<div class="jakal-activity-row"><span class="ts">' + String(ts).slice(0, 24) +
          '</span><span class="evt">' + evt + (action ? " · " + action : "") +
          '</span><span class="' + (ok ? "ok" : "fail") + '">' + status + "</span></div>";
      }).join("");
    }).catch(function () {});
  }

  function refreshAll() {
    refreshFleet();
    refreshFabricCard();
    refreshAgentActivity();
  }

  function hook() {
    if (window.switchDashboardTab && !window.switchDashboardTab.__jkLive) {
      var orig = window.switchDashboardTab;
      window.switchDashboardTab = function (tab, doRender) {
        var r = orig.apply(this, arguments);
        if (tab === "fleet" && online !== false) {
          setTimeout(refreshFleet, 50);
        }
        setTimeout(function () {
          refreshFabricCard();
          refreshAgentActivity();
        }, 80);
        return r;
      };
      window.switchDashboardTab.__jkLive = true;
    }
    setTimeout(refreshAll, 800);
    setInterval(function () {
      if (document.hidden) return;
      if (document.getElementById("device-list-table") || document.getElementById("jakal-agent-activity-live")) {
        refreshAll();
      }
    }, 45000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", hook); else hook();
})();
