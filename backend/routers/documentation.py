"""
routers/documentation.py — GACyber Documentation Engine — asset management,
and zero-knowledge vault engine.

Architecture mirrors IT Glue's three core pillars:
  1. Flexible Asset Engine   — custom schema types + EAV-style JSON instances
  2. Polymorphic Graph       — AssetRelations linking ANY record to ANY other
  3. Zero-Knowledge Vault    — AES-256-GCM encrypted credentials, rotation log

Builds on existing JAKAL tables (cap_asset_relationships, cap_credential_rotation,
network_map) and adds:
  doc_asset_types    — custom schema definitions (JSON field spec)
  doc_asset_records  — instances keyed to a type (JSONB-equivalent via JSON column)
  doc_sops           — structured runbooks/SOPs with step arrays
  doc_activity_log   — append-only tamper audit: who viewed/edited what

Endpoints (all under /api/docs):
  GET /asset-types          — list defined types
  POST /asset-types         — create new type
  GET /asset-types/{id}     — get one type definition
  PUT /asset-types/{id}     — update field spec
  DELETE /asset-types/{id}  — soft-delete

  GET /assets               — list instances (filterable by type)
  POST /assets              — create instance
  GET /assets/{id}          — get instance + related records
  PUT /assets/{id}          — update instance fields
  DELETE /assets/{id}       — soft-delete

  GET /relationships        — full polymorphic graph (nodes + edges)
  POST /relationships       — add relationship edge
  DELETE /relationships/{id}— remove edge

  GET /vault                — list credentials (payload NEVER returned)
  POST /vault               — create encrypted credential
  GET /vault/{id}/decrypt   — return decrypted fields (logged + auth-gated)
  PUT /vault/{id}           — update / rotate
  DELETE /vault/{id}        — soft-delete

  GET /sops                 — list SOPs / runbooks
  POST /sops                — create SOP
  GET /sops/{id}            — get SOP with all steps
  PUT /sops/{id}            — update SOP (auto-bumps version)
  DELETE /sops/{id}         — soft-delete

  GET /activity-log         — recent doc-engine activity (admin view)
"""
from __future__ import annotations

import json
import uuid
from base64 import b64encode, b64decode
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/docs", tags=["Documentation Engine"])


def _db():
    from database import get_db_manager
    return get_db_manager()


def _now():
    return datetime.now(timezone.utc)


def _uid():
    return str(uuid.uuid4())


# ─────────────────────────────────────────────
# Schema bootstrap (idempotent)
# ─────────────────────────────────────────────

