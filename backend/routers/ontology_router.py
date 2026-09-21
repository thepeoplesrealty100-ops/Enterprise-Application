"""
backend/routers/ontology_router.py
JAKAL Ontology Engine API (v3.0) — Palantir Foundry-style Object/Link
digital twin. Backend: services/ontology_engine.py, database.py's
ontological_object_nodes + lattice_edge_telemetry tables.

Endpoints:
  POST  /nodes                       — create an object node
  GET   /nodes/{node_id}              — fetch one node
  PATCH /nodes/{node_id}/confidence   — update a node's confidence score
  POST  /links                        — link two nodes (a directed edge)
  GET   /subgraph/{node_id}           — breadth-first subgraph from a root node
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import DuckDBManager, get_db_manager
from services.ontology_engine import OntologyEngine

router = APIRouter(tags=["ontology-v3"])


def get_db() -> DuckDBManager:
    return get_db_manager()


def get_engine(db: DuckDBManager = Depends(get_db)) -> OntologyEngine:
    return OntologyEngine(db)


class CreateNodeRequest(BaseModel):
    object_type: str = Field(..., max_length=128)
    attributes: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    operator_id: str = "system"


class LinkNodesRequest(BaseModel):
    source_id: str
    target_id: str
    event_type: str = Field(..., max_length=128)
    vector_payload: Dict[str, Any] = Field(default_factory=dict)
    operator_id: str = "system"


class ConfidenceUpdate(BaseModel):
    confidence: float = Field(..., ge=0.0, le=1.0)


@router.post("/nodes")
def create_node(body: CreateNodeRequest, engine: OntologyEngine = Depends(get_engine)):
    node_id = engine.create_node(
        object_type=body.object_type,
        attributes=body.attributes,
        confidence=body.confidence,
        operator_id=body.operator_id,
    )
    return {"node_id": node_id, "status": "created"}


@router.get("/nodes/{node_id}")
def get_node(node_id: str, engine: OntologyEngine = Depends(get_engine)):
    node = engine.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="node not found")
    return node


@router.post("/links")
def link_nodes(body: LinkNodesRequest, engine: OntologyEngine = Depends(get_engine)):
    try:
        telemetry_id = engine.link_nodes(
            source_id=body.source_id,
            target_id=body.target_id,
            event_type=body.event_type,
            vector_payload=body.vector_payload,
            operator_id=body.operator_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"telemetry_id": telemetry_id, "status": "linked"}


@router.get("/subgraph/{node_id}")
def subgraph(node_id: str, depth: int = 2, engine: OntologyEngine = Depends(get_engine)):
    if depth < 0 or depth > 10:
        raise HTTPException(status_code=422, detail="depth must be between 0 and 10")
    return engine.query_subgraph(node_id, max_depth=depth)


@router.patch("/nodes/{node_id}/confidence")
def update_confidence(node_id: str, body: ConfidenceUpdate, engine: OntologyEngine = Depends(get_engine)):
    ok = engine.update_confidence(node_id, body.confidence)
    if not ok:
        raise HTTPException(status_code=404, detail="node not found")
    return {"node_id": node_id, "confidence": body.confidence, "status": "updated"}
