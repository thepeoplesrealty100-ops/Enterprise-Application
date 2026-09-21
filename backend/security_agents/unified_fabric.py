"""
backend/security_agents/unified_fabric.py
=========================================
Unified Security Fabric — ONE module that consolidates the seven former
micro-modules (Managed Detection & Response, Zero Trust Enforcement, SASE
Network Tunnel, Privileged Access Management, DNS Web Filtering, Email
Security Gateway, Data Loss Prevention) into a single governed control plane.

Grounding (real frameworks, researched):
  • NSA / CISA Zero Trust Maturity Model — 7 pillars + cross-cutting
    capabilities (Visibility & Analytics, Automation & Orchestration,
    Governance). Each Fabric capability is mapped to a ZT pillar and scored on
    the CISA maturity ladder: Traditional → Initial → Advanced → Optimal.
    (Refs: CISA Zero Trust Maturity Model v2.0; NSA "Advancing Zero Trust
    Maturity" pillar CSIs, 2024.)
  • Palantir AIP Ontology — the Fabric is modeled as OBJECTS (capabilities,
    pillars, controls, events) + LINKS + bounded ACTIONS, so the autonomous
    "AIP" layer can only act through governed, audited operations.
  • NASA continuous-monitoring / defense-in-depth posture — the Fabric keeps a
    continuously-updated posture score rather than point-in-time checks.

This module does not itself enforce network controls on third-party hosts; it
is the unified state, posture, policy, and event model that the JAKAL control
plane and its dashboards read from. Enforcement integrations are pluggable.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── CISA Zero Trust Maturity ladder ────────────────────────────────────────
MATURITY_LEVELS = ["Traditional", "Initial", "Advanced", "Optimal"]
_MATURITY_SCORE = {"Traditional": 25, "Initial": 50, "Advanced": 75, "Optimal": 100}

# ── The seven Fabric capabilities, each mapped to a ZT pillar ──────────────
# key: stable id  | pillar: NSA/CISA ZT pillar | default maturity + controls
FABRIC_CAPABILITIES: Dict[str, Dict[str, Any]] = {
    "mdr": {
        "label": "Managed Detection & Response",
        "pillar": "Visibility & Analytics",
        "icon": "shield-check",
        "description": "24/7 detection and response across endpoint, network, and cloud telemetry.",
        "default_maturity": "Advanced",
        "controls": [
            "Continuous endpoint telemetry (EDR)",
            "Network detection & response (NDR)",
            "SIEM correlation + UEBA",
            "24/7 SOC triage & escalation",
            "MITRE ATT&CK detection coverage mapping",
        ],
        "metrics": {"mttd_minutes": 8, "mttr_minutes": 42, "coverage_pct": 87},
    },
    "zero_trust": {
        "label": "Zero Trust Enforcement",
        "pillar": "User / Device",
        "icon": "lock",
        "description": "Every access request is authenticated, authorized, and continuously validated.",
        "default_maturity": "Advanced",
        "controls": [
            "Phishing-resistant MFA (FIDO2/WebAuthn)",
            "Device health attestation before access",
            "Per-request policy decision point (PDP/PEP)",
            "Continuous session risk scoring",
            "Least-privilege default-deny policy",
        ],
        "metrics": {"policies_enforced": 214, "deny_rate_pct": 3.4, "mfa_coverage_pct": 96},
    },
    "sase": {
        "label": "SASE Network Tunnel",
        "pillar": "Network & Environment",
        "icon": "globe-lock",
        "description": "Secure Access Service Edge — identity-aware, encrypted tunnels for all users.",
        "default_maturity": "Initial",
        "controls": [
            "Identity-aware software-defined perimeter",
            "Microsegmentation of east-west traffic",
            "TLS 1.3 / encrypted transport everywhere",
            "Inline CASB for sanctioned SaaS",
            "PQC-ready tunnel key exchange (ML-KEM roadmap)",
        ],
        "metrics": {"active_tunnels": 128, "segments": 34, "encrypted_pct": 100},
    },
    "pam": {
        "label": "Privileged Access Management",
        "pillar": "User / Device",
        "icon": "key-round",
        "description": "Just-in-time, fully-audited access to critical systems; no standing privilege.",
        "default_maturity": "Advanced",
        "controls": [
            "Just-in-time (JIT) privilege elevation",
            "Credential vaulting + automatic rotation",
            "Session recording & keystroke audit",
            "Approval workflow for tier-0 assets",
            "Zero standing privilege (ZSP) target",
        ],
        "metrics": {"vaulted_accounts": 340, "jit_grants_24h": 27, "standing_admins": 4},
    },
    "dns_filter": {
        "label": "DNS Web Filtering",
        "pillar": "Network & Environment",
        "icon": "shield-off",
        "description": "Protective DNS blocking malware, C2, and phishing domains at resolution time.",
        "default_maturity": "Advanced",
        "controls": [
            "Protective DNS (PDNS) with threat-intel feeds",
            "Newly-registered-domain (NRD) blocking",
            "DNS-over-HTTPS/TLS enforcement",
            "Category-based web filtering",
            "DGA / tunneling detection",
        ],
        "metrics": {"queries_24h": 1840000, "blocked_24h": 12400, "feeds": 9},
    },
    "email_security": {
        "label": "Email Security Gateway",
        "pillar": "Application & Workload",
        "icon": "mail-x",
        "description": "Inbound/outbound mail defense: phishing, malware, BEC, and impersonation.",
        "default_maturity": "Advanced",
        "controls": [
            "SPF / DKIM / DMARC enforcement",
            "Attachment detonation sandbox",
            "URL rewriting + time-of-click analysis",
            "Impersonation / BEC detection",
            "Outbound content inspection",
        ],
        "metrics": {"messages_24h": 96000, "quarantined_24h": 2100, "dmarc_pct": 100},
    },
    "dlp": {
        "label": "Data Loss Prevention",
        "pillar": "Data",
        "icon": "database-zap",
        "description": "Classify, monitor, and protect sensitive data across endpoint, network, and cloud.",
        "default_maturity": "Initial",
        "controls": [
            "Automated data classification & labeling",
            "Egress inspection (endpoint / network / cloud)",
            "Encryption enforcement for labeled data",
            "Insider-risk policy triggers",
            "Tokenization of regulated fields (PII/PCI)",
        ],
        "metrics": {"classified_stores": 58, "incidents_24h": 14, "encrypted_at_rest_pct": 92},
    },
}

# Cross-cutting ZT capabilities that span all pillars
CROSS_CUTTING = ["Visibility & Analytics", "Automation & Orchestration", "Governance"]


class UnifiedSecurityFabric:
    """
    Single consolidated control plane over the seven security capabilities.

    Reads/writes fabric state through DuckDBManager (tables: fabric_modules,
    fabric_events, zt_posture_assessments). If a capability row is missing it
    is seeded from FABRIC_CAPABILITIES defaults.
    """

    def __init__(self, db=None):
        self.db = db
        if self.db:
            try:
                self.seed_defaults()
            except Exception as e:
                logger.warning("Fabric seed skipped: %s", e)

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------

    def seed_defaults(self) -> Dict[str, Any]:
        """Insert any missing capability rows from defaults. Idempotent."""
        if not self.db:
            return {"seeded": 0, "note": "no db"}
        seeded = 0
        for key, cap in FABRIC_CAPABILITIES.items():
            existing = self.db.get_fabric_module(key)
            if not existing:
                self.db.upsert_fabric_module({
                    "module_key":  key,
                    "label":       cap["label"],
                    "pillar":      cap["pillar"],
                    "icon":        cap["icon"],
                    "description": cap["description"],
                    "maturity":    cap["default_maturity"],
                    "status":      "active",
                    "controls":    cap["controls"],
                    "metrics":     cap["metrics"],
                })
                seeded += 1
        return {"seeded": seeded, "total_capabilities": len(FABRIC_CAPABILITIES)}

    # ------------------------------------------------------------------
    # Read models
    # ------------------------------------------------------------------

    def _default_view(self, key: str) -> Dict[str, Any]:
        cap = FABRIC_CAPABILITIES[key]
        return {
            "module_key": key,
            "label": cap["label"],
            "pillar": cap["pillar"],
            "icon": cap["icon"],
            "description": cap["description"],
            "maturity": cap["default_maturity"],
            "status": "active",
            "controls": cap["controls"],
            "metrics": cap["metrics"],
            "maturity_score": _MATURITY_SCORE[cap["default_maturity"]],
        }

    def get_capability(self, key: str) -> Optional[Dict[str, Any]]:
        if key not in FABRIC_CAPABILITIES:
            return None
        if self.db:
            row = self.db.get_fabric_module(key)
            if row:
                row["maturity_score"] = _MATURITY_SCORE.get(row.get("maturity", "Traditional"), 25)
                return row
        return self._default_view(key)

    def status(self) -> Dict[str, Any]:
        """Full consolidated Fabric status — all seven capabilities in one view."""
        capabilities = []
        for key in FABRIC_CAPABILITIES:
            cap = self.get_capability(key)
            if cap:
                capabilities.append(cap)
        posture = self.posture(capabilities)
        return {
            "fabric": "Unified Security Fabric",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "capability_count": len(capabilities),
            "capabilities": capabilities,
            "posture": posture,
            "cross_cutting": CROSS_CUTTING,
        }

    def capability_summary(self) -> Dict[str, Any]:
        """v3.0 Phase 4.3: light summary of which of the 7 Fabric
        capabilities are currently considered active, using only data
        that already exists -- each capability's persisted (or default)
        status field, plus whether any fabric_events have ever been
        recorded for it. No new collection logic, no polling of the
        underlying subsystems -- `status()` above already returns full
        detail per capability; this is the lighter "just tell me what's
        active" view."""
        summary = []
        for key in FABRIC_CAPABILITIES:
            cap = self.get_capability(key)
            if not cap:
                continue
            has_recorded_activity = bool(
                self.db and self.db.list_fabric_events(module_key=key, limit=1)
            )
            summary.append({
                "module_key": key,
                "label": cap["label"],
                "pillar": cap["pillar"],
                "status": cap["status"],
                "considered_active": cap["status"] == "active",
                "has_recorded_activity": has_recorded_activity,
            })
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_capabilities": len(summary),
            "active_count": sum(1 for s in summary if s["considered_active"]),
            "capabilities": summary,
        }

    # ------------------------------------------------------------------
    # Zero Trust posture scoring
    # ------------------------------------------------------------------

    def posture(self, capabilities: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Compute an aggregate Zero Trust maturity posture across all pillars,
        following the CISA ZTMM ladder. Returns overall score, level, and a
        per-pillar breakdown.
        """
        if capabilities is None:
            capabilities = [self.get_capability(k) for k in FABRIC_CAPABILITIES]
            capabilities = [c for c in capabilities if c]

        # Aggregate by pillar (average of member capabilities)
        pillar_scores: Dict[str, List[int]] = {}
        for cap in capabilities:
            pillar = cap.get("pillar", "Unknown")
            pillar_scores.setdefault(pillar, []).append(
                cap.get("maturity_score", _MATURITY_SCORE.get(cap.get("maturity", "Traditional"), 25))
            )

        pillar_breakdown = {}
        for pillar, scores in pillar_scores.items():
            avg = round(sum(scores) / len(scores), 1)
            pillar_breakdown[pillar] = {
                "score": avg,
                "level": self._score_to_level(avg),
                "capabilities": len(scores),
            }

        overall = round(
            sum(c.get("maturity_score", 25) for c in capabilities) / max(len(capabilities), 1), 1
        )
        return {
            "overall_score": overall,
            "overall_level": self._score_to_level(overall),
            "scale": MATURITY_LEVELS,
            "by_pillar": pillar_breakdown,
        }

    @staticmethod
    def _score_to_level(score: float) -> str:
        if score >= 88:
            return "Optimal"
        if score >= 63:
            return "Advanced"
        if score >= 38:
            return "Initial"
        return "Traditional"

    def record_posture_snapshot(self, operator_id: str = "system") -> Dict[str, Any]:
        """Persist a point-in-time posture snapshot for trend analysis."""
        posture = self.posture()
        if self.db:
            try:
                self.db.insert_posture_assessment({
                    "assessment_id": str(uuid.uuid4()),
                    "overall_score": posture["overall_score"],
                    "overall_level": posture["overall_level"],
                    "by_pillar": posture["by_pillar"],
                    "operator_id": operator_id,
                })
            except Exception as e:
                logger.warning("posture snapshot persist failed: %s", e)
        return posture

    # ------------------------------------------------------------------
    # Mutations (bounded ACTIONS)
    # ------------------------------------------------------------------

    def set_maturity(self, key: str, maturity: str, operator_id: str = "system") -> Dict[str, Any]:
        if key not in FABRIC_CAPABILITIES:
            return {"error": f"unknown capability '{key}'"}
        if maturity not in MATURITY_LEVELS:
            return {"error": f"invalid maturity '{maturity}'", "valid": MATURITY_LEVELS}
        if self.db:
            cur = self.db.get_fabric_module(key) or self._default_view(key)
            cur["maturity"] = maturity
            self.db.upsert_fabric_module({
                "module_key": key,
                "label": cur["label"], "pillar": cur["pillar"], "icon": cur["icon"],
                "description": cur["description"], "maturity": maturity,
                "status": cur.get("status", "active"),
                "controls": cur["controls"], "metrics": cur["metrics"],
            })
            self.record_event(key, "maturity_change",
                              f"{key} maturity set to {maturity}", operator_id)
        return {"module_key": key, "maturity": maturity,
                "maturity_score": _MATURITY_SCORE[maturity]}

    def set_status(self, key: str, status: str, operator_id: str = "system") -> Dict[str, Any]:
        if key not in FABRIC_CAPABILITIES:
            return {"error": f"unknown capability '{key}'"}
        if status not in ("active", "degraded", "disabled"):
            return {"error": f"invalid status '{status}'"}
        if self.db:
            cur = self.db.get_fabric_module(key) or self._default_view(key)
            self.db.upsert_fabric_module({
                "module_key": key,
                "label": cur["label"], "pillar": cur["pillar"], "icon": cur["icon"],
                "description": cur["description"], "maturity": cur.get("maturity", "Initial"),
                "status": status, "controls": cur["controls"], "metrics": cur["metrics"],
            })
            self.record_event(key, "status_change", f"{key} status -> {status}", operator_id)
        return {"module_key": key, "status": status}

    def record_event(self, module_key: str, event_type: str, detail: str,
                     operator_id: str = "system", severity: str = "info") -> Dict[str, Any]:
        evt = {
            "event_id": str(uuid.uuid4()),
            "module_key": module_key,
            "event_type": event_type,
            "detail": detail,
            "severity": severity,
            "operator_id": operator_id,
        }
        if self.db:
            try:
                self.db.insert_fabric_event(evt)
            except Exception as e:
                logger.warning("fabric event persist failed: %s", e)
        return evt

    def recent_events(self, module_key: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.db:
            return []
        return self.db.list_fabric_events(module_key=module_key, limit=limit)

    # ------------------------------------------------------------------
    # Ontology export (OBJECTS + LINKS) for the AIP layer / dashboard
    # ------------------------------------------------------------------

    def ontology_graph(self) -> Dict[str, Any]:
        objects: List[Dict[str, Any]] = [
            {"id": "fabric:root", "type": "Fabric", "label": "Unified Security Fabric"}
        ]
        links: List[Dict[str, Any]] = []
        pillars = set()
        for key, cap in FABRIC_CAPABILITIES.items():
            pillars.add(cap["pillar"])
            objects.append({
                "id": f"cap:{key}", "type": "Capability",
                "label": cap["label"], "pillar": cap["pillar"],
            })
            links.append({"from": "fabric:root", "to": f"cap:{key}", "rel": "includes"})
            links.append({"from": f"cap:{key}", "to": f"pillar:{cap['pillar']}", "rel": "advances"})
            for ctrl in cap["controls"]:
                cid = "ctrl:" + str(abs(hash(key + ctrl)) % (10 ** 8))
                objects.append({"id": cid, "type": "Control", "label": ctrl})
                links.append({"from": f"cap:{key}", "to": cid, "rel": "implements"})
        for p in pillars:
            objects.append({"id": f"pillar:{p}", "type": "ZTPillar", "label": p})
        return {"objects": objects, "links": links,
                "stats": {"capabilities": len(FABRIC_CAPABILITIES), "pillars": len(pillars)}}