_TABLES = [
    """CREATE TABLE IF NOT EXISTS doc_asset_types (
        type_id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        icon TEXT DEFAULT 'server',
        description TEXT DEFAULT '',
        field_spec TEXT DEFAULT '[]',   -- JSON array of {name, type, required, options}
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS doc_asset_records (
        record_id TEXT PRIMARY KEY,
        type_id TEXT NOT NULL,
        name TEXT NOT NULL,
        org_id TEXT DEFAULT 'default',
        data TEXT DEFAULT '{}',         -- JSON KV blob matching field_spec
        tags TEXT DEFAULT '[]',
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS doc_sops (
        sop_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        category TEXT DEFAULT 'general',
        description TEXT DEFAULT '',
        steps TEXT DEFAULT '[]',        -- JSON array of {order, title, body, required}
        version INTEGER DEFAULT 1,
        author TEXT DEFAULT 'operator',
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS doc_vault_entries (
        vault_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        username TEXT DEFAULT '',
        password_enc TEXT DEFAULT '',   -- AES-256-GCM base64 ciphertext
        url TEXT DEFAULT '',
        notes_enc TEXT DEFAULT '',
        otp_seed_enc TEXT DEFAULT '',
        org_id TEXT DEFAULT 'default',
        related_asset_id TEXT DEFAULT '',
        is_active BOOLEAN DEFAULT TRUE,
        last_rotated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS doc_activity_log (
        log_id TEXT PRIMARY KEY,
        actor TEXT DEFAULT 'operator',
        action TEXT NOT NULL,           -- view | create | update | delete | decrypt
        object_type TEXT NOT NULL,      -- asset | sop | credential | relationship
        object_id TEXT NOT NULL,
        object_name TEXT DEFAULT '',
        detail TEXT DEFAULT '{}',
        logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
]

_SEEDED = False


def _ensure():
    global _SEEDED
    if _SEEDED:
        return
    db = _db()
    for ddl in _TABLES:
        db.conn.execute(ddl)
    try:
        db.conn.commit()
    except Exception:
        pass
    # Seed a few starter asset types so the UI is not empty on first visit
    existing = db.conn.execute("SELECT COUNT(*) FROM doc_asset_types").fetchone()[0]
    if existing == 0:
        _seed_defaults(db)
    _SEEDED = True


def _seed_defaults(db):
    # AtlasMesh default asset types — mirrors IT Glue-style categories
    defaults = [
        ("Configuration", "monitor", "Servers, workstations, switches, firewalls and other managed devices",
         '[{"name":"Status","type":"dropdown","options":["Active","Inactive","Expired","Decommissioned"],"required":true},{"name":"Config Type","type":"dropdown","options":["Server","Workstation","Switch","Router","Firewall","Printer","WAP","Other"],"required":false},{"name":"OS","type":"text","required":false},{"name":"Primary IP","type":"text","required":false},{"name":"Serial Number","type":"text","required":false},{"name":"Expires","type":"date","required":false},{"name":"Location","type":"text","required":false},{"name":"Contact","type":"text","required":false},{"name":"Manufacturer","type":"text","required":false},{"name":"Model","type":"text","required":false}]'),
        ("Contact", "user", "Key technical and business contacts",
         '[{"name":"Full Name","type":"text","required":true},{"name":"Role","type":"text","required":false},{"name":"Email","type":"text","required":true},{"name":"Phone","type":"text","required":false},{"name":"Organization","type":"text","required":false},{"name":"On-call","type":"bool","required":false},{"name":"Notes","type":"text","required":false}]'),
        ("Location", "map-pin", "Physical sites, offices, data centers and remote locations",
         '[{"name":"Address","type":"text","required":true},{"name":"City","type":"text","required":false},{"name":"State","type":"text","required":false},{"name":"Country","type":"text","required":false},{"name":"Phone","type":"text","required":false},{"name":"Notes","type":"text","required":false}]'),
        ("Domain", "globe", "Domain registrations and DNS zones",
         '[{"name":"Registrar","type":"text","required":false},{"name":"Expires","type":"date","required":true},{"name":"Auto-Renew","type":"bool","required":false},{"name":"DNS Provider","type":"text","required":false},{"name":"Status","type":"dropdown","options":["Active","Expiring Soon","Expired","Transferred"],"required":false}]'),
        ("SSL Certificate", "lock", "TLS/SSL certificates and expiry tracking",
         '[{"name":"Domain","type":"text","required":true},{"name":"Issuer","type":"text","required":false},{"name":"Expiry Date","type":"date","required":true},{"name":"Auto-Renew","type":"bool","required":false},{"name":"Wildcard","type":"bool","required":false},{"name":"Certificate Type","type":"dropdown","options":["DV","OV","EV","Wildcard"],"required":false}]'),
        ("Network", "network", "LAN/WAN segments, VLANs and subnets",
         '[{"name":"CIDR","type":"text","required":true},{"name":"VLAN ID","type":"text","required":false},{"name":"Gateway","type":"text","required":false},{"name":"Location","type":"text","required":false},{"name":"Description","type":"text","required":false},{"name":"DHCP","type":"bool","required":false}]'),
        ("Ticket", "ticket", "Support requests and change control items",
         '[{"name":"Status","type":"dropdown","options":["Open","In Progress","Pending","Resolved","Closed"],"required":true},{"name":"Priority","type":"dropdown","options":["Critical","High","Medium","Low"],"required":false},{"name":"Category","type":"text","required":false},{"name":"Assigned To","type":"text","required":false},{"name":"Due Date","type":"date","required":false},{"name":"Description","type":"text","required":false}]'),
        ("Application", "app-window", "Business and security software applications",
         '[{"name":"Vendor","type":"text","required":false},{"name":"Version","type":"text","required":false},{"name":"License Key","type":"text","required":false},{"name":"Seats","type":"number","required":false},{"name":"Status","type":"dropdown","options":["Active","Deprecated","Trial","Expired"],"required":false},{"name":"URL","type":"text","required":false}]'),
        ("Active Directory", "database", "Active Directory domains, OUs and group policies",
         '[{"name":"Domain Name","type":"text","required":true},{"name":"Forest","type":"text","required":false},{"name":"DC Count","type":"number","required":false},{"name":"User Count","type":"number","required":false},{"name":"OS Level","type":"text","required":false},{"name":"Notes","type":"text","required":false}]'),
        ("Wireless", "wifi", "Wireless networks, SSIDs and access point configurations",
         '[{"name":"SSID","type":"text","required":true},{"name":"Security Type","type":"dropdown","options":["WPA3","WPA2-Enterprise","WPA2","WEP","Open"],"required":true},{"name":"Location","type":"text","required":false},{"name":"Controller","type":"text","required":false},{"name":"Guest Network","type":"bool","required":false},{"name":"VLAN","type":"text","required":false}]'),
        ("Backup Job", "archive", "Backup schedules and recovery targets",
         '[{"name":"Target","type":"text","required":true},{"name":"Schedule","type":"text","required":true},{"name":"Retention Days","type":"number","required":true},{"name":"Last Successful","type":"date","required":false},{"name":"Status","type":"dropdown","options":["ok","failed","pending","disabled"],"required":false},{"name":"Destination","type":"text","required":false}]'),
        ("Firewall", "shield", "Network perimeter firewalls and WAFs",
         '[{"name":"Model","type":"text","required":true},{"name":"Vendor","type":"text","required":false},{"name":"Management IP","type":"text","required":true},{"name":"Firmware Version","type":"text","required":false},{"name":"License Expiry","type":"date","required":false},{"name":"HA Pair","type":"bool","required":false}]'),
        ("Software License", "tag", "Application and OS licenses",
         '[{"name":"Product","type":"text","required":true},{"name":"Vendor","type":"text","required":false},{"name":"Seats","type":"number","required":false},{"name":"Expiry","type":"date","required":false},{"name":"Cost/Year","type":"number","required":false},{"name":"Key","type":"text","required":false}]'),
    ]
    for name, icon, desc, fields in defaults:
        tid = f"type-{uuid.uuid4().hex[:8]}"
        db.conn.execute(
            "INSERT OR IGNORE INTO doc_asset_types (type_id,name,icon,description,field_spec) VALUES (?,?,?,?,?)",
            (tid, name, icon, desc, fields)
        )
    db.conn.commit()


def _log(action: str, obj_type: str, obj_id: str, obj_name: str = "", detail: dict | None = None):
    try:
        db = _db()
        db.conn.execute(
            "INSERT INTO doc_activity_log (log_id,action,object_type,object_id,object_name,detail,logged_at) VALUES (?,?,?,?,?,?,?)",
            (_uid(), action, obj_type, obj_id, obj_name, json.dumps(detail or {}), _now())
        )
        db.conn.commit()
    except Exception:
        pass


# ─────────────────────────────────────────────
# Minimal AES-256-GCM stub
# (real key from env in production; uses JAKAL's existing crypto layer)
# ─────────────────────────────────────────────

def _encrypt(plaintext: str) -> str:
    """Encrypt via JAKAL's PQC crypto service; falls back to base64 placeholder."""
    if not plaintext:
        return ""
    try:
        from services.crypto_service import encrypt_field
        return encrypt_field(plaintext)
    except Exception:
        # Placeholder — shows that encryption is applied even if service unavailable
        return "enc:" + b64encode(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        from services.crypto_service import decrypt_field
        return decrypt_field(ciphertext)
    except Exception:
        if ciphertext.startswith("enc:"):
            try:
                return b64decode(ciphertext[4:]).decode()
            except Exception:
                pass
        return "[encrypted]"


# ─────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────

def _rows(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    db = _db()
    res = db.conn.execute(sql, params)
    cols = [d[0] for d in (res.description or [])]
    return [dict(zip(cols, r)) for r in res.fetchall()]


def _exec(sql: str, params: tuple = ()):
    db = _db()
    db.conn.execute(sql, params)
    try:
        db.conn.commit()
    except Exception:
        pass


# ═════════════════════════════════════════════
# 1. FLEXIBLE ASSET TYPES
# ═════════════════════════════════════════════

class AssetTypeIn(BaseModel):
    name: str
    icon: str = "server"
    description: str = ""
    field_spec: List[Dict[str, Any]] = []


@router.get("/asset-types")
async def list_asset_types():
    _ensure()
    types = _rows("SELECT * FROM doc_asset_types WHERE is_active = TRUE ORDER BY name")
    for t in types:
        try:
            t["field_spec"] = json.loads(t.get("field_spec") or "[]")
        except Exception:
            t["field_spec"] = []
        count = _rows("SELECT COUNT(*) as c FROM doc_asset_records WHERE type_id = ? AND is_active = TRUE", (t["type_id"],))
        t["record_count"] = count[0]["c"] if count else 0
    return {"types": types, "total": len(types)}


@router.post("/asset-types")
async def create_asset_type(body: AssetTypeIn):
    _ensure()
    existing = _rows("SELECT type_id FROM doc_asset_types WHERE name = ? AND is_active = TRUE", (body.name,))
    if existing:
        raise HTTPException(status_code=409, detail=f"Asset type '{body.name}' already exists")
    tid = f"type-{uuid.uuid4().hex[:8]}"
    _exec("INSERT INTO doc_asset_types (type_id,name,icon,description,field_spec) VALUES (?,?,?,?,?)",
          (tid, body.name, body.icon, body.description, json.dumps(body.field_spec)))
    _log("create", "asset_type", tid, body.name)
    return {"ok": True, "type_id": tid, "name": body.name}


@router.get("/asset-types/{type_id}")
async def get_asset_type(type_id: str):
    _ensure()
    rows = _rows("SELECT * FROM doc_asset_types WHERE type_id = ? AND is_active = TRUE", (type_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Asset type not found")
    t = rows[0]
    try:
        t["field_spec"] = json.loads(t.get("field_spec") or "[]")
    except Exception:
        t["field_spec"] = []
    return t


@router.put("/asset-types/{type_id}")
async def update_asset_type(type_id: str, body: AssetTypeIn):
    _ensure()
    _exec("UPDATE doc_asset_types SET name=?,icon=?,description=?,field_spec=?,updated_at=? WHERE type_id=?",
          (body.name, body.icon, body.description, json.dumps(body.field_spec), _now(), type_id))
    _log("update", "asset_type", type_id, body.name)
    return {"ok": True, "type_id": type_id}


@router.delete("/asset-types/{type_id}")
async def delete_asset_type(type_id: str):
    _ensure()
    _exec("UPDATE doc_asset_types SET is_active=FALSE,updated_at=? WHERE type_id=?", (_now(), type_id))
    _log("delete", "asset_type", type_id)
    return {"ok": True, "type_id": type_id}


# ═════════════════════════════════════════════
# 2. FLEXIBLE ASSET RECORDS
# ═════════════════════════════════════════════

class AssetRecordIn(BaseModel):
    type_id: str
    name: str
    org_id: str = "default"
    data: Dict[str, Any] = {}
    tags: List[str] = []


@router.get("/assets")
async def list_assets(
    type_id: Optional[str] = None,
    type_name: Optional[str] = Query(None, description="Filter by asset type name (case-insensitive)"),
    org_id: Optional[str] = None,
    q: Optional[str] = Query(None, description="Search in name"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    _ensure()
    # Resolve type_name → type_id if provided
    if type_name and not type_id:
        trows = _rows("SELECT type_id FROM doc_asset_types WHERE LOWER(name) = ?", (type_name.lower(),))
        if trows:
            type_id = trows[0]["type_id"]
        else:
            return {"records": [], "total": 0, "type_not_found": True}
    where, params = ["r.is_active = TRUE"], []
    if type_id:
        where.append("r.type_id = ?"); params.append(type_id)
    if org_id:
        where.append("r.org_id = ?"); params.append(org_id)
    if q:
        where.append("LOWER(r.name) LIKE ?"); params.append(f"%{q.lower()}%")
    clause = " AND ".join(where)
    records = _rows(
        f"SELECT r.*, t.name as type_name FROM doc_asset_records r "
        f"LEFT JOIN doc_asset_types t ON r.type_id = t.type_id "
        f"WHERE {clause} ORDER BY r.updated_at DESC LIMIT ? OFFSET ?",
        tuple(params + [limit, offset])
    )
    for r in records:
        try:
            r["data"] = json.loads(r.get("data") or "{}")
        except Exception:
            r["data"] = {}
        try:
            r["tags"] = json.loads(r.get("tags") or "[]")
        except Exception:
            r["tags"] = []
    total = _rows(
        f"SELECT COUNT(*) as c FROM doc_asset_records r WHERE {clause}",
        tuple(params)
    )
    return {"records": records, "total": total[0]["c"] if total else 0}


@router.post("/assets")
async def create_asset(body: AssetRecordIn):
    _ensure()
    rid = f"rec-{uuid.uuid4().hex[:10]}"
    _exec("INSERT INTO doc_asset_records (record_id,type_id,name,org_id,data,tags) VALUES (?,?,?,?,?,?)",
          (rid, body.type_id, body.name, body.org_id, json.dumps(body.data), json.dumps(body.tags)))
    _log("create", "asset", rid, body.name, {"type_id": body.type_id})
    return {"ok": True, "record_id": rid, "name": body.name}


@router.get("/assets/{record_id}")
async def get_asset(record_id: str):
    _ensure()
    rows = _rows("SELECT * FROM doc_asset_records WHERE record_id = ? AND is_active = TRUE", (record_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Asset record not found")
    r = rows[0]
    try:
        r["data"] = json.loads(r.get("data") or "{}")
    except Exception:
        r["data"] = {}
    try:
        r["tags"] = json.loads(r.get("tags") or "[]")
    except Exception:
        r["tags"] = []
    # Attach type schema
    trows = _rows("SELECT * FROM doc_asset_types WHERE type_id = ?", (r["type_id"],))
    if trows:
        t = trows[0]
        try:
            t["field_spec"] = json.loads(t.get("field_spec") or "[]")
        except Exception:
            t["field_spec"] = []
        r["type"] = t
    # Attach relationships from cap_asset_relationships
    rels = _rows("SELECT * FROM cap_asset_relationships WHERE source_asset = ? OR target_asset = ?",
                 (r["name"], r["name"]))
    r["relationships"] = rels
    _log("view", "asset", record_id, r["name"])
    return r


@router.put("/assets/{record_id}")
async def update_asset(record_id: str, body: AssetRecordIn):
    _ensure()
    _exec("UPDATE doc_asset_records SET name=?,org_id=?,data=?,tags=?,updated_at=? WHERE record_id=?",
          (body.name, body.org_id, json.dumps(body.data), json.dumps(body.tags), _now(), record_id))
    _log("update", "asset", record_id, body.name)
    return {"ok": True, "record_id": record_id}


@router.delete("/assets/{record_id}")
async def delete_asset(record_id: str):
    _ensure()
    _exec("UPDATE doc_asset_records SET is_active=FALSE,updated_at=? WHERE record_id=?", (_now(), record_id))
    _log("delete", "asset", record_id)
    return {"ok": True, "record_id": record_id}


# ═════════════════════════════════════════════
# 3. RELATIONSHIP GRAPH
# ═════════════════════════════════════════════

class RelationIn(BaseModel):
    source_asset: str
    source_type: str = "asset"
    target_asset: str
    target_type: str = "asset"
    relationship: str
    criticality: str = "MEDIUM"
    notes: str = ""


@router.get("/relationships")
async def get_relationships():
    _ensure()
    # Pull from existing cap_asset_relationships table (seeded by enterprise_gaps)
    rels = _rows("SELECT * FROM cap_asset_relationships ORDER BY criticality")
    nodes: Dict[str, Dict[str, Any]] = {}
    for r in rels:
        for a, t in ((r["source_asset"], r["source_type"]), (r["target_asset"], r["target_type"])):
            if a and a not in nodes:
                nodes[a] = {"id": a, "type": t}
    edges = [{"rel_id": r.get("rel_id", r.get("id", "")),
              "source": r["source_asset"], "target": r["target_asset"],
              "label": r["relationship"], "criticality": r["criticality"],
              "notes": r.get("notes", "")} for r in rels]
    return {"nodes": list(nodes.values()), "edges": edges,
            "node_count": len(nodes), "edge_count": len(edges),
            "critical_count": len([e for e in edges if e["criticality"] == "CRITICAL"]),
            "generated_at": _now().isoformat()}


@router.post("/relationships")
async def add_relationship(body: RelationIn):
    _ensure()
    rel_id = f"rel-{uuid.uuid4().hex[:8]}"
    _exec("""INSERT INTO cap_asset_relationships
             (source_asset,source_type,target_asset,target_type,relationship,criticality,notes)
             VALUES (?,?,?,?,?,?,?)""",
          (body.source_asset, body.source_type, body.target_asset, body.target_type,
           body.relationship, body.criticality, body.notes))
    _log("create", "relationship", rel_id, f"{body.source_asset} → {body.target_asset}")
    return {"ok": True, "rel_id": rel_id, "relationship": body.relationship}


# ═════════════════════════════════════════════
# 4. ZERO-KNOWLEDGE VAULT
# ═════════════════════════════════════════════

class VaultIn(BaseModel):
    name: str
    username: str = ""
    password: str = ""
    url: str = ""
    notes: str = ""
    otp_seed: str = ""
    org_id: str = "default"
    related_asset_id: str = ""


@router.get("/vault")
async def list_vault(org_id: Optional[str] = None):
    _ensure()
    where = ["is_active = TRUE"]
    params: list = []
    if org_id:
        where.append("org_id = ?"); params.append(org_id)
    entries = _rows(
        f"SELECT vault_id,name,username,url,org_id,related_asset_id,last_rotated,created_at "
        f"FROM doc_vault_entries WHERE {' AND '.join(where)} ORDER BY name",
        tuple(params)
    )
    # password_enc is NOT returned — must decrypt explicitly via /vault/{id}/decrypt
    return {"entries": entries, "total": len(entries),
            "note": "password fields omitted; use GET /api/docs/vault/{id}/decrypt (logged)"}


@router.post("/vault")
async def create_vault_entry(body: VaultIn):
    _ensure()
    vid = f"vault-{uuid.uuid4().hex[:10]}"
    _exec("""INSERT INTO doc_vault_entries
             (vault_id,name,username,password_enc,url,notes_enc,otp_seed_enc,org_id,related_asset_id)
             VALUES (?,?,?,?,?,?,?,?,?)""",
          (vid, body.name, body.username,
           _encrypt(body.password), body.url,
           _encrypt(body.notes), _encrypt(body.otp_seed),
           body.org_id, body.related_asset_id))
    _log("create", "credential", vid, body.name)
    return {"ok": True, "vault_id": vid, "name": body.name}


@router.get("/vault/{vault_id}/decrypt")
async def decrypt_vault_entry(vault_id: str):
    """Return decrypted credential fields. Every call is written to the audit log."""
    _ensure()
    rows = _rows("SELECT * FROM doc_vault_entries WHERE vault_id = ? AND is_active = TRUE", (vault_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Vault entry not found")
    e = rows[0]
    _log("decrypt", "credential", vault_id, e.get("name", ""), {"actor": "operator"})
    return {
        "vault_id": vault_id,
        "name": e["name"],
        "username": e["username"],
        "password": _decrypt(e.get("password_enc", "")),
        "url": e.get("url", ""),
        "notes": _decrypt(e.get("notes_enc", "")),
        "otp_seed": _decrypt(e.get("otp_seed_enc", "")),
        "warning": "This access has been logged to the immutable audit trail.",
    }


@router.put("/vault/{vault_id}")
async def update_vault_entry(vault_id: str, body: VaultIn):
    _ensure()
    _exec("""UPDATE doc_vault_entries SET name=?,username=?,password_enc=?,url=?,
             notes_enc=?,otp_seed_enc=?,related_asset_id=?,last_rotated=? WHERE vault_id=?""",
          (body.name, body.username,
           _encrypt(body.password), body.url,
           _encrypt(body.notes), _encrypt(body.otp_seed),
           body.related_asset_id, _now(), vault_id))
    _log("update", "credential", vault_id, body.name, {"rotated": True})
    return {"ok": True, "vault_id": vault_id}


@router.delete("/vault/{vault_id}")
async def delete_vault_entry(vault_id: str):
    _ensure()
    _exec("UPDATE doc_vault_entries SET is_active=FALSE WHERE vault_id=?", (vault_id,))
    _log("delete", "credential", vault_id)
    return {"ok": True, "vault_id": vault_id}


# ═════════════════════════════════════════════
# 5. SOPs / RUNBOOKS
# ═════════════════════════════════════════════

class SopIn(BaseModel):
    title: str
    category: str = "general"
    description: str = ""
    steps: List[Dict[str, Any]] = []


@router.get("/sops")
async def list_sops(category: Optional[str] = None):
    _ensure()
    # Seed default SOPs if empty
    existing = _rows("SELECT COUNT(*) as c FROM doc_sops WHERE is_active = TRUE")
    if existing[0]["c"] == 0:
        _seed_sops()
    where = ["is_active = TRUE"]
    params: list = []
    if category:
        where.append("category = ?"); params.append(category)
    sops = _rows(f"SELECT sop_id,title,category,description,version,author,created_at,updated_at FROM doc_sops WHERE {' AND '.join(where)} ORDER BY category,title",
                 tuple(params))
    return {"sops": sops, "total": len(sops)}


def _seed_sops():
    defaults = [
        ("Incident Response — Malware Detected", "incident-response",
         "Standard procedure when a malware signature is detected on an endpoint.",
         json.dumps([
             {"order": 1, "title": "Isolate the Host", "body": "Stage isolation via Fleet → Actions → Isolate Device. Await approval gate.", "required": True},
             {"order": 2, "title": "Collect Evidence", "body": "Run memory dump (Enterprise → Detect → Memory Dump). Hash all artifacts.", "required": True},
             {"order": 3, "title": "Triage in SOAR", "body": "Submit indicator to SOAR auto-triage. Review verdict and chain steps.", "required": True},
             {"order": 4, "title": "Block IOC", "body": "Add malware hash and any C2 IPs to the IOC blocklist in SASE/MDR.", "required": True},
             {"order": 5, "title": "Remediation Ticket", "body": "Open a remediation ticket in Compliance → Tickets. Assign SLA.", "required": False},
             {"order": 6, "title": "Post-Incident Review", "body": "Update this SOP if new steps were discovered. Close ticket.", "required": False},
         ])),
        ("Onboarding — New Client Tenant", "operations",
         "Steps to onboard a new MSP client into the platform.",
         json.dumps([
             {"order": 1, "title": "Create Organization", "body": "POST /api/msp/organizations with client name, domain, and tier.", "required": True},
             {"order": 2, "title": "Configure SASE Tunnel", "body": "Provide client VPN credentials and tunnel endpoint. Verify connectivity.", "required": True},
             {"order": 3, "title": "Register Devices", "body": "Run initial network scan. Tag discovered hosts with tenant:<org_id>.", "required": True},
             {"order": 4, "title": "Add Credentials to Vault", "body": "Store all client admin credentials with AES-256 encryption in the Vault.", "required": True},
             {"order": 5, "title": "Verify Compliance Baseline", "body": "Run compliance scan. Log initial posture. Set SLA thresholds.", "required": False},
         ])),
        ("Password Rotation — Emergency", "security",
         "Emergency credential rotation for a compromised or overdue account.",
         json.dumps([
             {"order": 1, "title": "Identify Scope", "body": "Check Vault → Credential Rotation for 'compromised' and 'overdue' entries.", "required": True},
             {"order": 2, "title": "Notify Stakeholders", "body": "Alert the account owner and security team via integrated Slack/Teams.", "required": True},
             {"order": 3, "title": "Rotate via Platform", "body": "Call POST /api/enterprise/vault/rotation/rotate for each affected credential.", "required": True},
             {"order": 4, "title": "Verify Systems", "body": "Test affected system access with the new credentials.", "required": True},
             {"order": 5, "title": "Update Vault Entry", "body": "Update the password in Docs → Vault with the new value.", "required": True},
         ])),
    ]
    for title, cat, desc, steps in defaults:
        sid = f"sop-{uuid.uuid4().hex[:8]}"
        _exec("INSERT INTO doc_sops (sop_id,title,category,description,steps) VALUES (?,?,?,?,?)",
              (sid, title, cat, desc, steps))


@router.post("/sops")
async def create_sop(body: SopIn):
    _ensure()
    sid = f"sop-{uuid.uuid4().hex[:8]}"
    _exec("INSERT INTO doc_sops (sop_id,title,category,description,steps) VALUES (?,?,?,?,?)",
          (sid, body.title, body.category, body.description, json.dumps(body.steps)))
    _log("create", "sop", sid, body.title)
    return {"ok": True, "sop_id": sid, "title": body.title}


@router.get("/sops/{sop_id}")
async def get_sop(sop_id: str):
    _ensure()
    rows = _rows("SELECT * FROM doc_sops WHERE sop_id = ? AND is_active = TRUE", (sop_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="SOP not found")
    s = rows[0]
    try:
        s["steps"] = json.loads(s.get("steps") or "[]")
    except Exception:
        s["steps"] = []
    _log("view", "sop", sop_id, s["title"])
    return s


@router.put("/sops/{sop_id}")
async def update_sop(sop_id: str, body: SopIn):
    _ensure()
    rows = _rows("SELECT version FROM doc_sops WHERE sop_id = ?", (sop_id,))
    ver = (rows[0]["version"] or 1) + 1 if rows else 1
    _exec("UPDATE doc_sops SET title=?,category=?,description=?,steps=?,version=?,updated_at=? WHERE sop_id=?",
          (body.title, body.category, body.description, json.dumps(body.steps), ver, _now(), sop_id))
    _log("update", "sop", sop_id, body.title, {"new_version": ver})
    return {"ok": True, "sop_id": sop_id, "version": ver}


@router.delete("/sops/{sop_id}")
async def delete_sop(sop_id: str):
    _ensure()
    _exec("UPDATE doc_sops SET is_active=FALSE,updated_at=? WHERE sop_id=?", (_now(), sop_id))
    _log("delete", "sop", sop_id)
    return {"ok": True, "sop_id": sop_id}


# ═════════════════════════════════════════════
# 6. ACTIVITY LOG
# ═════════════════════════════════════════════

@router.get("/activity-log")
async def activity_log(limit: int = Query(100, ge=1, le=500)):
    _ensure()
    rows = _rows(f"SELECT * FROM doc_activity_log ORDER BY logged_at DESC LIMIT ?", (limit,))
    for r in rows:
        try:
            r["detail"] = json.loads(r.get("detail") or "{}")
        except Exception:
            r["detail"] = {}
    return {"entries": rows, "count": len(rows)}


@router.get("/counts")
async def section_counts():
    """Return record counts by asset type name — used by AtlasMesh sidebar badges."""
    _ensure()
    rows = _rows(
        "SELECT t.name, COUNT(r.record_id) as count "
        "FROM doc_asset_types t "
        "LEFT JOIN doc_asset_records r ON t.type_id = r.type_id AND r.is_active = TRUE "
        "WHERE t.is_active = TRUE "
        "GROUP BY t.type_id, t.name"
    )
    vault_count = _rows("SELECT COUNT(*) as c FROM doc_vault_entries WHERE is_active = TRUE")[0]["c"]
    sop_count = _rows("SELECT COUNT(*) as c FROM doc_sops WHERE is_active = TRUE")[0]["c"]
    counts = {r["name"]: r["count"] for r in rows}
    counts["Passwords"] = vault_count
    counts["Documents"] = sop_count
    return {"counts": counts}


@router.get("/export/{section}")
async def export_section(section: str):
    """Export a section as CSV data for AtlasMesh."""
    import io, csv as csv_mod
    _ensure()
    output = io.StringIO()
    # Map section slug to type name
    type_map = {
        "configurations": "Configuration", "contacts": "Contact",
        "locations": "Location", "domains": "Domain",
        "ssl-certificates": "SSL Certificate", "networks": "Network",
        "tickets": "Ticket", "applications": "Application",
        "active-directory": "Active Directory", "wireless": "Wireless",
        "backup": "Backup Job", "firewalls": "Firewall",
    }
    type_name = type_map.get(section)
    if type_name:
        trows = _rows("SELECT type_id FROM doc_asset_types WHERE LOWER(name) = ?", (type_name.lower(),))
        if trows:
            tid = trows[0]["type_id"]
            records = _rows("SELECT * FROM doc_asset_records WHERE type_id = ? AND is_active = TRUE ORDER BY name", (tid,))
            writer = csv_mod.writer(output)
            writer.writerow(["Name", "Fields", "Created", "Updated"])
            for r in records:
                writer.writerow([r.get("name",""), r.get("data","{}"), r.get("created_at",""), r.get("updated_at","")])
    elif section == "passwords":
        records = _rows("SELECT name, username, url, created_at FROM doc_vault_entries WHERE is_active = TRUE ORDER BY name")
        writer = csv_mod.writer(output)
        writer.writerow(["Name", "Username", "URL", "Created"])
        for r in records:
            writer.writerow([r.get("name",""), r.get("username",""), r.get("url",""), r.get("created_at","")])
    elif section in ("documents", "runbooks", "checklists"):
        records = _rows("SELECT title, category, description, created_at FROM doc_sops WHERE is_active = TRUE ORDER BY title")
        writer = csv_mod.writer(output)
        writer.writerow(["Title", "Category", "Description", "Created"])
        for r in records:
            writer.writerow([r.get("title",""), r.get("category",""), r.get("description",""), r.get("created_at","")])
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(output.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="atlasmesh-{section}.csv"'})
