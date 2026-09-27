"""
backend/routers/digital_twin.py — JAKAL Digital Twin (v4.0, rebuilt)

Real asset digital twin backed by the Ontology Engine (Object/Link graph:
services/ontology_engine.py, database.py's ontological_object_nodes +
lattice_edge_telemetry). Materializes every known asset -- network_map scan
results and registered fleet agents (routers/fleet_agent.py) -- into "Asset"
nodes, so the graph already populated by staged payloads and containment
actions (ExploitAgent.stage_payloads(), routers/response.py's
_materialize_containment_ontology_link()) gains a real inventory layer
instead of standing alone.

This replaces the original v4.0 router, which returned entirely hardcoded
fixture data for a fictitious "Water Treatment Facility Alpha" on every
endpoint (no persistence, no real inputs). Nothing here reuses that shape.
Not used by any frontend page yet (confirmed: no "digital-twin" reference
in index.html or js/); frontend wiring is a follow-up.

Endpoints:
  POST /sync                       — pull network_map + fleet agents into the graph
  GET  /assets                      — list synced assets with derived status
  GET  /assets/{node_id}             — one asset: attributes + linked graph objects
  POST /assets/{node_id}/annotate    — attach an operator note (graph-linked)
  GET  /summary                      — fleet-wide rollup

Does not duplicate routers/ontology_router.py's generic node/link/subgraph
CRUD (mounted at /api/v3/ontology) -- this router is the Digital-Twin-
specific view over the same underlying graph.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import DuckDBManager, get_db_manager
from dependencies import get_authenticated_user, require_permission
from services.ontology_engine import OntologyEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/digital-twin", tags=["Digital Twin"])

AGENT_OFFLINE_SECONDS = 120  # matches routers/fleet_agent.py's own threshold


def _db() -> DuckDBManager:
    return get_db_manager()


def _engine(db: DuckDBManager = Depends(_db)) -> OntologyEngine:
    return OntologyEngine(db)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_list(raw: Any) -> List[Any]:
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _agent_status(last_seen: Any) -> str:
    if not last_seen:
        return "offline"
    if isinstance(last_seen, str):
        try:
            last_seen = datetime.fromisoformat(last_seen)
        except ValueError:
            return "offline"
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return "online" if (datetime.now(timezone.utc) - last_seen) < timedelta(seconds=AGENT_OFFLINE_SECONDS) else "offline"


def _asset_health(attrs: Dict[str, Any], linked_action_count: int) -> Dict[str, Any]:
    """Health/risk derived only from real signals already in the
    database -- network_map's own risk_score, fleet agent liveness, and
    how many exploit/containment actions the ontology graph already has
    linked against this asset. Not a simulated ML output."""
    risk_score = float(attrs.get("risk_score") or 0.0)
    source = attrs.get("source")
    online = (source == "fleet_agent" and attrs.get("agent_status") == "online") or source == "network_map"
    score = 1.0 - min(risk_score / 10.0, 1.0) - min(0.1 * linked_action_count, 0.5)
    score = max(0.0, min(1.0, score))
    if not online:
        score = min(score, 0.5)
    status = "healthy" if score >= 0.7 else ("degraded" if score >= 0.4 else "at_risk")
    return {"health_score": round(score, 2), "health_status": status}


def _linked_action_count(db: DuckDBManager, node_id: str) -> int:
    row = db.conn.execute(
        "SELECT COUNT(*) FROM lattice_edge_telemetry WHERE source_node = ? OR target_node = ?",
        (node_id, node_id),
    ).fetchone()
    return int(row[0]) if row else 0


class SyncResult(BaseModel):
    synced_from_network_map: int
    synced_from_fleet_agents: int
    assets_total: int
    timestamp: str


class AnnotateRequest(BaseModel):
    note: str = Field(..., min_length=1, max_length=2000)
    tag: Optional[str] = Field(None, max_length=64)


@router.post("/sync", response_model=SyncResult, dependencies=[require_permission("response:manage")])
async def sync(engine: OntologyEngine = Depends(_engine), db: DuckDBManager = Depends(_db),
                user: dict = Depends(get_authenticated_user)):
    """
    Materialize/refresh an "Asset" node for every network_map scan result
    and every registered fleet agent. Idempotent: re-running updates the
    existing node for a given IP (via
    OntologyEngine.find_or_create_target_node()) rather than duplicating
    it, then OntologyEngine.update_attributes() refreshes its fields.
    """
    operator_id = user.get("username") or user.get("user_id") or "system"

    net_synced = 0
    for row in db.get_network_map():
        target = row.get("ip_address")
        if not target:
            continue
        node_id = engine.find_or_create_target_node(target, operator_id=operator_id)
        engine.update_attributes(node_id, {
            "target": target,
            "ip_address": target,
            "hostname": row.get("hostname"),
            "mac_address": row.get("mac_address"),
            "os_fingerprint": row.get("os_fingerprint"),
            "open_ports": _json_list(row.get("open_ports")),
            "tags": _json_list(row.get("tags")),
            "risk_score": float(row.get("risk_score") or 0.0),
            "notes": row.get("notes"),
            "source": "network_map",
            "network_map_id": row.get("id"),
            "last_seen": str(row.get("last_seen") or ""),
        })
        net_synced += 1

    fleet_synced = 0
    try:
        from routers.fleet_agent import _ensure_schema, _rows
        _ensure_schema(db)
        agents = _rows(
            db,
            "SELECT agent_id,hostname,os,os_version,ip,status,first_seen,last_seen,tags FROM agent_endpoints",
        )
    except Exception as e:
        logger.warning("Digital twin sync: fleet agent read failed: %s", e)
        agents = []
    for a in agents:
        target = a.get("ip") or a.get("agent_id")
        if not target:
            continue
        node_id = engine.find_or_create_target_node(target, operator_id=operator_id)
        engine.update_attributes(node_id, {
            "target": target,
            "agent_id": a.get("agent_id"),
            "hostname": a.get("hostname"),
            "os": a.get("os"),
            "os_version": a.get("os_version"),
            "ip_address": a.get("ip"),
            "agent_status": _agent_status(a.get("last_seen")),
            "tags": _json_list(a.get("tags")),
            "source": "fleet_agent",
            "last_seen": str(a.get("last_seen") or ""),
        })
        fleet_synced += 1

    total = len(engine.list_nodes("Asset"))
    return SyncResult(
        synced_from_network_map=net_synced,
        synced_from_fleet_agents=fleet_synced,
        assets_total=total,
        timestamp=_now_iso(),
    )


@router.get("/assets")
async def list_assets(db: DuckDBManager = Depends(_db), engine: OntologyEngine = Depends(_engine),
                       user: dict = Depends(get_authenticated_user)):
    nodes = engine.list_nodes("Asset")
    out = []
    for n in nodes:
        attrs = n.get("attributes", {})
        linked = _linked_action_count(db, n["node_id"])
        out.append({
            "node_id": n["node_id"],
            "target": attrs.get("target"),
            "hostname": attrs.get("hostname"),
            "ip_address": attrs.get("ip_address"),
            "source": attrs.get("source"),
            "agent_status": attrs.get("agent_status"),
            "risk_score": attrs.get("risk_score"),
            "tags": attrs.get("tags") or [],
            "linked_objects": linked,
            "confidence": n.get("confidence_score"),
            "updated_at": str(n.get("updated_at") or n.get("created_at") or ""),
            **_asset_health(attrs, linked),
        })
    return {"assets": out, "count": len(out)}


@router.get("/assets/{node_id}")
async def asset_detail(node_id: str, depth: int = 2, db: DuckDBManager = Depends(_db),
                        engine: OntologyEngine = Depends(_engine),
                        user: dict = Depends(get_authenticated_user)):
    node = engine.get_node(node_id)
    if not node or node.get("object_type") != "Asset":
        raise HTTPException(status_code=404, detail="asset not found")
    try:
        attrs = json.loads(node.get("attributes_json") or "{}")
    except Exception:
        attrs = {}

    subgraph = engine.query_subgraph(node_id, max_depth=max(0, min(depth, 5)))
    linked_objects = []
    for nid, n in subgraph["nodes"].items():
        if nid == node_id:
            continue
        try:
            n_attrs = json.loads(n.get("attributes_json") or "{}")
        except Exception:
            n_attrs = {}
        linked_objects.append({"node_id": nid, "object_type": n.get("object_type"), "attributes": n_attrs})

    return {
        "node_id": node_id,
        "attributes": attrs,
        "confidence": node.get("confidence_score"),
        "created_at": str(node.get("created_at") or ""),
        "updated_at": str(node.get("updated_at") or ""),
        "linked_objects": linked_objects,
        "edges": subgraph["edges"],
        **_asset_health(attrs, len(subgraph["edges"])),
    }


@router.post("/assets/{node_id}/annotate")
async def annotate_asset(node_id: str, body: AnnotateRequest, engine: OntologyEngine = Depends(_engine),
                          user: dict = Depends(get_authenticated_user)):
    node = engine.get_node(node_id)
    if not node or node.get("object_type") != "Asset":
        raise HTTPException(status_code=404, detail="asset not found")
    operator_id = user.get("username") or user.get("user_id") or "system"
    annotation_id = engine.create_node(
        "Annotation",
        {"note": body.note, "tag": body.tag, "asset_node_id": node_id, "created_at": _now_iso()},
        operator_id=operator_id,
    )
    engine.link_nodes(annotation_id, node_id, "ANNOTATES", operator_id=operator_id)
    return {"annotation_id": annotation_id, "asset_node_id": node_id, "status": "annotated"}


@router.get("/summary")
async def summary(db: DuckDBManager = Depends(_db), engine: OntologyEngine = Depends(_engine),
                   user: dict = Depends(get_authenticated_user)):
    nodes = engine.list_nodes("Asset")
    online = sum(1 for n in nodes if n.get("attributes", {}).get("agent_status") == "online")
    scanned_only = sum(1 for n in nodes if n.get("attributes", {}).get("source") == "network_map")
    scores = []
    at_risk = 0
    for n in nodes:
        attrs = n.get("attributes", {})
        linked = _linked_action_count(db, n["node_id"])
        h = _asset_health(attrs, linked)
        scores.append(h["health_score"])
        if h["health_status"] == "at_risk":
            at_risk += 1
    avg_health = round(sum(scores) / len(scores), 2) if scores else None
    return {
        "assets_total": len(nodes),
        "fleet_agents_online": online,
        "network_scan_only": scanned_only,
        "average_health_score": avg_health,
        "assets_at_risk": at_risk,
        "timestamp": _now_iso(),
    }
