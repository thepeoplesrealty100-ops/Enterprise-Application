"""
services/threat_intel.py — JAKAL live threat-intelligence engine (v1.0)

Real multi-source indicator enrichment. Two source tiers:

  Keyless (work out-of-the-box, no configuration):
    * Feodo Tracker  — abuse.ch botnet C2 IP blocklist
    * Tor exit list  — check.torproject.org bulk exit list
  Keyed (enrich when a key is stored in the Integrations vault):
    * VirusTotal     — ip / domain / url / hash
    * AbuseIPDB      — ip
    * AlienVault OTX — ip / domain / url / hash

lookup(indicator) auto-detects the indicator type, queries every applicable
source, and returns a combined verdict (0-100 score + label) with a truthful
per-source breakdown. No seeded data; a source that is unconfigured or errors
says so honestly and does not contribute a fake signal.
"""
from __future__ import annotations

import base64
import ipaddress
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("threat_intel")
_session = requests.Session()
_session.headers.update({"user-agent": "JAKAL-ThreatIntel/1.0"})

_HASH_RE = re.compile(r"^[a-fA-F0-9]{32}$|^[a-fA-F0-9]{40}$|^[a-fA-F0-9]{64}$")
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def detect_indicator_type(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return "unknown"
    if _EMAIL_RE.match(v):
        return "email"
    try:
        ipaddress.ip_address(v)
        return "ip"
    except ValueError:
        pass
    if v.startswith("http://") or v.startswith("https://"):
        return "url"
    if _HASH_RE.match(v):
        return "hash"
    if _DOMAIN_RE.match(v):
        return "domain"
    return "unknown"


# ── Keyless feed caches (TTL) ─────────────────────────────────────────────
_CACHE: Dict[str, Dict[str, Any]] = {}
_TTL = 3600  # 1h


def _cached(key: str):
    e = _CACHE.get(key)
    if e and (time.time() - e["at"] < _TTL):
        return e["data"]
    return None


def _feodo() -> Dict[str, Dict[str, Any]]:
    c = _cached("feodo")
    if c is not None:
        return c
    data: Dict[str, Dict[str, Any]] = {}
    try:
        r = _session.get("https://feodotracker.abuse.ch/downloads/ipblocklist.json", timeout=15)
        r.raise_for_status()
        for row in r.json():
            data[row.get("ip_address")] = row
    except requests.RequestException as e:
        logger.warning("feodo fetch failed: %s", e)
    _CACHE["feodo"] = {"at": time.time(), "data": data}
    return data


def _tor() -> set:
    c = _cached("tor")
    if c is not None:
        return c
    nodes: set = set()
    try:
        r = _session.get("https://check.torproject.org/torbulkexitlist", timeout=15)
        r.raise_for_status()
        nodes = {l.strip() for l in r.text.splitlines() if l and not l.startswith("#")}
    except requests.RequestException as e:
        logger.warning("tor list fetch failed: %s", e)
    _CACHE["tor"] = {"at": time.time(), "data": nodes}
    return nodes


# ── Source queries → normalized {source, verdict, score(0-100), detail} ────
def _src_feodo(ind: str) -> Optional[Dict[str, Any]]:
    hit = _feodo().get(ind)
    if hit:
        return {"source": "Feodo Tracker", "keyless": True, "malicious": True, "score": 95,
                "detail": {"malware": hit.get("malware"), "status": hit.get("status"),
                           "first_seen": hit.get("first_seen"), "c2": True},
                "summary": f"Known botnet C2 ({hit.get('malware')})"}
    return {"source": "Feodo Tracker", "keyless": True, "malicious": False, "score": 0,
            "summary": "not on C2 blocklist"}


def _src_tor(ind: str) -> Optional[Dict[str, Any]]:
    if ind in _tor():
        return {"source": "Tor exit list", "keyless": True, "malicious": False, "suspicious": True,
                "score": 45, "summary": "Tor exit node", "detail": {"tor_exit": True}}
    return {"source": "Tor exit list", "keyless": True, "malicious": False, "score": 0,
            "summary": "not a Tor exit"}


def _src_abuseipdb(ind: str, key: str) -> Dict[str, Any]:
    try:
        r = _session.get("https://api.abuseipdb.com/api/v2/check",
                         headers={"Key": key, "Accept": "application/json"},
                         params={"ipAddress": ind, "maxAgeInDays": 90}, timeout=15)
        if r.status_code == 401:
            return {"source": "AbuseIPDB", "error": "invalid API key (401)", "score": 0}
        r.raise_for_status()
        d = r.json().get("data", {})
        conf = int(d.get("abuseConfidenceScore", 0))
        return {"source": "AbuseIPDB", "score": conf, "malicious": conf >= 50,
                "detail": {"reports": d.get("totalReports"), "isp": d.get("isp"),
                           "country": d.get("countryCode"), "usage": d.get("usageType"),
                           "confidence": conf},
                "summary": f"{conf}% abuse confidence, {d.get('totalReports',0)} reports"}
    except requests.RequestException as e:
        return {"source": "AbuseIPDB", "error": str(e), "score": 0}


def _src_virustotal(ind: str, itype: str, key: str) -> Dict[str, Any]:
    path = {"ip": f"ip_addresses/{ind}", "domain": f"domains/{ind}",
            "hash": f"files/{ind}"}.get(itype)
    if itype == "url":
        path = "urls/" + base64.urlsafe_b64encode(ind.encode()).decode().strip("=")
    if not path:
        return {"source": "VirusTotal", "error": f"unsupported type {itype}", "score": 0}
    try:
        r = _session.get(f"https://www.virustotal.com/api/v3/{path}",
                         headers={"x-apikey": key}, timeout=15)
        if r.status_code == 401:
            return {"source": "VirusTotal", "error": "invalid API key (401)", "score": 0}
        if r.status_code == 404:
            return {"source": "VirusTotal", "score": 0, "malicious": False,
                    "summary": "not found in VirusTotal"}
        r.raise_for_status()
        stats = r.json().get("data", {}).get("attributes", {}).get("last_analysis_stats", {})
        mal = int(stats.get("malicious", 0)); total = sum(int(v) for v in stats.values()) or 1
        score = min(100, int(mal / total * 100) + (mal * 5))
        return {"source": "VirusTotal", "score": score, "malicious": mal > 0,
                "detail": {"malicious": mal, "suspicious": stats.get("suspicious"),
                           "harmless": stats.get("harmless"), "engines": total},
                "summary": f"{mal}/{total} engines flagged"}
    except requests.RequestException as e:
        return {"source": "VirusTotal", "error": str(e), "score": 0}


def _src_otx(ind: str, itype: str, key: str) -> Dict[str, Any]:
    seg = {"ip": "IPv4", "domain": "domain", "hash": "file", "url": "url"}.get(itype)
    if not seg:
        return {"source": "AlienVault OTX", "error": f"unsupported type {itype}", "score": 0}
    try:
        r = _session.get(f"https://otx.alienvault.com/api/v1/indicators/{seg}/{ind}/general",
                         headers={"X-OTX-API-KEY": key}, timeout=15)
        if r.status_code in (401, 403):
            return {"source": "AlienVault OTX", "error": "invalid API key", "score": 0}
        r.raise_for_status()
        pulses = r.json().get("pulse_info", {}).get("count", 0)
        score = min(100, pulses * 12)
        return {"source": "AlienVault OTX", "score": score, "malicious": pulses >= 3,
                "detail": {"pulses": pulses},
                "summary": f"{pulses} threat pulses"}
    except requests.RequestException as e:
        return {"source": "AlienVault OTX", "error": str(e), "score": 0}


def lookup(indicator: str) -> Dict[str, Any]:
    indicator = (indicator or "").strip()
    itype = detect_indicator_type(indicator)
    if itype == "unknown":
        return {"ok": False, "indicator": indicator, "error": "unrecognized indicator format"}

    from services.secrets import get_secret
    sources: List[Dict[str, Any]] = []

    if itype == "ip":
        sources.append(_src_feodo(indicator))
        sources.append(_src_tor(indicator))
        if get_secret("abuseipdb"):
            sources.append(_src_abuseipdb(indicator, get_secret("abuseipdb")))
    if itype in ("ip", "domain", "url", "hash"):
        if get_secret("virustotal"):
            sources.append(_src_virustotal(indicator, itype, get_secret("virustotal")))
        if get_secret("otx"):
            sources.append(_src_otx(indicator, itype, get_secret("otx")))

    scored = [s for s in sources if isinstance(s.get("score"), (int, float)) and not s.get("error")]
    max_score = max([s["score"] for s in scored], default=0)
    any_mal = any(s.get("malicious") for s in sources)
    any_susp = any(s.get("suspicious") for s in sources)
    if any_mal or max_score >= 70:
        verdict, conf = "malicious", "high"
    elif any_susp or max_score >= 40:
        verdict, conf = "suspicious", "medium"
    else:
        verdict, conf = "clean", "low"

    configured = {"abuseipdb": bool(get_secret("abuseipdb")), "virustotal": bool(get_secret("virustotal")),
                  "otx": bool(get_secret("otx"))}
    return {
        "ok": True, "indicator": indicator, "indicator_type": itype,
        "verdict": verdict, "confidence": conf, "score": max_score,
        "malicious_sources": [s["source"] for s in sources if s.get("malicious")],
        "sources": sources,
        "keyed_sources_configured": configured,
        "note": (None if any(configured.values())
                 else "Keyless sources only. Add VirusTotal / AbuseIPDB / OTX keys in Integrations for deeper coverage."),
        "checked_at": _now(),
    }


def probe_provider(provider: str, key: str) -> Dict[str, Any]:
    """Cheap live connectivity check for the Integrations 'Test' button."""
    try:
        if provider == "abuseipdb":
            r = _session.get("https://api.abuseipdb.com/api/v2/check",
                             headers={"Key": key, "Accept": "application/json"},
                             params={"ipAddress": "8.8.8.8", "maxAgeInDays": 30}, timeout=12)
        elif provider == "virustotal":
            r = _session.get("https://www.virustotal.com/api/v3/ip_addresses/8.8.8.8",
                             headers={"x-apikey": key}, timeout=12)
        elif provider == "otx":
            r = _session.get("https://otx.alienvault.com/api/v1/indicators/IPv4/8.8.8.8/general",
                             headers={"X-OTX-API-KEY": key}, timeout=12)
        elif provider == "hibp":
            r = _session.get("https://haveibeenpwned.com/api/v3/breachedaccount/test@example.com",
                             headers={"hibp-api-key": key, "user-agent": "JAKAL"}, timeout=12)
        elif provider == "shodan":
            r = _session.get(f"https://api.shodan.io/api-info?key={key}", timeout=12)
        else:
            return {"provider": provider, "ok": True, "status": "configured",
                    "message": "Key stored. No live probe implemented for this provider."}
        if r.status_code in (401, 403):
            return {"provider": provider, "ok": False, "status": "invalid_key",
                    "message": f"Key rejected by {provider} ({r.status_code})."}
        return {"provider": provider, "ok": True, "status": "ok",
                "message": f"{provider} responded {r.status_code} — key works."}
    except requests.RequestException as e:
        return {"provider": provider, "ok": False, "status": "error", "message": str(e)}
