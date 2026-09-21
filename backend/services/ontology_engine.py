"""
backend/services/ontology_engine.py

JAKAL Ontology Engine v3.0 — a Palantir Foundry-style Object/Link digital
twin backed by database.py's ontological_object_nodes and
lattice_edge_telemetry tables. Thin service wrapper: all persistence and
integrity checks live in DuckDBManager (see its v3.0 helpers' docstrings
for why source/target node existence is checked at the application layer
rather than via SQL FOREIGN KEY).

Object Types are free-text (e.g. "Asset", "Finding", "ScanResult",
"RemediationAction") rather than a fixed enum, matching how the rest of
this codebase's scan/response modules already produce heterogeneous
severity/category strings — a schema migration isn't needed to introduce
a new kind of node. Link Types (event_type) are similarly free-text (e.g.
"AFFECTS", "ISOLATED", "QUARANTINED", "DISCOVERED_BY").
"""

import logging
from typing import Any, Dict, Optional

from database import DuckDBManager

logger = logging.getLogger(__name__)


class OntologyEngine:
    def __init__(self, db: DuckDBManager):
        self.db = db

    def create_node(self, object_type: str, attributes: Dict[str, Any],
                     confidence: float = 1.0, operator_id: str = "system",
                     pqc_entry_id: Optional[str] = None) -> str:
        return self.db.create_ontological_node(
            object_type=object_type,
            attributes=attributes,
            confidence=confidence,
            operator_id=operator_id,
            pqc_entry_id=pqc_entry_id,
        )

    def link_nodes(self, source_id: str, target_id: str, event_type: str,
                   vector_payload: Optional[Dict[str, Any]] = None,
                   operator_id: str = "system",
                   pqc_signature: Optional[str] = None) -> str:
        return self.db.link_ontological_nodes(
            source_id=source_id,
            target_id=target_id,
            event_type=event_type,
            vector_payload=vector_payload or {},
            operator_id=operator_id,
            pqc_signature=pqc_signature,
        )

    def update_confidence(self, node_id: str, new_score: float) -> bool:
        return self.db.update_node_confidence(node_id, new_score)

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        return self.db.get_ontological_node(node_id)

    def query_subgraph(self, root_node_id: str, max_depth: int = 2) -> Dict[str, Any]:
        return self.db.query_subgraph(root_node_id, max_depth)

    # ------------------------------------------------------------------
    # v3.0 Phase 5 -- controlled expansion: give staged payloads and
    # remediation actions a real position in the graph, so the Approval
    # Gate can offer a basic attack-path/related-object view instead of
    # an empty ontology. Shared by ExploitAgent.stage_payloads() and
    # routers/response.py's containment actions so both feed the same
    # graph rather than each inventing their own node shape.
    # ------------------------------------------------------------------

    def find_or_create_target_node(self, target: str, operator_id: str = "system") -> str:
        """Reuses the existing "Asset" node for `target` if one was
        already materialized (by an earlier staging against the same
        target), rather than creating a duplicate node per call."""
        existing = self.db.find_ontological_node_by_attribute("Asset", "target", target)
        if existing:
            return existing["node_id"]
        return self.create_node("Asset", {"target": target}, operator_id=operator_id)

    def materialize_action_link(
        self, target: str, action_object_type: str, action_attributes: Dict[str, Any],
        link_event_type: str = "TARGETS", operator_id: str = "system",
    ) -> Optional[str]:
        """Create a node for one staged payload/remediation action and
        link it to its target's Asset node. Best-effort: returns the new
        action node's id on success, None on any failure (a materialization
        failure must never block staging/approval -- this is enrichment,
        not gating). Returns None immediately if target is falsy."""
        if not target:
            return None
        try:
            asset_id = self.find_or_create_target_node(target, operator_id=operator_id)
            action_node_id = self.create_node(action_object_type, action_attributes, operator_id=operator_id)
            self.link_nodes(action_node_id, asset_id, link_event_type, operator_id=operator_id)
            return action_node_id
        except Exception as e:
            logger.warning("Ontology materialization failed for target '%s': %s", target, e)
            return None
