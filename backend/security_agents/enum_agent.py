"""
JAKAL Security Agent - Enumeration (CPENT Phase 3)

Deeper, still-passive-or-authorized-active enumeration beyond basic recon:
- DNS zone transfer attempts (a standard authorized test -- a server that
  allows AXFR to anyone is itself a finding, not something being "exploited")
- SNMP public/private community string probing (read-only queries)
- SMB share enumeration (listing, not accessing content)
- HTTP technology fingerprinting

Everything here reads/lists/queries. Nothing here writes to a target,
authenticates with cracked or guessed credentials, or executes code on a
target. That distinction is what keeps this in "enumeration" rather than
"exploitation."
"""

import logging
import re
import socket
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from tools.authorization import check_authorization_and_scope

logger = logging.getLogger(__name__)


class EnumAgent:
    def __init__(self, db_manager=None, config=None):
        self.db = db_manager
        self.config = config

    def enumerate(
        self,
        target: str,
        open_ports: Optional[List[Dict[str, Any]]] = None,
        operator_id: str = "system",
    ) -> Dict[str, Any]:
        check_authorization_and_scope(target, "enum_agent_enumerate", operator_id, db=self.db)

        open_ports = open_ports or []
        port_numbers = {p.get("port") for p in open_ports}

        results: Dict[str, Any] = {
            "phase": "CPENT-Phase-3-Enumeration",
            "target": target,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dns_zone_transfer": self._attempt_zone_transfer(target),
            "smb_shares": self._enumerate_smb(target) if 445 in port_numbers or 139 in port_numbers else {"skipped": "no SMB ports open"},
            "snmp": self._enumerate_snmp(target) if 161 in port_numbers else {"skipped": "no SNMP port open"},
            "http_fingerprint": self._fingerprint_http(target) if (80 in port_numbers or 443 in port_numbers) else {"skipped": "no HTTP(S) ports open"},
        }

        if self.db:
            self.db.insert_log({
                "event": "ENUM_COMPLETED",
                "action": "enumerate",
                "status": "success",
                "operator_id": operator_id,
                "details": {"target": target},
            })

        return results

    # ------------------------------------------------------------------
    # DNS zone transfer
    # ------------------------------------------------------------------

    def _attempt_zone_transfer(self, target: str) -> Dict[str, Any]:
        """A server permitting AXFR from an arbitrary client is a
        misconfiguration finding in itself. This only lists what a
        properly-configured server would refuse to hand over anyway."""
        try:
            import dns.resolver
            import dns.zone
            import dns.query

            ns_answers = dns.resolver.resolve(target, "NS")
            nameservers = [str(r).rstrip(".") for r in ns_answers]

            transferable = []
            for ns in nameservers:
                try:
                    ns_ip = socket.gethostbyname(ns)
                    zone = dns.zone.from_xfr(dns.query.xfr(ns_ip, target, timeout=10))
                    record_count = len(list(zone.nodes.keys()))
                    transferable.append({"nameserver": ns, "records_exposed": record_count})
                except Exception:
                    continue  # refused -- expected/good outcome, not an error

            return {
                "nameservers_checked": nameservers,
                "vulnerable_to_axfr": transferable,
                "finding": (
                    f"CRITICAL: zone transfer succeeded against {len(transferable)} nameserver(s)"
                    if transferable else "No nameservers allowed unauthenticated zone transfer (expected/secure)"
                ),
            }
        except ImportError:
            return {"error": "dnspython not installed"}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # SMB
    # ------------------------------------------------------------------

    def _enumerate_smb(self, target: str) -> Dict[str, Any]:
        """Lists shares only -- via smbclient -L (list shares, anonymous/guest
        if permitted). Does not attempt to read share contents or brute-force
        credentials."""
        try:
            result = subprocess.run(
                ["smbclient", "-L", target, "-N"],  # -N = no password (anonymous)
                shell=False, capture_output=True, text=True, timeout=30,
            )
            shares = re.findall(r"^\s*(\S+)\s+(Disk|IPC|Printer)\s", result.stdout, re.MULTILINE)
            return {
                "shares_found": [{"name": s[0], "type": s[1]} for s in shares],
                "anonymous_access": len(shares) > 0,
                "raw_stdout": result.stdout[:2000],  # capped, this is diagnostic not a full dump
            }
        except FileNotFoundError:
            return {"error": "smbclient not installed (install samba-client / smbclient package)"}
        except subprocess.TimeoutExpired:
            return {"error": "smb enumeration timed out"}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # SNMP
    # ------------------------------------------------------------------

    def _enumerate_snmp(self, target: str) -> Dict[str, Any]:
        """Read-only SNMP GET against the standard 'public' community string.
        Finding that 'public' works at all is the vulnerability being
        reported -- this doesn't attempt to brute-force other strings."""
        try:
            result = subprocess.run(
                ["snmpget", "-v2c", "-c", "public", "-t", "5", target, "1.3.6.1.2.1.1.1.0"],  # sysDescr
                shell=False, capture_output=True, text=True, timeout=10,
            )
            public_accessible = result.returncode == 0 and "Timeout" not in result.stdout

            return {
                "public_community_accessible": public_accessible,
                "system_description": result.stdout.strip() if public_accessible else None,
                "finding": (
                    "MEDIUM: SNMP 'public' community string is readable -- system information disclosed"
                    if public_accessible else "SNMP 'public' community string not accessible (expected/secure)"
                ),
            }
        except FileNotFoundError:
            return {"error": "snmpget not installed (install net-snmp / snmp-utils package)"}
        except subprocess.TimeoutExpired:
            return {"public_community_accessible": False, "finding": "SNMP request timed out (likely filtered or not responding)"}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # HTTP fingerprinting
    # ------------------------------------------------------------------

    def _fingerprint_http(self, target: str) -> Dict[str, Any]:
        try:
            import requests
            fingerprint = {}
            for scheme in ("https", "http"):
                url = f"{scheme}://{target}"
                try:
                    resp = requests.get(url, timeout=8, allow_redirects=True, verify=False)
                    fingerprint[scheme] = {
                        "status_code": resp.status_code,
                        "server_header": resp.headers.get("Server"),
                        "powered_by": resp.headers.get("X-Powered-By"),
                        "final_url": resp.url,
                        "title": self._extract_title(resp.text),
                    }
                except requests.exceptions.RequestException as e:
                    fingerprint[scheme] = {"error": str(e)}
            return fingerprint
        except ImportError:
            return {"error": "requests library not installed"}

    @staticmethod
    def _extract_title(html: str) -> Optional[str]:
        match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        return match.group(1).strip()[:200] if match else None
