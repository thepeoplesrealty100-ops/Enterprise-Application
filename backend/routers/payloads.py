"""
backend/routers/payloads.py
============================
Payload Generator + Playbook API router for JAKAL v2.1

Endpoints:
  POST  /payloads/generate          — Generate payloads for a specific PTES phase
  POST  /payloads/engagement        — Generate full engagement payload set (all phases)
  POST  /payloads/log-execution     — Log a payload execution to the DB
  GET   /payloads/executions        — List payload executions

  GET   /playbooks                  — List all playbooks (category filter supported)
  GET   /playbooks/{key}            — Get a single playbook by key
  POST  /playbooks/seed             — Seed playbook library to DB
  POST  /playbooks/execute          — Start a playbook execution
  POST  /playbooks/execute/{exec_id}/step  — Mark a step complete
  POST  /playbooks/execute/{exec_id}/finish — Finish a playbook execution
  GET   /playbooks/categories       — List all playbook categories

  GET   /threat-intel               — Search threat intelligence
  POST  /threat-intel/ingest        — Ingest a new threat intel indicator
  GET   /threat-intel/stats         — Threat intel statistics

  GET   /network-map                — Get network map (filter by pentest_id)
  POST  /network-map/host           — Upsert a discovered host

  GET   /vuln-db                    — Search vulnerability database
  POST  /vuln-db/entry              — Add or update a vuln entry
"""

import json
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status as http_status
from pydantic import BaseModel

# ── Local imports ──────────────────────────────────────────────────────────
try:
    from payloads.payload_generator import PayloadGenerator
    from payloads.playbook_library import (
        get_all_playbooks, get_playbook, get_playbooks_by_category,
        list_categories, seed_playbooks_to_db, PLAYBOOKS,
    )
    PAYLOADS_OK = True
except Exception as _e:
    PAYLOADS_OK = False
    _PAYLOAD_ERR = str(_e)

try:
    from database import DuckDBManager, get_db_manager
    _db: Optional[DuckDBManager] = get_db_manager()
except Exception:
    _db = None

# ── Schemas ────────────────────────────────────────────────────────────────

class PhaseRequest(BaseModel):
    target: str
    phase: str                      # recon_passive | recon_active | enumeration | web_application |
                                    # vulnerability_analysis | post_exploitation | encryption_analysis |
                                    # cleanup_and_evidence
    domain: str = ""
    ports: str = "1-1000"
    open_ports: Optional[List[int]] = None
    port: int = 80
    protocol: str = "http"
    shell_type: str = "linux"
    cve_list: Optional[List[str]] = None

class EngagementRequest(BaseModel):
    target: str
    domain: str = ""
    open_ports: Optional[List[int]] = None

class PayloadExecutionLogRequest(BaseModel):
    target: str
    phase: str
    command: str
    operator_id: str
    pentest_id: Optional[int] = None
    technique_id: Optional[str] = None
    tool: Optional[str] = None
    risk_level: str = "MEDIUM"
    authorized: bool = False
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int] = None

class PlaybookExecuteRequest(BaseModel):
    playbook_key: str
    context: str = ""
    operator_id: str

class PlaybookStepRequest(BaseModel):
    notes: str = ""

class ThreatIntelIngestRequest(BaseModel):
    feed_source: str
    intel_type: str                  # IOC | TTP | actor | campaign | malware
    indicator: str
    indicator_type: Optional[str] = None
    confidence: int = 50
    severity: str = "MEDIUM"
    tlp: str = "WHITE"
    tags: List[str] = []
    context: Dict[str, Any] = {}

class NetworkHostRequest(BaseModel):
    ip_address: str
    pentest_id: Optional[int] = None
    hostname: Optional[str] = None
    mac_address: Optional[str] = None
    os_fingerprint: Optional[str] = None
    open_ports: List[Dict[str, Any]] = []
    tags: List[str] = []
    risk_score: float = 0.0
    notes: Optional[str] = None

class VulnEntryRequest(BaseModel):
    vuln_id: str                     # CVE-YYYY-NNNNN or JAKAL-custom-id
    title: str
    description: str
    severity: str                    # CRITICAL | HIGH | MEDIUM | LOW | INFO
    cvss_score: Optional[float] = None
    cvss_vector: Optional[str] = None
    cwe_id: Optional[str] = None
    mitre_technique: Optional[str] = None
    affected_products: List[str] = []
    patch_available: bool = False
    patch_reference: Optional[str] = None
    exploit_available: bool = False
    exploit_reference: Optional[str] = None
    source: str = "manual"

# ── Router ────────────────────────────────────────────────────────────────

router = APIRouter(tags=["payloads"])


def _require_payloads():
    if not PAYLOADS_OK:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Payload module unavailable: {_PAYLOAD_ERR if not PAYLOADS_OK else 'ok'}",
        )


# ══════════════════════════════════════════════════════════════════════════
# Payload Generator
# ══════════════════════════════════════════════════════════════════════════

