"""
services/nvd_scanner.py — JAKAL NVD/CPE scanner for OS & application software.

Complements services.vuln_scanner (OSV.dev, open-source package ecosystems):
this covers installed OS/application software (Windows apps, servers, OS
components) by matching against the U.S. National Vulnerability Database via
CPE — the same approach ConnectSecure uses.

  nvd_scan(products)  — products: [{name, version, vendor?, cpe?}]
                        Live NVD CVE API 2.0 query per product; real CVSS.

Honest by design: NVD's keyless rate limit is 5 requests / 30s, so scans are
spaced and bounded, results cached, and a truncated scan says so. Set an NVD
API key in the Integrations vault to raise the limit to 50 / 30s. Network or
rate errors return an honest error, never fabricated CVEs.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("nvd_scanner")
NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_SEV_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}
_MAX_PRODUCTS = 12
_session = requests.Session()
_session.headers.update({"user-agent": "JAKAL-NVDScanner/1.0"})
_cache: Dict[str, Dict[str, Any]] = {}
_TTL = 6 * 3600


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9._]+", "_", (s or "").strip().lower()).strip("_")


def _rate_gap() -> float:
    from services.secrets import get_secret
    return 0.7 if get_secret("nvd") else 6.5  # keyed 50/30s vs keyless 5/30s


def _headers() -> Dict[str, str]:
    from services.secrets import get_secret
    key = get_secret("nvd")
    return {"apiKey": key} if key else {}


def _cvss(metrics: Dict[str, Any]) -> tuple:
    for k in ("cvssMetricV31", "cvssMetricV30"):
        arr = metrics.get(k) or []
        if arr:
            d = arr[0].get("cvssData", {})
            return d.get("baseScore"), (d.get("baseSeverity") or "UNKNOWN").upper()
    arr = metrics.get("cvssMetricV2") or []
    if arr:
        d = arr[0].get("cvssData", {})
        sev = (arr[0].get("baseSeverity") or "UNKNOWN").upper()
        return d.get("baseScore"), sev
    return None, "UNKNOWN"


def _query(product: Dict[str, str]) -> Dict[str, Any]:
    name = product.get("name", ""); version = product.get("version", "")
    slug = _slug(name)
    if not slug:
        return {"product": name, "version": version, "findings": [], "matched": False}
    vendor = _slug(product.get("vendor", "")) or slug
    cpe = product.get("cpe") or f"cpe:2.3:a:{vendor}:{slug}" + (f":{version}" if version else "")
    ck = f"{cpe}"
    c = _cache.get(ck)
    if c and time.time() - c["at"] < _TTL:
        return c["data"]
    try:
        r = _session.get(NVD_URL, params={"virtualMatchString": cpe, "resultsPerPage": 20},
                         headers=_headers(), timeout=30)
        if r.status_code in (403, 429):
            return {"product": name, "version": version, "findings": [], "matched": False,
                    "error": f"NVD rate-limited ({r.status_code}); add an NVD key in Integrations."}
        r.raise_for_status()
        j = r.json()
    except requests.RequestException as e:
        return {"product": name, "version": version, "findings": [], "matched": False,
                "error": f"NVD query failed: {e.__class__.__name__}"}
    findings = []
    for item in j.get("vulnerabilities", []):
        cve = item.get("cve", {})
        score, sev = _cvss(cve.get("metrics", {}))
        desc = next((d["value"] for d in cve.get("descriptions", []) if d.get("lang") == "en"), "")
        findings.append({"cve_id": cve.get("id"), "severity": sev, "cvss": score,
                         "summary": desc[:300],
                         "published": cve.get("published"),
                         "reference": f"https://nvd.nist.gov/vuln/detail/{cve.get('id')}"})
    findings.sort(key=lambda f: (_SEV_ORDER.get(f["severity"], 0), f.get("cvss") or 0), reverse=True)
    out = {"product": name, "version": version, "cpe": cpe,
           "matched": bool(findings), "total": j.get("totalResults", 0), "findings": findings[:25]}
    _cache[ck] = {"at": time.time(), "data": out}
    return out


def nvd_scan(products: List[Dict[str, str]]) -> Dict[str, Any]:
    products = [p for p in (products or []) if p.get("name")]
    if not products:
        return {"ok": True, "products_scanned": 0, "results": [], "critical": 0, "high": 0,
                "source": "https://nvd.nist.gov", "scanned_at": _now()}
    truncated = len(products) > _MAX_PRODUCTS
    products = products[:_MAX_PRODUCTS]
    gap = _rate_gap()
    results, all_find = [], []
    for i, p in enumerate(products):
        res = _query(p)
        results.append(res)
        all_find.extend(res.get("findings", []))
        if i < len(products) - 1:
            time.sleep(gap)
    return {
        "ok": True, "products_scanned": len(products),
        "vulnerable_products": len([r for r in results if r.get("matched")]),
        "results": results,
        "critical": len([f for f in all_find if f["severity"] == "CRITICAL"]),
        "high": len([f for f in all_find if f["severity"] == "HIGH"]),
        "truncated": truncated,
        "note": ("Scan truncated to first %d products; add an NVD key in Integrations for faster, larger scans." % _MAX_PRODUCTS) if truncated else None,
        "source": "https://nvd.nist.gov (National Vulnerability Database)",
        "scanned_at": _now(),
    }
