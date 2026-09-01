"""
backend/security_agents/compliance_constraints.py
==================================================
Compliance-aware containment constraints — JAKAL Track A.

Before a containment action (quarantine/isolate) executes, this module
validates against HIPAA, SOC2, PCI-DSS requirements stored in the org's
compliance posture. A containment that would violate data residency,
breach a patient/cardholder privacy boundary, or trigger a compliance
audit exception is blocked with a detailed reason — operators can
override with explicit approval, but the constraint is documented and
audited.

Grounding: HIPAA 45 CFR §164.308(a)(7) (Contingency Planning), SOC2
CC7 (System Monitoring), PCI-DSS 1.2 (Firewall Configuration Review).
"""

import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class ComplianceConstraint:
    """Base class for compliance validators."""
    name: str
    applicable_frameworks: List[str]

    def validate(self, action_type: str, target: str, org_compliance_posture: Dict[str, Any]) -> Optional[str]:
        """
        Return None if compliant; otherwise return a human-readable reason
        explaining the compliance violation.
        """
        raise NotImplementedError


class HIPAADataResidencyConstraint(ComplianceConstraint):
    """HIPAA 45 CFR §164.308(a)(7): Patient data must remain in
    configured geographic boundaries. Isolating a host in a different
    region risks losing access to backups and recovery infrastructure."""
    name = "hipaa_data_residency"
    applicable_frameworks = ["HIPAA", "HIPAA+Business_Associate"]

    def validate(self, action_type: str, target: str,
                 org_compliance_posture: Dict[str, Any]) -> Optional[str]:
        if action_type not in ("isolate_host_staged", "quarantine_host_staged"):
            return None
        if "HIPAA" not in org_compliance_posture.get("frameworks", []):
            return None

        required_regions = org_compliance_posture.get("hipaa_allowed_regions", [])
        if not required_regions:
            return None

        # Extract region from target (format: "region-hostname" or lookup via IP geolocation).
        # For MVP: simple heuristic — if target contains region prefix, check it.
        target_lower = target.lower()
        for region in required_regions:
            if region.lower() in target_lower:
                return None

        return (f"HIPAA compliance: target '{target}' is not in allowed data residency regions "
                f"{required_regions}. Isolation would breach geographic containment requirement "
                f"(45 CFR §164.308(a)(7)).")


class SOC2AvailabilityConstraint(ComplianceConstraint):
    """SOC2 CC7: System Monitoring and Incident Management. Isolating a
    host in a critical service path requires explicit SOC2 audit approval."""
    name = "soc2_availability"
    applicable_frameworks = ["SOC2", "SOC2_Type2"]

    def validate(self, action_type: str, target: str,
                 org_compliance_posture: Dict[str, Any]) -> Optional[str]:
        if action_type not in ("isolate_host_staged", "quarantine_host_staged"):
            return None
        if "SOC2" not in org_compliance_posture.get("frameworks", []):
            return None

        critical_services = org_compliance_posture.get("soc2_critical_service_hosts", [])
        if target in critical_services:
            return (f"SOC2 compliance: '{target}' is listed as critical for service availability. "
                    f"Isolation requires explicit SOC2 audit exception (CC7). "
                    f"Override requires written approval from Compliance Officer.")

        return None


class PCIDSSCardholderConstraint(ComplianceConstraint):
    """PCI-DSS 1.2: Firewall Configuration Review. Isolating a host in
    the cardholder data environment (CDE) triggers a compliance audit."""
    name = "pci_dss_cde"
    applicable_frameworks = ["PCI-DSS"]

    def validate(self, action_type: str, target: str,
                 org_compliance_posture: Dict[str, Any]) -> Optional[str]:
        if action_type not in ("isolate_host_staged", "quarantine_host_staged"):
            return None
        if "PCI-DSS" not in org_compliance_posture.get("frameworks", []):
            return None

        cde_hosts = org_compliance_posture.get("pci_dss_cde_hosts", [])
        if target in cde_hosts:
            return (f"PCI-DSS compliance: '{target}' is in the Cardholder Data Environment (CDE). "
                    f"Isolation triggers mandatory audit review (PCI-DSS 1.2). "
                    f"Proceed only with documented audit exception.")

        return None


_CONSTRAINTS = [
    HIPAADataResidencyConstraint(),
    SOC2AvailabilityConstraint(),
    PCIDSSCardholderConstraint(),
]


def validate_containment_compliance(action_type: str, target: str,
                                     org_compliance_posture: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate a containment action against all applicable compliance
    constraints. Return a dict:
    {
        "compliant": bool,
        "violations": [{"constraint": str, "reason": str}, ...],
        "requires_audit_exception": bool,
    }
    """
    violations = []
    for constraint in _CONSTRAINTS:
        reason = constraint.validate(action_type, target, org_compliance_posture)
        if reason:
            violations.append({
                "constraint": constraint.name,
                "reason": reason,
            })

    requires_audit = any("audit" in v["reason"].lower() or "exception" in v["reason"].lower()
                         for v in violations)

    return {
        "compliant": len(violations) == 0,
        "violations": violations,
        "requires_audit_exception": requires_audit,
    }
