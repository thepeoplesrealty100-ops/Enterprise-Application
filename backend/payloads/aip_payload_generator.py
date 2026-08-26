"""
backend/payloads/aip_payload_generator.py
=========================================
AIP Payload Generator — the ontology-driven, audited bridge between the
pre-populated MITRE payload generator and the GACyber CheatSheet Library.

"AIP" here follows the Palantir AIP pattern (see cheatsheet_ontology.py):
an agent produces an operational plan by SELECTING from a governed ontology
of real, pre-authorized objects (cheatsheet tools + MITRE-tagged payloads),
never by inventing tradecraft. Every generation is:

  1. AUTHORIZATION-GATED  — target must pass scope + insurance (check_authorization_and_scope)
  2. ONTOLOGY-BOUNDED     — commands trace to a real cheatsheet entry or a
                            pre-populated MITRE payload; nothing is fabricated
  3. AUDIT-SIGNED         — the generated plan is PQC-signed (ML-DSA) and logged
  4. SAFETY-BOUNDED       — social-engineering / phishing categories are never
                            emitted as executable payloads (reference only)

The optional `llm` hook lets an operator ask Claude to PRIORITIZE / ORDER the
bounded catalog for a specific engagement context. The LLM never adds commands
outside the ontology — it only ranks and annotates what the ontology already
authorized. If no llm is supplied, generation is fully deterministic.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .payload_generator import PayloadGenerator
from .cheatsheet_ontology import CheatsheetOntology

logger = logging.getLogger(__name__)


class AIPPayloadGenerator:
    """
    Ontology-driven payload generator.

    Parameters
    ----------
    db : DuckDBManager, optional
        Used for authorization gating, PQC audit persistence, and payload
        execution logging. If None, runs in "unbound" mode (no gate / no
        persistence) — suitable for offline planning only.
    llm : callable, optional
        A function llm(prompt: str) -> str used to rank/annotate the bounded
        catalog. Must never be relied on to produce commands.
    pqc : PQCAuditManager, optional
        Injected signer; if None, one is lazily created when db is present.
    """

    def __init__(self, db=None, llm: Optional[Callable[[str], str]] = None, pqc=None):
        self.db = db
        self.llm = llm
        self._pqc = pqc
        self.base = PayloadGenerator()
        self.ontology = CheatsheetOntology()

    # ------------------------------------------------------------------
    # Signing helper
    # ------------------------------------------------------------------

    def _get_pqc(self):
        if self._pqc is None:
            try:
                from crypto.pqc_manager import PQCAuditManager
                self._pqc = PQCAuditManager()
            except Exception as e:
                logger.warning("PQC signer unavailable for AIP generator: %s", e)
        return self._pqc

    def _sign_and_log(self, plan: Dict[str, Any], operator_id: str) -> Optional[str]:
        pqc = self._get_pqc()
        if not pqc:
            return None
        try:
            signed = pqc.sign_agent_action(
                agent_id="aip-payload-generator",
                action_payload={
                    "target": plan["target"],
                    "phase": plan["phase"],
                    "payload_count": plan["summary"]["total_payloads"],
                    "sources": plan["summary"]["cheatsheet_sources"],
                },
                operator_id=operator_id,
            )
            plan["pqc_signature"] = signed["pqc_signature"]
            plan["pqc_entry_id"] = signed["entry_id"]
            plan["pqc_algorithm"] = signed["algorithm"]
            if self.db:
                self.db.insert_pqc_audit_entry({
                    "entry_id":     signed["entry_id"],
                    "agent_id":     "aip-payload-generator",
                    "operator_id":  operator_id,
                    "action_type":  "aip_payload_generation",
                    "action_detail": json.dumps({
                        "target": plan["target"], "phase": plan["phase"],
                    }),
                    "payload_hash": signed["payload_hash"],
                    "pqc_signature":signed["pqc_signature"],
                    "algorithm":    signed["algorithm"],
                    "public_key":   signed["public_key"],
                })
            return signed["entry_id"]
        except Exception as e:
            logger.warning("AIP plan signing failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------

    def _authorize(self, target: str, operator_id: str) -> Dict[str, Any]:
        """
        Run the scope+insurance gate. Returns the authorization result.
        Raises the underlying AuthorizationError if the gate blocks.
        """
        if not self.db:
            return {"authorized": None, "note": "no db — authorization not enforced (offline planning)"}
        from tools.authorization import check_authorization_and_scope
        return check_authorization_and_scope(target, "aip_payload_generation", operator_id, db=self.db)

    # ------------------------------------------------------------------
    # Core generation
    # ------------------------------------------------------------------

    def generate(
        self,
        target: str,
        phase: str,
        operator_id: str = "system",
        domain: str = "",
        use_llm: bool = False,
        max_cheatsheet_entries: int = 8,
    ) -> Dict[str, Any]:
        """
        Generate an ontology-bounded payload plan for one phase.

        Returns a structured plan:
          {
            plan_id, target, phase, generated_at,
            authorization: {...},
            mitre_payloads: [ {command, technique_id, ...} ],   # pre-populated
            cheatsheet_payloads: [ {command, source_id, ...} ], # from library
            ontology_refs: [ {id, title, category} ],
            llm_prioritization: {...} | null,
            summary: {...},
            pqc_signature, pqc_entry_id
          }
        """
        # 1. Authorization gate (raises AuthorizationError if blocked)
        auth = self._authorize(target, operator_id)

        # 2. Pre-populated MITRE payloads for this phase
        try:
            mitre = self.base.generate_phase(phase, target, domain=domain) \
                if phase == "recon_passive" else self.base.generate_phase(phase, target)
        except Exception as e:
            logger.info("base.generate_phase(%s) fallback: %s", phase, e)
            mitre = []

        # 3. Real commands drawn from the cheatsheet ontology (interweave)
        cheat_cmds = self.ontology.resolve_commands(
            phase=phase, target=target, limit_entries=max_cheatsheet_entries,
        )

        # 4. Ontology references used (traceability)
        ontology_refs = self.ontology.resolve(phase=phase, limit=max_cheatsheet_entries)

        plan: Dict[str, Any] = {
            "plan_id":       str(uuid.uuid4()),
            "target":        target,
            "phase":         phase,
            "operator_id":   operator_id,
            "generated_at":  datetime.now(timezone.utc).isoformat(),
            "authorization": auth,
            "mitre_payloads":       mitre if isinstance(mitre, list) else [],
            "cheatsheet_payloads":  cheat_cmds,
            "ontology_refs":        ontology_refs,
            "llm_prioritization":   None,
        }

        plan["summary"] = {
            "total_payloads": len(plan["mitre_payloads"]) + len(cheat_cmds),
            "mitre_count": len(plan["mitre_payloads"]),
            "cheatsheet_count": len(cheat_cmds),
            "cheatsheet_sources": sorted({c["source_id"] for c in cheat_cmds}),
        }

        # 5. Optional LLM prioritization (bounded to the catalog above)
        if use_llm and self.llm:
            plan["llm_prioritization"] = self._llm_prioritize(plan)

        # 6. Sign + audit
        self._sign_and_log(plan, operator_id)
        return plan

    def _llm_prioritize(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ask the LLM to rank/annotate the ALREADY-BOUNDED catalog. The prompt
        forbids inventing new commands. Returns {ranking, rationale} or an error.
        """
        catalog = [
            {"idx": i, "command": p.get("command", ""), "kind": "mitre",
             "technique": p.get("technique_id", "")}
            for i, p in enumerate(plan["mitre_payloads"])
        ] + [
            {"idx": len(plan["mitre_payloads"]) + i, "command": c["command"],
             "kind": "cheatsheet", "source": c["source_id"]}
            for i, c in enumerate(plan["cheatsheet_payloads"])
        ]
        prompt = (
            "You are an authorized penetration-test planning assistant operating under "
            "a Palantir-AIP-style ontology boundary. You are given a fixed catalog of "
            "pre-authorized commands for an AUTHORIZED engagement. Your ONLY job is to "
            "return a JSON object {\"ranking\":[idx,...],\"rationale\":\"...\"} ordering "
            "the catalog by operational priority for the phase '" + plan["phase"] + "' "
            "against target '" + plan["target"] + "'. Do NOT invent, modify, or add any "
            "command. Use only the provided indices.\n\nCATALOG:\n"
            + json.dumps(catalog, indent=2)[:6000]
        )
        try:
            raw = self.llm(prompt)
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            # Validate indices are within the catalog (bound enforcement)
            valid_idx = {c["idx"] for c in catalog}
            ranking = [i for i in parsed.get("ranking", []) if i in valid_idx]
            return {"ranking": ranking, "rationale": parsed.get("rationale", ""),
                    "bounded": True}
        except Exception as e:
            return {"error": str(e), "bounded": True}

    # ------------------------------------------------------------------
    # Full engagement (all phases)
    # ------------------------------------------------------------------

    def generate_engagement(
        self,
        target: str,
        operator_id: str = "system",
        domain: str = "",
        phases: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Generate ontology-bounded plans across all (or given) phases."""
        phases = phases or [
            "recon_passive", "recon_active", "enumeration", "web_application",
            "vulnerability_analysis", "post_exploitation_assessment",
            "encryption_analysis",
        ]
        # Authorize once up front (each generate() re-checks defensively)
        auth = self._authorize(target, operator_id)
        engagement: Dict[str, Any] = {
            "engagement_id": str(uuid.uuid4()),
            "target": target,
            "operator_id": operator_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "authorization": auth,
            "phases": {},
        }
        totals = {"mitre": 0, "cheatsheet": 0}
        for ph in phases:
            try:
                plan = self.generate(target, ph, operator_id, domain=domain)
                engagement["phases"][ph] = plan
                totals["mitre"] += plan["summary"]["mitre_count"]
                totals["cheatsheet"] += plan["summary"]["cheatsheet_count"]
            except Exception as e:
                engagement["phases"][ph] = {"error": str(e)}
        engagement["summary"] = {
            "phase_count": len(phases),
            "total_mitre_payloads": totals["mitre"],
            "total_cheatsheet_payloads": totals["cheatsheet"],
            "total_payloads": totals["mitre"] + totals["cheatsheet"],
        }
        return engagement

    # ------------------------------------------------------------------
    # Ontology introspection
    # ------------------------------------------------------------------

    def ontology_graph(self) -> Dict[str, Any]:
        return self.ontology.ontology_graph()

    def status(self) -> Dict[str, Any]:
        return {
            "ontology": self.ontology.stats(),
            "authorization_enforced": self.db is not None,
            "llm_available": self.llm is not None,
            "pqc_signing": self._get_pqc() is not None,
        }
