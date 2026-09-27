"""
backend/routers/msp_multi_tenant.py — JAKAL MSP Multi-Tenant Gateway (v3.1, rebuilt)

Real tenant management backed by database.py's organizations/tenant_members/
tenant_sso_config/tenant_cross_ops tables (see initialize_schema()'s v3.1
section). Replaces the original router, which returned entirely hardcoded
data from all 12 endpoints regardless of input -- a canned two-tenant list
("Acme Corp"/"TechStart Inc"), a fabricated "healthy" SSO test on every call,
a fake JWT-shaped string on every "switch", invented billing dollar figures,
and a "passed" isolation-test report that never queried anything.

What this platform honestly has, and does not have, for multi-tenancy:
  - It HAS real tenant records, real tenant membership, and real device
    counts (network_map/agent_endpoints rows tagged "tenant:<id>" -- the
    same tag-based scoping routers/fleet_management.py's device groups
    already use).
  - It does NOT have a live SAML/OIDC identity provider connection, a
    billing/metering integration, or per-request tenant-scoped query
    filtering across the other 40+ routers (that's a much larger,
    cross-cutting change -- out of scope here). SSO config is persisted
    for real but `enabled` stays false until an operator supplies real IdP
    credentials; the "test connection" endpoint makes a real HTTP request
    to the stored discovery/metadata URL rather than always reporting
    "healthy". Billing reports `not_configured` rather than inventing
    dollar amounts, matching routers/fleet_management.py's established
    convention for capabilities this platform doesn't actually have.

Endpoints:
  GET    /tenants                                  — real tenant list
  POST   /tenants                                   — create a tenant  (msp:manage)
  GET    /tenants/{tenant_id}                       — one tenant + real device/user counts
  PATCH  /tenants/{tenant_id}                       — update tenant fields (msp:manage)
  POST   /tenants/{tenant_id}/members                — add a member (msp:manage)
  DELETE /tenants/{tenant_id}/members/{user_id}       — remove a member (msp:manage)
  GET    /tenants/{tenant_id}/members                — list members
  POST   /tenants/switch                             — set caller's active tenant
  GET    /tenants/switch/current                     — caller's tenant memberships
  GET    /tenants/{tenant_id}/sso/mechanisms          — real stored SSO config (empty if none)
  POST   /tenants/{tenant_id}/sso/configure           — persist SSO config (msp:manage)
  POST   /tenants/{tenant_id}/sso/{mechanism_type}/test — real reachability probe (msp:manage)
  POST   /operations/broadcast                        — create real cross-tenant op (msp:manage)
  GET    /operations/{operation_id}/status            — real op row, 404 if unknown
  POST   /operations/{operation_id}/rollback           — real status transition (msp:manage)
  GET    /audit/cross-tenant                          — real aggregation over audit_log
  GET    /billing/forecast                            — real device/limit counts; cost = not_configured
  POST   /security/data-isolation-test                — real tag/membership overlap check (msp:manage)
  GET    /compliance/tenant-specific                   — not_configured (no tenant-scoped compliance wiring yet)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import DuckDBManager, get_db_manager
from dependencies import get_authenticated_user, require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/msp", tags=["MSP Multi-Tenant"])


def _db() -> DuckDBManager:
    return get_db_manager()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _actor(user: dict) -> str:
    return user.get("username") or user.get("user_id") or "system"


def _require_tenant(db: DuckDBManager, tenant_id: str) -> Dict[str, Any]:
    org = db.get_organization(tenant_id)
    if not org:
        raise HTTPException(status_code=404, detail="tenant not found")
    return org


def _tenant_view(db: DuckDBManager, org: Dict[str, Any]) -> Dict[str, Any]:
    device_count = db.count_devices_for_tenant(org["tenant_id"])
    user_count = len(db.list_tenant_members(org["tenant_id"]))
    return {
        "tenant_id": org["tenant_id"],
        "tenant_name": org["tenant_name"],
        "tenant_type": org["tenant_type"],
        "status": org["status"],
        "subscription_tier": org["subscription_tier"],
        "device_limit": org["device_limit"],
        "device_count": device_count,
        "device_utilization_pct": round(100 * device_count / org["device_limit"], 1) if org["device_limit"] else None,
        "user_limit": org["user_limit"],
        "user_count": user_count,
        "parent_msp_id": org.get("parent_msp_id"),
        "created_at": str(org.get("created_at") or ""),
        "updated_at": str(org.get("updated_at") or ""),
    }


class CreateTenantRequest(BaseModel):
    tenant_id: str = Field(..., min_length=2, max_length=64)
    tenant_name: str = Field(..., min_length=1, max_length=200)
    tenant_type: str = Field("client", pattern="^(msp|client|partner)$")
    subscription_tier: str = Field("starter", pattern="^(starter|professional|enterprise)$")
    device_limit: int = Field(0, ge=0)
    user_limit: int = Field(0, ge=0)
    parent_msp_id: Optional[str] = None


class UpdateTenantRequest(BaseModel):
    tenant_name: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|suspended|archived)$")
    subscription_tier: Optional[str] = Field(None, pattern="^(starter|professional|enterprise)$")
    device_limit: Optional[int] = Field(None, ge=0)
    user_limit: Optional[int] = Field(None, ge=0)


class MemberRequest(BaseModel):
    user_id: str
    role: str = Field("member", pattern="^(member|admin)$")


class SwitchRequest(BaseModel):
    tenant_id: str


class SSOConfigureRequest(BaseModel):
    mechanism_type: str = Field(..., pattern="^(saml|oidc|oauth2)$")
    provider: str = Field(..., min_length=1, max_length=64)
    config: Dict[str, Any] = Field(default_factory=dict)


class BroadcastRequest(BaseModel):
    operation_type: str = Field(..., min_length=1, max_length=64)
    source_tenant: str
    target_tenants: List[str] = Field(..., min_length=1)
    payload: Dict[str, Any] = Field(default_factory=dict)


class IsolationTestRequest(BaseModel):
    source_tenant: str
    target_tenant: str


# ============================================================================
# TENANT MANAGEMENT
# ============================================================================

@router.get("/tenants")
async def list_tenants(db: DuckDBManager = Depends(_db), user: dict = Depends(get_authenticated_user)):
    orgs = db.list_organizations()
    return {"tenants": [_tenant_view(db, o) for o in orgs], "count": len(orgs)}


@router.post("/tenants", dependencies=[require_permission("msp:manage")])
async def create_tenant(body: CreateTenantRequest, db: DuckDBManager = Depends(_db),
                         user: dict = Depends(get_authenticated_user)):
    if db.get_organization(body.tenant_id):
        raise HTTPException(status_code=409, detail=f"tenant '{body.tenant_id}' already exists")
    if body.parent_msp_id and not db.get_organization(body.parent_msp_id):
        raise HTTPException(status_code=400, detail=f"parent_msp_id '{body.parent_msp_id}' does not exist")
    org = db.create_organization(
        tenant_id=body.tenant_id, tenant_name=body.tenant_name, tenant_type=body.tenant_type,
        subscription_tier=body.subscription_tier, device_limit=body.device_limit,
        user_limit=body.user_limit, parent_msp_id=body.parent_msp_id,
    )
    db.insert_audit_entry({
        "actor_user_id": user.get("user_id"), "actor_label": _actor(user), "action": "msp:tenant_create",
        "resource_type": "tenant", "resource_id": body.tenant_id, "outcome": "success",
        "detail": {"tenant_type": body.tenant_type},
    })
    return _tenant_view(db, org)


@router.get("/tenants/{tenant_id}")
async def get_tenant_details(tenant_id: str, db: DuckDBManager = Depends(_db),
                              user: dict = Depends(get_authenticated_user)):
    org = _require_tenant(db, tenant_id)
    return _tenant_view(db, org)


@router.patch("/tenants/{tenant_id}", dependencies=[require_permission("msp:manage")])
async def update_tenant(tenant_id: str, body: UpdateTenantRequest, db: DuckDBManager = Depends(_db),
                         user: dict = Depends(get_authenticated_user)):
    _require_tenant(db, tenant_id)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    db.update_organization(tenant_id, fields)
    db.insert_audit_entry({
        "actor_user_id": user.get("user_id"), "actor_label": _actor(user), "action": "msp:tenant_update",
        "resource_type": "tenant", "resource_id": tenant_id, "outcome": "success", "detail": fields,
    })
    return _tenant_view(db, db.get_organization(tenant_id))


@router.get("/tenants/{tenant_id}/members")
async def list_members(tenant_id: str, db: DuckDBManager = Depends(_db),
                        user: dict = Depends(get_authenticated_user)):
    _require_tenant(db, tenant_id)
    return {"members": db.list_tenant_members(tenant_id)}


@router.post("/tenants/{tenant_id}/members", dependencies=[require_permission("msp:manage")])
async def add_member(tenant_id: str, body: MemberRequest, db: DuckDBManager = Depends(_db),
                      user: dict = Depends(get_authenticated_user)):
    _require_tenant(db, tenant_id)
    if not db.get_user_by_id(body.user_id):
        raise HTTPException(status_code=404, detail=f"user '{body.user_id}' does not exist")
    db.add_tenant_member(tenant_id, body.user_id, body.role)
    db.insert_audit_entry({
        "actor_user_id": user.get("user_id"), "actor_label": _actor(user), "action": "msp:member_add",
        "resource_type": "tenant", "resource_id": tenant_id, "outcome": "success",
        "detail": {"user_id": body.user_id, "role": body.role},
    })
    return {"status": "added", "tenant_id": tenant_id, "user_id": body.user_id, "role": body.role}


@router.delete("/tenants/{tenant_id}/members/{user_id}", dependencies=[require_permission("msp:manage")])
async def remove_member(tenant_id: str, user_id: str, db: DuckDBManager = Depends(_db),
                         user: dict = Depends(get_authenticated_user)):
    _require_tenant(db, tenant_id)
    if not db.remove_tenant_member(tenant_id, user_id):
        raise HTTPException(status_code=404, detail="membership not found")
    db.insert_audit_entry({
        "actor_user_id": user.get("user_id"), "actor_label": _actor(user), "action": "msp:member_remove",
        "resource_type": "tenant", "resource_id": tenant_id, "outcome": "success", "detail": {"user_id": user_id},
    })
    return {"status": "removed", "tenant_id": tenant_id, "user_id": user_id}


@router.post("/tenants/switch")
async def switch_tenant(body: SwitchRequest, db: DuckDBManager = Depends(_db),
                         user: dict = Depends(get_authenticated_user)):
    """Sets the caller's active tenant. Requires the caller already be a
    tenant member, or hold msp:manage (root_admin/MSP staff), unlike the
    old endpoint which switched to any tenant_id string unconditionally
    and returned a fabricated "jwt.token.<id>" that was never a real
    token."""
    org = _require_tenant(db, body.tenant_id)
    user_perms = set(db.get_user_permissions(user["user_id"]))
    is_member = body.tenant_id in db.list_tenants_for_user(user["user_id"])
    if not is_member and "system:*" not in user_perms and "msp:manage" not in user_perms:
        raise HTTPException(status_code=403, detail="not a member of this tenant")
    db.set_user_active_tenant(user.get("user_id"), body.tenant_id)
    return {"status": "switched", "current_tenant": body.tenant_id, "tenant": _tenant_view(db, org),
            "timestamp": _now_iso()}


@router.get("/tenants/switch/current")
async def current_tenants(db: DuckDBManager = Depends(_db), user: dict = Depends(get_authenticated_user)):
    tenant_ids = db.list_tenants_for_user(user.get("user_id"))
    return {"tenant_ids": tenant_ids}


# ============================================================================
# SSO & FEDERATION
# ============================================================================

@router.get("/tenants/{tenant_id}/sso/mechanisms")
async def list_sso_mechanisms(tenant_id: str, db: DuckDBManager = Depends(_db),
                               user: dict = Depends(get_authenticated_user)):
    _require_tenant(db, tenant_id)
    configs = db.list_tenant_sso_configs(tenant_id)
    return {"tenant_id": tenant_id, "mechanisms": [
        {"mechanism_type": c["mechanism_type"], "provider": c["provider"], "enabled": bool(c["enabled"]),
         "configured": True, "updated_at": str(c.get("updated_at") or "")}
        for c in configs
    ]}


@router.post("/tenants/{tenant_id}/sso/configure", dependencies=[require_permission("msp:manage")])
async def configure_sso(tenant_id: str, body: SSOConfigureRequest, db: DuckDBManager = Depends(_db),
                         user: dict = Depends(get_authenticated_user)):
    _require_tenant(db, tenant_id)
    db.save_tenant_sso_config(tenant_id, body.mechanism_type, body.provider, body.config, enabled=False)
    db.insert_audit_entry({
        "actor_user_id": user.get("user_id"), "actor_label": _actor(user), "action": "msp:sso_configure",
        "resource_type": "tenant", "resource_id": tenant_id, "outcome": "success",
        "detail": {"mechanism_type": body.mechanism_type, "provider": body.provider},
    })
    return {
        "status": "saved", "sso_type": body.mechanism_type, "provider": body.provider, "enabled": False,
        "note": (
            f"Configuration stored for tenant '{tenant_id}'. Federation stays disabled until an operator "
            f"verifies real {body.provider} credentials via POST .../sso/{body.mechanism_type}/test and "
            "flips it on with PATCH — this platform does not fabricate a live IdP handshake."
        ),
    }


@router.post("/tenants/{tenant_id}/sso/{mechanism_type}/test", dependencies=[require_permission("msp:manage")])
async def test_sso_connection(tenant_id: str, mechanism_type: str, db: DuckDBManager = Depends(_db),
                               user: dict = Depends(get_authenticated_user)):
    """Real reachability probe against the stored discovery/metadata URL --
    not a hardcoded "healthy" response. Reports not_configured if no config
    was ever saved, unreachable if the HTTP probe fails."""
    _require_tenant(db, tenant_id)
    cfg = db.get_tenant_sso_config(tenant_id, mechanism_type)
    if not cfg:
        return {"connection_status": "not_configured", "mechanism_type": mechanism_type}
    endpoint = (cfg.get("config") or {}).get("discovery_endpoint") or (cfg.get("config") or {}).get("metadata_url")
    if not endpoint:
        return {
            "connection_status": "not_configured", "mechanism_type": mechanism_type, "provider": cfg["provider"],
            "note": "No discovery_endpoint/metadata_url stored in config; nothing to probe.",
        }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(endpoint)
        status = "reachable" if resp.status_code < 400 else "unreachable"
        return {
            "connection_status": status, "mechanism_type": mechanism_type, "provider": cfg["provider"],
            "endpoint": endpoint, "http_status": resp.status_code, "checked_at": _now_iso(),
        }
    except httpx.HTTPError as e:
        return {
            "connection_status": "unreachable", "mechanism_type": mechanism_type, "provider": cfg["provider"],
            "endpoint": endpoint, "error": str(e), "checked_at": _now_iso(),
        }


# ============================================================================
# CROSS-TENANT OPERATIONS
# ============================================================================

@router.post("/operations/broadcast", dependencies=[require_permission("msp:manage")])
async def broadcast_operation(body: BroadcastRequest, db: DuckDBManager = Depends(_db),
                               user: dict = Depends(get_authenticated_user)):
    _require_tenant(db, body.source_tenant)
    for t in body.target_tenants:
        _require_tenant(db, t)
    op = db.create_cross_tenant_op(body.operation_type, body.source_tenant, body.target_tenants, body.payload)
    db.insert_audit_entry({
        "actor_user_id": user.get("user_id"), "actor_label": _actor(user), "action": "msp:broadcast",
        "resource_type": "tenant", "resource_id": body.source_tenant, "outcome": "success",
        "detail": {"operation_id": op["operation_id"], "targets": body.target_tenants},
    })
    return {
        "operation_id": op["operation_id"], "status": op["status"], "operation_type": op["operation_type"],
        "broadcast_to": len(body.target_tenants), "tracking_url": f"/api/msp/operations/{op['operation_id']}/status",
    }


@router.get("/operations/{operation_id}/status")
async def get_operation_status(operation_id: str, db: DuckDBManager = Depends(_db),
                                user: dict = Depends(get_authenticated_user)):
    op = db.get_cross_tenant_op(operation_id)
    if not op:
        raise HTTPException(status_code=404, detail="operation not found")
    return {
        "operation_id": op["operation_id"], "operation_type": op["operation_type"], "status": op["status"],
        "source_tenant": op["source_tenant"], "target_tenants": op["target_tenants"],
        "created_at": str(op.get("created_at") or ""), "updated_at": str(op.get("updated_at") or ""),
    }


@router.post("/operations/{operation_id}/rollback", dependencies=[require_permission("msp:manage")])
async def rollback_operation(operation_id: str, db: DuckDBManager = Depends(_db),
                              user: dict = Depends(get_authenticated_user)):
    op = db.get_cross_tenant_op(operation_id)
    if not op:
        raise HTTPException(status_code=404, detail="operation not found")
    if op["status"] not in ("queued", "in_progress", "completed"):
        raise HTTPException(status_code=409, detail=f"cannot roll back an operation in status '{op['status']}'")
    db.update_cross_tenant_op_status(operation_id, "rolled_back")
    db.insert_audit_entry({
        "actor_user_id": user.get("user_id"), "actor_label": _actor(user), "action": "msp:rollback",
        "resource_type": "tenant", "resource_id": op["source_tenant"], "outcome": "success",
        "detail": {"operation_id": operation_id},
    })
    return {"operation_id": operation_id, "rollback_status": "rolled_back"}


# ============================================================================
# TENANT AUDIT & BILLING
# ============================================================================

@router.get("/audit/cross-tenant")
async def get_cross_tenant_audit(start_date: str, end_date: str, db: DuckDBManager = Depends(_db),
                                  user: dict = Depends(get_authenticated_user)):
    try:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="start_date/end_date must be ISO-8601")
    summary = db.audit_log_summary(start, end, action_prefix="msp:")
    return {"audit_period": f"{start_date} to {end_date}", **summary}


@router.get("/billing/forecast")
async def billing_forecast(tenant_id: str, months_ahead: int = 3, db: DuckDBManager = Depends(_db),
                            user: dict = Depends(get_authenticated_user)):
    org = _require_tenant(db, tenant_id)
    view = _tenant_view(db, org)
    return {
        "tenant_id": tenant_id,
        "billing_status": "not_configured",
        "note": "No metering/billing provider is connected, so cost figures are not fabricated. "
                "Real usage below can be fed into a billing integration once one exists.",
        "subscription_tier": org["subscription_tier"],
        "device_count": view["device_count"],
        "device_limit": org["device_limit"],
        "user_count": view["user_count"],
        "user_limit": org["user_limit"],
        "months_ahead": months_ahead,
    }


# ============================================================================
# TENANT ISOLATION & SECURITY
# ============================================================================

@router.post("/security/data-isolation-test", dependencies=[require_permission("msp:manage")])
async def test_data_isolation(body: IsolationTestRequest, db: DuckDBManager = Depends(_db),
                               user: dict = Depends(get_authenticated_user)):
    """Real checks against the tag-based tenant scoping this router
    actually implements -- not a hardcoded "all passed" list. Checks:
    (1) no device is tagged for both tenants, (2) no user is a member of
    both tenants."""
    _require_tenant(db, body.source_tenant)
    _require_tenant(db, body.target_tenant)

    src_tag, tgt_tag = f"tenant:{body.source_tenant}", f"tenant:{body.target_tenant}"
    overlap_row = db.conn.execute(
        "SELECT COUNT(*) FROM network_map WHERE tags LIKE ? AND tags LIKE ?",
        (f"%{src_tag}%", f"%{tgt_tag}%"),
    ).fetchone()
    device_overlap = int(overlap_row[0]) if overlap_row else 0

    src_members = {m["user_id"] for m in db.list_tenant_members(body.source_tenant)}
    tgt_members = {m["user_id"] for m in db.list_tenant_members(body.target_tenant)}
    member_overlap = sorted(src_members & tgt_members)

    checks = [
        {"check": "Device tag exclusivity (network_map)", "status": "passed" if device_overlap == 0 else "FAILED",
         "overlapping_devices": device_overlap},
        {"check": "Tenant membership exclusivity", "status": "passed" if not member_overlap else "FAILED",
         "overlapping_users": member_overlap},
    ]
    overall = "passed" if all(c["status"] == "passed" for c in checks) else "failed"
    db.insert_audit_entry({
        "actor_user_id": user.get("user_id"), "actor_label": _actor(user), "action": "msp:isolation_test",
        "resource_type": "tenant", "resource_id": body.source_tenant, "outcome": "success",
        "detail": {"target_tenant": body.target_tenant, "result": overall},
    })
    return {"test_status": overall, "source_tenant": body.source_tenant, "target_tenant": body.target_tenant,
            "isolation_checks": checks}


@router.get("/compliance/tenant-specific")
async def get_tenant_compliance(tenant_id: str, framework: str, db: DuckDBManager = Depends(_db),
                                 user: dict = Depends(get_authenticated_user)):
    _require_tenant(db, tenant_id)
    return {
        "tenant_id": tenant_id, "framework": framework, "status": "not_configured",
        "note": "Tenant-scoped compliance mapping is not wired to the Compliance Intelligence module yet. "
                "See GET /api/compliance/... for a platform-wide assessment.",
    }
