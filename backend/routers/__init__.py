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
v2.4 routers:
  horizon_router   — /api/horizon/*   (AI-safety event stream + regulatory-compliance rollup)
  canvas_router     — /api/canvas/*    (Agentic Canvas — patch deploys gated by the Approval Gate)
  resonance_router  — /api/resonance/* (fleet posture + derived org-wide security settings)
  qaip_router       — /api/qaip/*      (Energy Core throttle + quantum/LLM inference ledger)
v2.5 routers:
  ares_router       — /api/ares/*      (Ares Unified Control Plane — cross-pillar
                                         event bus + Horizon/Resonance/Fabric rollup)
v2.6 routers — Global Settings & Security + remaining Human/Risk Layer modules:
  iam_router        — /api/iam/*       (Profile, Login/MFA, RBAC, API keys, Auditing)
  vault_router      — /api/vault/*     (EAS R&D dependency scanner + Trade Secrets vault)
  awareness_router  — /api/awareness/* (Security Awareness Training + Phishing Campaigns)
  darkweb_router    — /api/darkweb/*   (Dark Web Monitoring — HIBP connector + manual feed)
  cheatsheet_router — /api/cheatsheet/* (CheatSheet Library — exposes the existing ontology,
                                          plus v2.7's real script catalog + staged execution)
v2.7 routers:
  response_router   — /api/response/*  (Detection & Response — triage, IOC block, quarantine, isolate)
  scripts_router    — /api/scripts/*   (operator-uploaded script marketplace + sandbox execution;
                                         complementary to cheatsheet_router's prepopulated,
                                         auto-indexed gacyber_toolkit script catalog)
v3.0 routers:
  ontology_router   — /api/v3/ontology/*  (Palantir Foundry-style Object/Link digital twin --
                                            see services/ontology_engine.py)
  maya_auth_router  — /api/v3/auth/maya/* (Maya-Vigesimal calendar 2FA challenge, interlocked
                                            with the v2.3 Human Approval Gate for HIGH/CRITICAL
                                            staged payloads -- see security_agents/exploit_agent.py)
v3.0 Phase 4 routers:
  aip_cheatsheet_router — /api/v3/aip/cheatsheet/* (thin prompt -> matching-playbook lookup
                                            over the existing playbook_library.PLAYBOOKS
                                            catalog -- see payloads/aip_cheatsheet_engine.py)
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
from .horizon import router as horizon_router
from .canvas import router as canvas_router
from .resonance import router as resonance_router
from .qaip import router as qaip_router
from .ares import router as ares_router
from .iam import router as iam_router
from .vault import router as vault_router
from .awareness import router as awareness_router
from .darkweb import router as darkweb_router
from .cheatsheet import router as cheatsheet_router
from .response import router as response_router
from .scripts import router as scripts_router
from .ui_bridge import router as ui_bridge_router
from .ontology_router import router as ontology_router
from .maya_auth_router import router as maya_auth_router
from .aip_cheatsheet_router import router as aip_cheatsheet_router

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
    "horizon_router",
    "canvas_router",
    "resonance_router",
    "qaip_router",
    "ares_router",
    "iam_router",
    "vault_router",
    "awareness_router",
    "darkweb_router",
    "cheatsheet_router",
    "response_router",
    "scripts_router",
    "ui_bridge_router",
    "ontology_router",
    "maya_auth_router",
    "aip_cheatsheet_router",
]
