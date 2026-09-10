"""
services/vuln_scanner.py — JAKAL shared vulnerability-scan engine (v1.0)

The ONE real scanner both the capabilities engine and the endpoint-agent
inventory pipeline call. No seeded data, no simulation.

  * osv_scan(packages)  — live OSV.dev scan (open-source ecosystems: PyPI, npm,
                          Go, Maven, RubyGems, crates.io, NuGet…). No API key.
                          Two-phase: batch query finds vulnerable packages,
                          then unique vuln records are fetched for real
                          severity (CVSS base score, or GHSA severity label).
  * scan_manifest(paths)— parse pinned requirements files → osv_scan().

Every result carries a truthful `source`; on network failure it returns a
truthful `error`, never fabricated rows.
"""
from __future__ import annotations

import concurrent.futures as _cf
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests

logger = logging.getLogger("vuln_scanner")

OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns/"
_DEFAULT_ECOSYSTEM = "PyPI"
_SEV_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}
_MAX_DETAIL_FETCH = 120          # bound latency on huge inventories
_session = requests.Session()
_session.headers.update({"user-agent": "JAKAL-VulnScanner/1.0"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── CVSS 3.x base-score calculator (FIRST.org spec) ───────────────────────
_CVSS_METRICS = {
    "AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2},
    "AC": {"L": 0.77, "H": 0.44},
    "PR_U": {"N": 0.85, "L": 0.62, "H": 0.27},
    "PR_C": {"N": 0.85, "L": 0.68, "H": 0.5},
    "UI": {"N": 0.85, "R": 0.62},
    "CIA": {"H": 0.56, "L": 0.22, "N": 0.0},
}


def _cvss3_base(vector: str) -> float:
    try:
        parts = dict(p.split(":") for p in vector.split("/") if ":" in p and not p.startswith("CVSS"))
        scope_changed = parts.get("S") == "C"
        av = _CVSS_METRICS["AV"][parts["AV"]]
        ac = _CVSS_METRICS["AC"][parts["AC"]]
        pr = _CVSS_METRICS["PR_C" if scope_changed else "PR_U"][parts["PR"]]
        ui = _CVSS_METRICS["UI"][parts["UI"]]
        c = _CVSS_METRICS["CIA"][parts["C"]]
        i = _CVSS_METRICS["CIA"][parts["I"]]
        a = _CVSS_METRICS["CIA"][parts["A"]]
        iss = 1 - ((1 - c) * (1 - i) * (1 - a))
        impact = (7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15) if scope_changed \
            else (6.42 * iss)
        expl = 8.22 * av * ac * pr * ui
        if impact <= 0:
            return 0.0
        raw = min((1.08 * (impact + expl)) if scope_changed else (impact + expl), 10.0)
        # round up to one decimal
        import math
        return math.ceil(raw * 10) / 10.0
    except (KeyError, ValueError, ZeroDivisionError):
        return 0.0


def _label_from_score(score: float) -> str:
    if score >= 9.0: return "CRITICAL"
    if score >= 7.0: return "HIGH"
    if score >= 4.0: return "MEDIUM"
    if score > 0: return "LOW"
    return "UNKNOWN"


def _fetch_detail(vuln_id: str) -> Dict[str, Any]:
    try:
        r = _session.get(OSV_VULN_URL + vuln_id, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return {}


def _severity_and_score(full: Dict[str, Any]) -> tuple:
    """Return (label, score) from a full OSV record. Prefers a computed CVSS
    base score; falls back to GHSA database_specific.severity."""
    best = 0.0
    for sev in full.get("severity", []) or []:
        if str(sev.get("type", "")).startswith("CVSS"):
            best = max(best, _cvss3_base(str(sev.get("score", ""))))
    if best > 0:
        return _label_from_score(best), best
    ds = (full.get("database_specific") or {}).get("severity")
    if ds:
        ds = ds.upper().replace("MODERATE", "MEDIUM")
        if ds in _SEV_ORDER:
            return ds, None
    return "UNKNOWN", None


def osv_scan(packages: List[Dict[str, str]], enrich: bool = True) -> Dict[str, Any]:
    """Live OSV.dev scan. packages: [{name, version, ecosystem?}]."""
    packages = [p for p in (packages or []) if p.get("name") and p.get("version")]
    if not packages:
        return {"ok": True, "packages_scanned": 0, "findings": [], "vulnerable_packages": 0,
                "critical": 0, "high": 0, "source": "https://osv.dev", "scanned_at": _now(),
                "note": "No pinned (name+version) packages supplied to scan."}

    queries = [{"package": {"name": p["name"], "ecosystem": p.get("ecosystem", _DEFAULT_ECOSYSTEM)},
                "version": p["version"]} for p in packages]
    try:
        resp = _session.post(OSV_BATCH_URL, json={"queries": queries}, timeout=20)
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except requests.RequestException as e:
        logger.warning("OSV.dev scan failed: %s", e)
        return {"ok": False, "packages_scanned": len(packages), "findings": [],
                "vulnerable_packages": 0, "critical": 0, "high": 0, "source": "https://osv.dev",
                "scanned_at": _now(),
                "error": f"OSV.dev query failed ({e.__class__.__name__}); is outbound network available?"}

    raw: List[Dict[str, Any]] = []
    for pkg, res in zip(packages, results):
        for vuln in (res.get("vulns", []) or []):
            raw.append({"pkg": pkg, "id": vuln.get("id")})

    # Enrich unique vuln ids with real severity (bounded, concurrent).
    detail: Dict[str, Dict[str, Any]] = {}
    unique_ids = list({r["id"] for r in raw if r["id"]})[:_MAX_DETAIL_FETCH]
    if enrich and unique_ids:
        with _cf.ThreadPoolExecutor(max_workers=8) as ex:
            for vid, full in zip(unique_ids, ex.map(_fetch_detail, unique_ids)):
                if full:
                    detail[vid] = full

    findings: List[Dict[str, Any]] = []
    for r in raw:
        pkg, vid = r["pkg"], r["id"]
        full = detail.get(vid, {})
        label, score = _severity_and_score(full) if full else ("UNKNOWN", None)
        aliases = full.get("aliases", [])
        findings.append({
            "package": pkg["name"], "version": pkg["version"],
            "ecosystem": pkg.get("ecosystem", _DEFAULT_ECOSYSTEM),
            "id": vid,
            "cve_id": next((a for a in aliases if str(a).startswith("CVE-")), vid),
            "aliases": aliases,
            "severity": label,
            "cvss": score,
            "summary": (full.get("summary") or "(no summary provided by OSV)")[:300],
            "modified": full.get("modified"),
            "reference": f"https://osv.dev/vulnerability/{vid}",
        })

    findings.sort(key=lambda f: (_SEV_ORDER.get(f["severity"], 0), f.get("cvss") or 0), reverse=True)
    return {
        "ok": True,
        "packages_scanned": len(packages),
        "vulnerable_packages": len({f["package"] for f in findings}),
        "findings": findings,
        "critical": len([f for f in findings if f["severity"] == "CRITICAL"]),
        "high": len([f for f in findings if f["severity"] == "HIGH"]),
        "source": "https://osv.dev (Open Source Vulnerability database)",
        "scanned_at": _now(),
    }


_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*==\s*([A-Za-z0-9._-]+)")


def parse_requirements(path: str) -> List[Dict[str, str]]:
    pkgs: List[Dict[str, str]] = []
    if not path or not os.path.exists(path):
        return pkgs
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                m = _REQ_LINE.match(line)
                if m:
                    pkgs.append({"name": m.group(1), "version": m.group(2), "ecosystem": "PyPI"})
    except OSError as e:
        logger.warning("cannot read requirements %s: %s", path, e)
    return pkgs


def scan_manifest(paths: List[str]) -> Dict[str, Any]:
    pkgs: List[Dict[str, str]] = []
    for p in paths or []:
        pkgs.extend(parse_requirements(p))
    result = osv_scan(pkgs)
    result["manifests"] = [p for p in (paths or []) if os.path.exists(p)]
    return result
