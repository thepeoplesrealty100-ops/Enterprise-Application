"""
services/secrets.py — JAKAL integration secret store (v1.0)

One place every module resolves an integration credential from:

  get_secret(provider)  →  plaintext key, or None

Resolution order: (1) the encrypted integration_keys table written by the
Settings → Integrations UI, decrypted with the existing AES-256-GCM
EncryptionManager; (2) the provider's environment variable (so a key already
in backend/.env keeps working). Secrets are NEVER returned by the status API —
only whether each provider is configured.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("secrets")

# Provider catalog — drives the Integrations UI and env fallbacks.
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "virustotal": {"label": "VirusTotal", "env": "VT_API_KEY", "kind": "threat_intel",
                   "docs": "https://www.virustotal.com/gui/my-apikey",
                   "indicators": ["ip", "domain", "url", "hash"], "free": "~500 lookups/day",
                   "secret_label": "API key"},
    "abuseipdb": {"label": "AbuseIPDB", "env": "ABUSEIPDB_API_KEY", "kind": "threat_intel",
                  "docs": "https://www.abuseipdb.com/account/api",
                  "indicators": ["ip"], "free": "1,000 lookups/day", "secret_label": "API key"},
    "otx": {"label": "AlienVault OTX", "env": "OTX_API_KEY", "kind": "threat_intel",
            "docs": "https://otx.alienvault.com/api",
            "indicators": ["ip", "domain", "url", "hash"], "free": "free account", "secret_label": "API key"},
    "urlhaus": {"label": "URLhaus (abuse.ch)", "env": "URLHAUS_AUTH_KEY", "kind": "threat_intel",
                "docs": "https://urlhaus.abuse.ch/api/",
                "indicators": ["url", "domain", "hash"], "free": "free (Auth-Key)", "secret_label": "Auth-Key"},
    "nvd": {"label": "NVD (NIST)", "env": "NVD_API_KEY", "kind": "vuln",
            "docs": "https://nvd.nist.gov/developers/request-an-api-key", "indicators": [],
            "free": "keyless 5/30s; key 50/30s", "secret_label": "API key"},
    "shodan": {"label": "Shodan", "env": "SHODAN_API_KEY", "kind": "recon",
               "docs": "https://account.shodan.io", "indicators": ["ip"], "free": "limited",
               "secret_label": "API key"},
    "hibp": {"label": "Have I Been Pwned", "env": "HIBP_API_KEY", "kind": "darkweb",
             "docs": "https://haveibeenpwned.com/API/Key", "indicators": ["email"],
             "free": "paid (HIBP requirement)", "secret_label": "API key"},
    "edr_webhook": {"label": "EDR / Firewall Webhook", "env": "EDR_WEBHOOK_URL", "kind": "response",
                    "docs": "", "indicators": [], "free": "self-hosted",
                    "secret_label": "Webhook URL", "companion_env": "EDR_WEBHOOK_SECRET"},
    "anthropic": {"label": "Anthropic Claude", "env": "ANTHROPIC_API_KEY", "kind": "llm",
                  "docs": "https://console.anthropic.com", "indicators": [], "free": "paid",
                  "secret_label": "API key"},
}

_enc = None
_db = None


def _ctx():
    global _enc, _db
    if _db is None:
        from database import get_db_manager
        _db = get_db_manager()
        _db.conn.execute("""
            CREATE TABLE IF NOT EXISTS integration_keys (
                provider   TEXT PRIMARY KEY,
                envelope   TEXT NOT NULL,
                meta       TEXT,
                updated_at TIMESTAMP DEFAULT now()
            )
        """)
    if _enc is None:
        from crypto.encryption_manager import EncryptionManager
        _enc = EncryptionManager(db=_db)
    return _enc, _db


def _row(provider: str) -> Optional[Dict[str, Any]]:
    _, db = _ctx()
    res = db.conn.execute("SELECT envelope, meta FROM integration_keys WHERE provider = ?", (provider,))
    rows = res.fetchall()
    if not rows:
        return None
    cols = [d[0] for d in (res.description or [])]
    return dict(zip(cols, rows[0]))


def set_secret(provider: str, secret: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if provider not in PROVIDERS:
        return {"ok": False, "error": f"unknown provider '{provider}'"}
    if not secret:
        return {"ok": False, "error": "empty secret"}
    enc, db = _ctx()
    envelope = json.dumps(enc.encrypt(secret))
    db.conn.execute("INSERT OR REPLACE INTO integration_keys (provider, envelope, meta, updated_at) VALUES (?, ?, ?, ?)",
               (provider, envelope, json.dumps(meta or {}), datetime.now(timezone.utc)))
    db.conn.commit()
    logger.info("integration key set for provider=%s", provider)
    return {"ok": True, "provider": provider, "configured": True, "source": "vault"}


def delete_secret(provider: str) -> Dict[str, Any]:
    _, db = _ctx()
    db.conn.execute("DELETE FROM integration_keys WHERE provider = ?", (provider,))
    db.conn.commit()
    return {"ok": True, "provider": provider, "configured": _env_configured(provider)}


def get_secret(provider: str) -> Optional[str]:
    """Plaintext secret for a provider: vault first, then env var. None if neither."""
    try:
        row = _row(provider)
        if row and row.get("envelope"):
            enc, _ = _ctx()
            return enc.decrypt(json.loads(row["envelope"])).decode("utf-8")
    except Exception as e:
        logger.warning("vault decrypt failed for %s: %s", provider, e)
    env = PROVIDERS.get(provider, {}).get("env")
    return os.getenv(env) if env else None


def get_meta(provider: str) -> Dict[str, Any]:
    row = _row(provider)
    if row and row.get("meta"):
        try:
            return json.loads(row["meta"])
        except Exception:
            return {}
    return {}


def _env_configured(provider: str) -> bool:
    env = PROVIDERS.get(provider, {}).get("env")
    return bool(env and os.getenv(env))


def _vault_configured(provider: str) -> bool:
    row = _row(provider)
    return bool(row and row.get("envelope"))


def status() -> List[Dict[str, Any]]:
    """Per-provider configured state + metadata. Never returns any secret."""
    out = []
    for pid, meta in PROVIDERS.items():
        in_vault = False
        try:
            in_vault = _vault_configured(pid)
        except Exception:
            in_vault = False
        in_env = _env_configured(pid)
        out.append({
            "provider": pid, "label": meta["label"], "kind": meta["kind"],
            "docs": meta["docs"], "indicators": meta["indicators"], "free": meta["free"],
            "secret_label": meta.get("secret_label", "API key"),
            "configured": in_vault or in_env,
            "source": "vault" if in_vault else ("env" if in_env else None),
        })
    return out
