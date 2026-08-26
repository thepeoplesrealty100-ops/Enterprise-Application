"""
JAKAL Security Agent - Wireless (802.11 Wi-Fi assessment) — SAFE CHECKS ONLY

Consistent with ReconAgent / EnumAgent / WebAgent: this agent performs
passive-to-low-risk READ-ONLY checks — it enumerates wireless interfaces,
lists nearby networks (SSID/BSSID/security/signal), and flags networks
whose encryption is weak or absent. It never sends deauthentication
frames, never stands up a rogue AP, and never attempts a WPS PIN or
handshake attack — that active tradecraft lives in
`backend/payloads/payload_generator.py`'s `wireless()` phase as
structured, MITRE-tagged command strings for human-reviewed execution
via the VM Orchestrator / a terminal session, exactly like every other
phase in this codebase. This agent answers "what's out there and is it
obviously misconfigured"; the payload generator answers "here is the
authorized command an operator can choose to run next."

`target` is the facility/site identifier being assessed (e.g. an office
name or a client-provided site code) — wireless engagements are scoped
to a physical location, not an IP/domain, but this still runs through
the same check_authorization_and_scope() gate as every other agent so
the engagement is provably in-scope before any interface is touched.
"""

import logging
import re
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from tools.authorization import check_authorization_and_scope

logger = logging.getLogger(__name__)

# Security strings from `nmcli`/`iwlist` output that indicate weak or no
# encryption. WPA3/WPA2 with a real cipher suite is fine; anything that is
# empty, "--", or literally contains WEP is a finding.
_WEAK_SECURITY_MARKERS = ("WEP",)
_OPEN_SECURITY_MARKERS = ("", "--", "none", "open")


class WirelessAgent:
    def __init__(self, db_manager=None, config=None):
        self.db = db_manager
        self.config = config

    def scan(
        self,
        target: str,
        interface: Optional[str] = None,
        operator_id: str = "system",
    ) -> Dict[str, Any]:
        check_authorization_and_scope(target, "wireless_agent_scan", operator_id, db=self.db)

        results: Dict[str, Any] = {
            "phase": "CPENT-Phase-Wireless",
            "target": target,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "interfaces": self._list_interfaces(),
        }
        iface = interface or self._pick_interface(results["interfaces"])
        results["interface_used"] = iface
        results["networks"] = self._passive_scan(iface) if iface else []
        results["findings_summary"] = self._summarize(results["networks"])

        if self.db:
            self.db.insert_log({
                "event": "WIRELESS_SCAN_COMPLETED",
                "action": "wireless_agent_scan",
                "status": "success",
                "operator_id": operator_id,
                "details": {"target": target, "networks_seen": len(results["networks"]),
                             "findings": len(results["findings_summary"])},
            })

        return results

    # ------------------------------------------------------------------
    # Interface enumeration
    # ------------------------------------------------------------------

    def _list_interfaces(self) -> List[Dict[str, Any]]:
        """Enumerate wireless NICs via `iw dev` (preferred) or `iwconfig`."""
        try:
            result = subprocess.run(
                ["iw", "dev"], shell=False, capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                names = re.findall(r"Interface\s+(\S+)", result.stdout)
                return [{"name": n, "source": "iw"} for n in names]
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning("iw dev failed: %s", e)

        try:
            result = subprocess.run(
                ["iwconfig"], shell=False, capture_output=True, text=True, timeout=10,
            )
            names = re.findall(r"^(\S+)\s+IEEE 802\.11", result.stdout, re.MULTILINE)
            return [{"name": n, "source": "iwconfig"} for n in names]
        except FileNotFoundError:
            return []
        except Exception as e:
            logger.warning("iwconfig failed: %s", e)
            return []

    @staticmethod
    def _pick_interface(interfaces: List[Dict[str, Any]]) -> Optional[str]:
        return interfaces[0]["name"] if interfaces else None

    # ------------------------------------------------------------------
    # Passive scan (list nearby networks, no packets sent to any client)
    # ------------------------------------------------------------------

    def _passive_scan(self, iface: str) -> List[Dict[str, Any]]:
        """
        Prefer `nmcli` (NetworkManager) — no root required, structured output.
        Fall back to `iwlist <iface> scan` (usually needs root).
        """
        nets = self._scan_nmcli()
        if nets:
            return nets
        return self._scan_iwlist(iface)

    def _scan_nmcli(self) -> List[Dict[str, Any]]:
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "SSID,BSSID,SECURITY,SIGNAL,CHAN", "device", "wifi", "list"],
                shell=False, capture_output=True, text=True, timeout=20,
            )
            if result.returncode != 0:
                return []
            nets = []
            for line in result.stdout.strip().splitlines():
                # nmcli -t escapes ':' inside BSSID with '\:' — split carefully.
                parts = re.split(r"(?<!\\):", line)
                if len(parts) < 5:
                    continue
                ssid, bssid, security, signal, chan = [p.replace("\\:", ":") for p in parts[:5]]
                nets.append({
                    "ssid": ssid or "(hidden)",
                    "bssid": bssid,
                    "security": security,
                    "signal": signal,
                    "channel": chan,
                    "source": "nmcli",
                })
            return nets
        except FileNotFoundError:
            return []
        except Exception as e:
            logger.warning("nmcli scan failed: %s", e)
            return []

    def _scan_iwlist(self, iface: str) -> List[Dict[str, Any]]:
        try:
            result = subprocess.run(
                ["iwlist", iface, "scan"], shell=False, capture_output=True, text=True, timeout=20,
            )
            if result.returncode != 0:
                return [{"error": result.stderr[:500] or "iwlist scan failed (often requires root)"}]
            nets = []
            cells = result.stdout.split("Cell ")
            for cell in cells[1:]:
                ssid_m = re.search(r'ESSID:"([^"]*)"', cell)
                addr_m = re.search(r"Address:\s*(\S+)", cell)
                enc_m = re.search(r"Encryption key:(on|off)", cell)
                wpa = "WPA" if "WPA" in cell else ("WEP" if enc_m and enc_m.group(1) == "on" and "WPA" not in cell else "")
                nets.append({
                    "ssid": ssid_m.group(1) if ssid_m else "(hidden)",
                    "bssid": addr_m.group(1) if addr_m else None,
                    "security": wpa if enc_m and enc_m.group(1) == "on" else "",
                    "signal": None,
                    "channel": None,
                    "source": "iwlist",
                })
            return nets
        except FileNotFoundError:
            return [{"error": "neither nmcli nor iwlist installed/available"}]
        except subprocess.TimeoutExpired:
            return [{"error": "iwlist scan timed out"}]
        except Exception as e:
            return [{"error": str(e)}]

    # ------------------------------------------------------------------
    # Findings
    # ------------------------------------------------------------------

    @staticmethod
    def _summarize(networks: List[Dict[str, Any]]) -> List[str]:
        findings = []
        for n in networks:
            if "error" in n:
                continue
            sec = (n.get("security") or "").upper()
            ssid = n.get("ssid", "?")
            if any(m in sec for m in _WEAK_SECURITY_MARKERS):
                findings.append(f"[HIGH] Network '{ssid}' ({n.get('bssid')}) uses WEP — trivially crackable")
            elif sec.strip().lower() in _OPEN_SECURITY_MARKERS:
                findings.append(f"[MEDIUM] Network '{ssid}' ({n.get('bssid')}) is open / unencrypted")
        return findings
