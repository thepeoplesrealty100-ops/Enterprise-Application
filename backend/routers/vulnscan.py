"""
routers/vulnscan.py — unified vulnerability scanning surface.

POST /api/vulnscan  {products:[{name,version,ecosystem?,vendor?}]}
  Routes package-ecosystem items to OSV.dev and OS/application items to the
  NVD/CPE scanner, returning merged live results. No seeded data.
"""
from typing import Any, Dict, List
from fastapi import APIRouter
from pydantic import BaseModel
from services.vuln_scanner import scan_combined, osv_scan
from services.nvd_scanner import nvd_scan

router = APIRouter(prefix="/api/vulnscan", tags=["Vulnerability Scanning"])


class ScanReq(BaseModel):
    products: List[Dict[str, Any]] = []


@router.post("")
async def scan(req: ScanReq):
    return scan_combined(req.products)


@router.post("/osv")
async def scan_osv(req: ScanReq):
    return osv_scan(req.products)


@router.post("/nvd")
async def scan_nvd(req: ScanReq):
    return nvd_scan(req.products)
