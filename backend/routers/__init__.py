"""
backend/routers
FastAPI router package for JAKAL API endpoints.

v2.1 routers:
  pentest_router  — /api/pentest/*
  quantum_router  — /api/quantum/*
  reports_router  — /api/reports/*
  crypto_router   — /api/crypto/*
  payloads_router — /api/* (payloads, playbooks, threat-intel, network-map, vuln-db)
v2.2 routers:
  aip_router      — /api/aip/* (ontology-driven payload gen interwoven with cheatsheets)
  fabric_router   — /api/fabric/* (Unified Security Fabric — 7 capabilities in one module)
v2.3 routers:
  wireless_router — /api/wireless/* (passive Wi-Fi survey; active payloads via /aip/generate)
  approval_router — /api/approval/* (Human Approval Gate — stage/approve/deny/execute)
"""

from .pentest import router as pentest_router
from .quantum import router as quantum_router
from .reports import router as reports_router
from .crypto import router as crypto_router
from .payloads import router as payloads_router
from .aip import router as aip_router
from .fabric import router as fabric_router
from .wireless import router as wireless_router
from .approval import router as approval_router

__all__ = [
    "pentest_router",
    "quantum_router",
    "reports_router",
    "crypto_router",
    "payloads_router",
    "aip_router",
    "fabric_router",
    "wireless_router",
    "approval_router",
]
