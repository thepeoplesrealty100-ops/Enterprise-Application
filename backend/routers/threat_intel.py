"""
routers/threat_intel.py — live indicator enrichment surface (Target A).

GET/POST /api/threatintel/lookup — enrich an IP/domain/URL/hash against live
threat feeds (keyless Feodo + Tor out of the box; VirusTotal/AbuseIPDB/OTX
when configured in the Integrations vault). Read-only; returns no secrets.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from services import threat_intel

router = APIRouter(prefix="/api/threatintel", tags=["Threat Intelligence"])


class LookupRequest(BaseModel):
    indicator: str


@router.get("/lookup")
async def lookup_get(indicator: str):
    return threat_intel.lookup(indicator)


@router.post("/lookup")
async def lookup_post(req: LookupRequest):
    return threat_intel.lookup(req.indicator)
