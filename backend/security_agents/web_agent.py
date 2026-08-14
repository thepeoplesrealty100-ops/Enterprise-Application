"""
JAKAL Security Agent - Web Application (CPENT Phase 4) — SAFE CHECKS ONLY

This agent performs passive and low-risk active checks: reading response
headers, checking TLS configuration, looking for common misconfigurations
(missing security headers, verbose error pages, directory listing enabled,
exposed .git/.env files). It does not send injection payloads (SQLi, XSS,
XXE, etc.), does not attempt authentication bypass, and does not fuzz for
exploitable input -- that line is intentional, see README_FIXES.md.

If you have Nikto installed, `_run_nikto` will use it for its standard
misconfiguration checks (also not an exploitation tool -- it's a
config/vuln *scanner*, same category as Nuclei).
"""

import logging
import socket
import ssl
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from tools.authorization import check_authorization_and_scope

logger = logging.getLogger(__name__)

# Headers whose ABSENCE is itself a finding.
_EXPECTED_SECURITY_HEADERS = {
    "Strict-Transport-Security": "medium",
    "Content-Security-Policy": "medium",
    "X-Content-Type-Options": "low",
    "X-Frame-Options": "low",
    "Referrer-Policy": "low",
}

# Paths that should never be publicly reachable if present.
_SENSITIVE_PATHS = [
    ".env", ".git/config", ".git/HEAD", "wp-config.php.bak",
    "config.php.bak", ".DS_Store", "backup.sql", ".aws/credentials",
]


class WebAgent:
    def __init__(self, db_manager=None, config=None):
        self.db = db_manager
        self.config = config

    def scan(self, target: str, operator_id: str = "system") -> Dict[str, Any]:
        check_authorization_and_scope(target, "web_agent_scan", operator_id, db=self.db)

        base_url = target if target.startswith(("http://", "https://")) else f"https://{target}"

        results: Dict[str, Any] = {
            "phase": "CPENT-Phase-4-WebApplication",
            "target": target,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tls": self._check_tls(target),
            "security_headers": self._check_security_headers(base_url),
            "exposed_paths": self._check_sensitive_paths(base_url),
            "directory_listing": self._check_directory_listing(base_url),
            "nikto": self._run_nikto(target),
        }

        results["findings_summary"] = self._summarize(results)

        if self.db:
            self.db.insert_log({
                "event": "WEB_SCAN_COMPLETED",
                "action": "web_agent_scan",
                "status": "success",
                "operator_id": operator_id,
                "details": {"target": target, "findings": len(results["findings_summary"])},
            })

        return results

    # ------------------------------------------------------------------
    # TLS
    # ------------------------------------------------------------------

    def _check_tls(self, target: str, port: int = 443) -> Dict[str, Any]:
        hostname = target.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((hostname, port), timeout=8) as sock:
                with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()
                    cipher = ssock.cipher()
                    not_after = cert.get("notAfter")
                    return {
                        "connected": True,
                        "tls_version": ssock.version(),
                        "cipher_suite": cipher[0] if cipher else None,
                        "cert_expires": not_after,
                        "cert_subject": dict(x[0] for x in cert.get("subject", [])),
                    }
        except ssl.SSLCertVerificationError as e:
            return {"connected": True, "cert_valid": False, "error": str(e), "finding": "MEDIUM: TLS certificate validation failed"}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Security headers
    # ------------------------------------------------------------------

    def _check_security_headers(self, base_url: str) -> Dict[str, Any]:
        try:
            import requests
            resp = requests.get(base_url, timeout=8, allow_redirects=True, verify=False)
            missing = []
            present = {}
            for header, severity in _EXPECTED_SECURITY_HEADERS.items():
                if header in resp.headers:
                    present[header] = resp.headers[header]
                else:
                    missing.append({"header": header, "severity": severity})
            return {"present": present, "missing": missing, "status_code": resp.status_code}
        except ImportError:
            return {"error": "requests library not installed"}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Exposed sensitive paths (read-only GET, checks status code only)
    # ------------------------------------------------------------------

    def _check_sensitive_paths(self, base_url: str) -> List[Dict[str, Any]]:
        try:
            import requests
        except ImportError:
            return [{"error": "requests library not installed"}]

        exposed = []
        for path in _SENSITIVE_PATHS:
            url = urljoin(base_url + "/", path)
            try:
                resp = requests.get(url, timeout=6, allow_redirects=False, verify=False)
                if resp.status_code == 200:
                    exposed.append({
                        "path": path,
                        "url": url,
                        "status_code": resp.status_code,
                        "severity": "high",
                        "finding": f"Sensitive file publicly accessible: {path}",
                    })
            except requests.exceptions.RequestException:
                continue
        return exposed

    # ------------------------------------------------------------------
    # Directory listing
    # ------------------------------------------------------------------

    def _check_directory_listing(self, base_url: str) -> Dict[str, Any]:
        try:
            import requests
            resp = requests.get(base_url, timeout=8, verify=False)
            indicators = ["Index of /", "<title>Index of", "Directory Listing For"]
            listing_enabled = any(ind in resp.text for ind in indicators)
            return {
                "enabled": listing_enabled,
                "finding": "MEDIUM: directory listing appears enabled on root path" if listing_enabled else None,
            }
        except ImportError:
            return {"error": "requests library not installed"}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Nikto (external scanner, not exploitation)
    # ------------------------------------------------------------------

    def _run_nikto(self, target: str, timeout_seconds: int = 300) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                ["nikto", "-h", target, "-Format", "txt", "-nointeractive"],
                shell=False, capture_output=True, text=True, timeout=timeout_seconds,
            )
            return {"ran": True, "output": result.stdout[-4000:]}  # tail, nikto output can be long
        except FileNotFoundError:
            return {"ran": False, "note": "nikto not installed"}
        except subprocess.TimeoutExpired:
            return {"ran": False, "note": "nikto scan timed out"}
        except Exception as e:
            return {"ran": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    @staticmethod
    def _summarize(results: Dict[str, Any]) -> List[str]:
        findings = []
        for h in results.get("security_headers", {}).get("missing", []):
            findings.append(f"[{h['severity'].upper()}] Missing security header: {h['header']}")
        for p in results.get("exposed_paths", []):
            if "finding" in p:
                findings.append(f"[{p['severity'].upper()}] {p['finding']}")
        if results.get("directory_listing", {}).get("finding"):
            findings.append(results["directory_listing"]["finding"])
        if results.get("tls", {}).get("finding"):
            findings.append(results["tls"]["finding"])
        return findings