@router.post("/payloads/generate")
def generate_phase_payloads(req: PhaseRequest):
    """
    Generate pre-populated, MITRE-tagged payloads for a specific PTES phase.
    Valid phases: recon_passive, recon_active, enumeration, web_application,
    vulnerability_analysis, post_exploitation_assessment, encryption_analysis,
    cleanup_and_evidence
    """
    _require_payloads()
    gen = PayloadGenerator()
    kwargs: Dict[str, Any] = {}

    if req.phase in ("recon_passive",):
        kwargs["domain"] = req.domain
    elif req.phase in ("recon_active",):
        kwargs["ports"] = req.ports
    elif req.phase in ("enumeration",):
        kwargs["ports"] = req.open_ports
    elif req.phase in ("web_application",):
        kwargs["port"] = req.port
        kwargs["protocol"] = req.protocol
    elif req.phase in ("vulnerability_analysis",):
        kwargs["cve_list"] = req.cve_list
    elif req.phase in ("post_exploitation_assessment",):
        kwargs["shell_type"] = req.shell_type

    try:
        payloads = gen.generate_phase(req.phase, req.target, **kwargs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "phase": req.phase,
        "target": req.target,
        "count": len(payloads),
        "payloads": payloads,
    }


@router.post("/payloads/engagement")
def generate_full_engagement(req: EngagementRequest):
    """
    Generate a full PTES engagement payload set across all phases for a target.
    Returns a dict keyed by phase name.
    """
    _require_payloads()
    gen = PayloadGenerator()
    try:
        engagement = gen.generate_full_engagement(
            target=req.target,
            domain=req.domain,
            open_ports=req.open_ports,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return engagement


@router.post("/payloads/log-execution", status_code=http_status.HTTP_201_CREATED)
def log_payload_execution(req: PayloadExecutionLogRequest):
    """Log a payload execution to the database for audit and reporting."""
    if not _db:
        raise HTTPException(status_code=503, detail="Database not available")
    execution_id = str(uuid.uuid4())
    try:
        row_id = _db.log_payload_execution({
            "execution_id":  execution_id,
            "pentest_id":    req.pentest_id,
            "target":        req.target,
            "phase":         req.phase,
            "command":       req.command,
            "technique_id":  req.technique_id,
            "tool":          req.tool,
            "risk_level":    req.risk_level,
            "operator_id":   req.operator_id,
            "authorized":    req.authorized,
            "stdout":        req.stdout,
            "stderr":        req.stderr,
            "exit_code":     req.exit_code,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"execution_id": execution_id, "row_id": row_id}


@router.get("/payloads/executions")
def list_executions(
    pentest_id: Optional[int] = Query(None),
    phase: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """List payload executions from the database."""
    if not _db:
        raise HTTPException(status_code=503, detail="Database not available")
    records = _db.list_payload_executions(pentest_id=pentest_id, phase=phase, limit=limit)
    return {"count": len(records), "executions": records}


# ══════════════════════════════════════════════════════════════════════════
# Playbook endpoints
# ══════════════════════════════════════════════════════════════════════════

@router.get("/playbooks/categories")
def playbook_categories():
    """List all available playbook categories."""
    _require_payloads()
    return {"categories": list_categories()}


@router.get("/playbooks")
def list_playbooks_endpoint(category: Optional[str] = Query(None)):
    """List all playbooks, optionally filtered by category."""
    _require_payloads()
    if category:
        books = get_playbooks_by_category(category)
    else:
        books = get_all_playbooks()
    return {"count": len(books), "playbooks": books}


@router.get("/playbooks/{key}")
def get_playbook_endpoint(key: str):
    """Get a single playbook by its key."""
    _require_payloads()
    book = get_playbook(key)
    if not book:
        raise HTTPException(status_code=404, detail=f"Playbook '{key}' not found")
    return book


@router.post("/playbooks/seed")
def seed_playbooks(operator_id: str = Query("system")):
    """
    Seed the playbook library into the database.
    Safe to call multiple times — skips already-existing keys.
    """
    _require_payloads()
    if not _db:
        raise HTTPException(status_code=503, detail="Database not available")
    result = seed_playbooks_to_db(_db)
    return result


@router.post("/playbooks/execute", status_code=http_status.HTTP_201_CREATED)
def start_playbook_execution(req: PlaybookExecuteRequest):
    """
    Start a playbook execution. Seeds the playbook to DB if not present.
    Returns execution_id.
    """
    _require_payloads()
    if not _db:
        raise HTTPException(status_code=503, detail="Database not available")

    # Ensure playbook is in DB
    pb_row = _db.get_playbook_by_key(req.playbook_key)
    if not pb_row:
        # Auto-seed this one playbook
        book = get_playbook(req.playbook_key)
        if not book:
            raise HTTPException(status_code=404, detail=f"Playbook '{req.playbook_key}' not found")
        pb_id = _db.insert_playbook(
            key=book["key"], name=book["name"],
            category=book["category"], steps=book["steps"],
        )
    else:
        pb_id = pb_row["id"]

    exec_id = _db.insert_playbook_execution(
        playbook_id=pb_id, context=req.context, operator_id=req.operator_id
    )
    return {
        "execution_id": exec_id,
        "playbook_key": req.playbook_key,
        "status": "in_progress",
    }


@router.post("/playbooks/execute/{exec_id}/step")
def complete_step(exec_id: int, step_index: int, req: PlaybookStepRequest):
    """Mark a playbook step as complete and log notes."""
    if not _db:
        raise HTTPException(status_code=503, detail="Database not available")
    result = _db.update_playbook_execution_step(exec_id, step_index, req.notes)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/playbooks/execute/{exec_id}/finish")
def finish_execution(exec_id: int):
    """Mark a playbook execution as finished/completed."""
    if not _db:
        raise HTTPException(status_code=503, detail="Database not available")
    return _db.finish_playbook_execution(exec_id)


# ══════════════════════════════════════════════════════════════════════════
# Threat Intelligence
# ══════════════════════════════════════════════════════════════════════════

@router.get("/threat-intel/stats")
def threat_intel_stats():
    """Return threat intelligence statistics."""
    if not _db:
        raise HTTPException(status_code=503, detail="Database not available")
    return _db.threat_intel_stats()


@router.get("/threat-intel")
def search_threat_intel(
    indicator: Optional[str] = Query(None),
    intel_type: Optional[str] = Query(None),
    active_only: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
):
    """Search threat intelligence indicators."""
    if not _db:
        raise HTTPException(status_code=503, detail="Database not available")
    results = _db.search_threat_intel(
        indicator=indicator, intel_type=intel_type,
        active_only=active_only, limit=limit,
    )
    return {"count": len(results), "indicators": results}


@router.post("/threat-intel/ingest", status_code=http_status.HTTP_201_CREATED)
def ingest_threat_intel(req: ThreatIntelIngestRequest):
    """Ingest a new threat intelligence indicator."""
    if not _db:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        row_id = _db.ingest_threat_intel({
            "feed_source":   req.feed_source,
            "intel_type":    req.intel_type,
            "indicator":     req.indicator,
            "indicator_type":req.indicator_type,
            "confidence":    req.confidence,
            "severity":      req.severity,
            "tlp":           req.tlp,
            "tags":          req.tags,
            "context":       req.context,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"id": row_id, "indicator": req.indicator, "status": "ingested"}


# ══════════════════════════════════════════════════════════════════════════
# Network Map
# ══════════════════════════════════════════════════════════════════════════

@router.get("/network-map")
def get_network_map(pentest_id: Optional[int] = Query(None)):
    """Retrieve the network asset map, optionally filtered by pentest_id."""
    if not _db:
        raise HTTPException(status_code=503, detail="Database not available")
    hosts = _db.get_network_map(pentest_id=pentest_id)
    return {"count": len(hosts), "hosts": hosts}


@router.post("/network-map/host", status_code=http_status.HTTP_201_CREATED)
def upsert_host(req: NetworkHostRequest):
    """Add or update a discovered host in the network map."""
    if not _db:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        row_id = _db.upsert_network_host({
            "ip_address":    req.ip_address,
            "pentest_id":    req.pentest_id,
            "hostname":      req.hostname,
            "mac_address":   req.mac_address,
            "os_fingerprint":req.os_fingerprint,
            "open_ports":    req.open_ports,
            "tags":          req.tags,
            "risk_score":    req.risk_score,
            "notes":         req.notes,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"id": row_id, "ip_address": req.ip_address, "status": "upserted"}


# ══════════════════════════════════════════════════════════════════════════
# Vulnerability Database
# ══════════════════════════════════════════════════════════════════════════

@router.get("/vuln-db")
def search_vulns(
    severity: Optional[str] = Query(None),
    mitre_technique: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """Search the local vulnerability database."""
    if not _db:
        raise HTTPException(status_code=503, detail="Database not available")
    results = _db.search_vulns(
        severity=severity, mitre_technique=mitre_technique, limit=limit
    )
    return {"count": len(results), "vulns": results}


@router.post("/vuln-db/entry", status_code=http_status.HTTP_201_CREATED)
def upsert_vuln(req: VulnEntryRequest):
    """Add or update a vulnerability entry in the local vuln database."""
    if not _db:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        row_id = _db.upsert_vuln({
            "vuln_id":           req.vuln_id,
            "title":             req.title,
            "description":       req.description,
            "severity":          req.severity,
            "cvss_score":        req.cvss_score,
            "cvss_vector":       req.cvss_vector,
            "cwe_id":            req.cwe_id,
            "mitre_technique":   req.mitre_technique,
            "affected_products": req.affected_products,
            "patch_available":   req.patch_available,
            "patch_reference":   req.patch_reference,
            "exploit_available": req.exploit_available,
            "exploit_reference": req.exploit_reference,
            "source":            req.source,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"id": row_id, "vuln_id": req.vuln_id, "status": "upserted"}
