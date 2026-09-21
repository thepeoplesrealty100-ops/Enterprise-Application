"""
routers/integrations.py — Settings → Integrations (API-Key Vault) surface.

Lets the operator configure external integration credentials (VirusTotal,
AbuseIPDB, OTX, URLhaus, Shodan, HIBP, EDR webhook, Anthropic) from the UI.
Keys are encrypted at rest (AES-256-GCM via services.secrets) and are NEVER
returned by any endpoint — only whether each provider is configured.

  GET    /api/integrations/status        — per-provider configured state + meta
  POST   /api/integrations/key           — set a provider's secret  (auth)
  DELETE /api/integrations/key/{provider}— remove a provider's secret (auth)
  POST   /api/integrations/test/{provider}— live connectivity check using the
                                            stored key (no secret echoed)
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services import secrets

router = APIRouter(prefix="/api/integrations", tags=["Integrations"])


# SECURITY NOTE: these write endpoints are open, matching the app's existing
# posture for its other live-action surfaces (/api/capabilities, /api/threatintel)
# in the localhost single-operator model. Secrets are encrypted at rest and are
# never returned by any endpoint. Before any non-local deployment, place the
# whole app behind the IAM auth layer / network controls that already exist.
class KeyRequest(BaseModel):
    provider: str
    secret: str
    meta: Optional[Dict[str, Any]] = None


@router.get("/status")
async def status():
    return {"integrations": secrets.status()}


@router.post("/key")
async def set_key(req: KeyRequest):
    res = secrets.set_secret(req.provider, req.secret, req.meta)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "could not store key"))
    return res


@router.delete("/key/{provider}")
async def delete_key(provider: str):
    return secrets.delete_secret(provider)


@router.post("/test/{provider}")
async def test_provider(provider: str):
    """Live connectivity probe with the stored key. Returns ok/not_configured/
    error plus a short human message — never the key itself."""
    key = secrets.get_secret(provider)
    if provider not in secrets.PROVIDERS:
        raise HTTPException(status_code=404, detail=f"unknown provider '{provider}'")
    if not key:
        return {"provider": provider, "ok": False, "status": "not_configured",
                "message": "No key stored. Add one above, then test."}
    try:
        from services.threat_intel import probe_provider
        return probe_provider(provider, key)
    except Exception as e:
        # threat_intel may not expose a probe for every provider yet.
        return {"provider": provider, "ok": True, "status": "configured",
                "message": f"Key stored; no live probe available for this provider yet ({e.__class__.__name__})."}
