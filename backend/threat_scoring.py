"""
backend/threat_scoring.py
============================
Lightweight, dependency-free severity scoring for inbound recon/threat
telemetry (JAKAL v2.5 — Ares Unified Control Plane).

This is intentionally a plain heuristic, not an LLM call: recon ingestion
needs to score potentially high volumes of findings without spending
Energy Core budget or LLM latency on every single event. The existing
AIPPayloadGenerator._llm_prioritize() LLM path is still available upstream
for engagement planning; this module is downstream triage -- "how urgent
is this one finding" -- and stays fast and fully deterministic so it's
testable without a model in the loop.

score_recon_finding() returns a float in [0.0, 1.0]. Callers that want to
gate human-in-the-loop approval on a threshold (e.g. > 0.8) do so
explicitly -- this module never creates approval requests itself, it only
scores.
"""
from typing import Any, Dict

# Keyword -> severity weight. Deliberately explainable rather than an
# opaque model score: every contribution here is inspectable and testable.
_CRITICAL_KEYWORDS: Dict[str, float] = {
    "unauthenticated rce": 0.95, "remote code execution": 0.9, "rce": 0.85,
    "domain admin": 0.9, "credential dump": 0.85, "ransomware": 0.95,
    "critical": 0.8, "exploited in the wild": 0.9, "zero-day": 0.9, "0day": 0.9,
}
_HIGH_KEYWORDS: Dict[str, float] = {
    "exposed": 0.6, "open port": 0.4, "default credentials": 0.75,
    "unpatched": 0.65, "sql injection": 0.75, "privilege escalation": 0.75,
    "shadow ai": 0.7, "shadow_ai": 0.7, "data leakage": 0.7, "dlp": 0.6,
    "phishing": 0.55, "malware": 0.75, "lateral movement": 0.7,
}
_MEDIUM_KEYWORDS: Dict[str, float] = {
    "misconfiguration": 0.4, "weak cipher": 0.35, "self-signed": 0.25,
    "outdated": 0.35, "informational": 0.1, "verbose error": 0.2,
}

# A minimum severity per declared threat_category, so an ambiguous or
# empty finding_summary still lands somewhere sane instead of at the floor.
_CATEGORY_FLOOR: Dict[str, float] = {
    "SHADOW_AI": 0.5, "SOC2_VIOLATION": 0.55, "EXPOSED_SERVICE": 0.4,
    "DLP_MATCH": 0.55, "RANSOMWARE": 0.9, "PHISHING": 0.45,
}

_UNCLASSIFIED_FLOOR = 0.15  # logged, not ignored -- distinct from 0.0


def score_recon_finding(payload: Dict[str, Any]) -> float:
    """
    Deterministic 0.0-1.0 severity score for one inbound recon/threat
    finding. Combines, in order of trust:
      1. an explicit numeric hint the caller supplies (indicators.cvss_score
         on a 0-10 scale, or indicators.severity_hint already on 0.0-1.0) --
         weighted most heavily since it's caller-asserted ground truth;
      2. keyword matches in finding_summary / threat_category text;
      3. a per-threat_category floor so a bare category still scores sanely.
    The final score is the MAX of every signal found, not a sum/average --
    one clearly critical signal should not be diluted by several mild ones.
    """
    text = " ".join(
        str(payload.get(k, "")) for k in ("finding_summary", "threat_category")
    ).lower()
    indicators = payload.get("indicators") or {}

    scores = []

    cvss = indicators.get("cvss_score")
    if isinstance(cvss, (int, float)) and 0 <= cvss <= 10:
        scores.append(min(cvss / 10.0, 1.0))

    hint = indicators.get("severity_hint")
    if isinstance(hint, (int, float)) and 0 <= hint <= 1:
        scores.append(float(hint))

    for table in (_CRITICAL_KEYWORDS, _HIGH_KEYWORDS, _MEDIUM_KEYWORDS):
        for kw, weight in table.items():
            if kw in text:
                scores.append(weight)

    category = str(payload.get("threat_category", "")).upper()
    floor = _CATEGORY_FLOOR.get(category)
    if floor is not None:
        scores.append(floor)

    if not scores:
        return _UNCLASSIFIED_FLOOR

    return round(max(scores), 4)
