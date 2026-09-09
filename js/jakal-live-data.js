/**
 * js/jakal-live-data.js — bridges live backend data into the existing module UIs.
 *
 * Non-destructive: when a backend is connected it replaces the Global Fleet
 * mock array (window.globalDashboardState.devices) with the real managed
 * devices from /api/dashboard/fleet, then lets the app's own renderer draw
 * them. Falls back silently to the built-in mock when offline.
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
    var risk = typeof d.risk === "number" ? d.risk : 0;
    var status = risk >= 0.6 ? "Critical" : risk >= 0.35 ? "Warning" : "Healthy";
    var riskLabel = risk >= 0.6 ? "High" : risk >= 0.35 ? "Medium" : "Low";
    var tags = Array.isArray(d.tags) ? d.tags : [];
    var type = tags.indexOf("server") >= 0 ? "Server" : tags.indexOf("iot") >= 0 ? "IoT"
      : tags.indexOf("laptop") >= 0 ? "Laptop" : tags.indexOf("kubernetes") >= 0 ? "Cloud" : "Workstation";
    return {
      id: "dev-" + (d.id != null ? d.id : Math.random().toString(36).slice(2, 7)),
      name: d.name || d.hostname || "Unknown",
      user: "—",
      client: (tags.indexOf("finance") >= 0 ? "Beta Corp" : tags.indexOf("engineering") >= 0 ? "Alpha Inc" : "Managed"),
      type: type,
      os: d.os || d.os_fingerprint || "Unknown",
      status: status,
      risk: riskLabel,
      location: "—",
      ip: d.ip || d.ip_address || "",
      login: "live",
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
      // Re-render the fleet tab if it is currently visible.
      try {
        if (window.switchDashboardTab && document.getElementById("device-list-table")) {
          window.switchDashboardTab("fleet");
        }
      } catch (e) {}
      if (window.JAKAL && window.JAKAL.log) window.JAKAL.log("Fleet synced: " + rows.length + " managed devices (live).", "muted");
    }).catch(function () { online = false; });
  }

  function hook() {
    // Refresh whenever the operator opens the Global Dashboard / Fleet tab.
    if (window.switchDashboardTab && !window.switchDashboardTab.__jkLive) {
      var orig = window.switchDashboardTab;
      window.switchDashboardTab = function (tab, doRender) {
        var r = orig.apply(this, arguments);
        if (tab === "fleet" && online !== false && !window.__jkFleetSynced) {
          window.__jkFleetSynced = true; setTimeout(refreshFleet, 50);
        }
        return r;
      };
      window.switchDashboardTab.__jkLive = true;
    }
    setTimeout(refreshFleet, 1200);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", hook); else hook();
})();
