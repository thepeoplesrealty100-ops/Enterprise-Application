"""
JAKAL Security Agent - Reconnaissance (CPENT Phase 1)

FIXES vs. the version currently in the repo:
1. Now actually calls the authorization/scope gate before touching a target
   (the committed version never did -- it would happily scan anything).
2. Nmap output is parsed with xml.etree.ElementTree instead of a regex.
   The regex (`<port ...>.*?<name>...` with re.DOTALL across the whole
   document) breaks the moment a host has more than one port block, or a
   product/version field is empty -- both are the common case, not the
   exception. XML parsing handles nested/optional fields correctly.
3. Nuclei is invoked with `-jsonl` (current flag) instead of `-json`,
   which newer Nuclei releases deprecated in favor of `-jsonl`.
4. Mock/demo data is clearly labeled as such in the returned dict so it's
   never mistaken for a real finding downstream (report generation, etc.)
"""

import json
import logging
import socket
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from tools.authorization import check_authorization_and_scope

logger = logging.getLogger(__name__)


class ReconAgent:
    """Reconnaissance agent using Nmap, Nuclei, and passive DNS enumeration."""

    def __init__(self, db_manager=None, config=None):
        self.db = db_manager
        self.config = config
        self.scan_history: Dict[str, Any] = {}

    def scan(
        self,
        target: str,
        scan_type: str = "comprehensive",
        operator_id: str = "system",
    ) -> Dict[str, Any]:
        check_authorization_and_scope(target, "recon_agent_scan", operator_id, db=self.db)

        logger.info(f"Starting {scan_type} recon against {target}")

        findings: Dict[str, Any] = {
            "target": target,
            "scan_type": scan_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "findings": [],
            "open_ports": [],
            "services": [],
            "vulnerabilities": [],
            "dns_records": [],
        }

        try:
            findings["open_ports"] = self._nmap_scan(target)
            findings["services"] = self._service_enumeration(target, findings["open_ports"])
            findings["vulnerabilities"] = self._nuclei_scan(target)
            findings["dns_records"] = self._dns_enumeration(target)
            findings["findings"] = self._compile_findings(findings)

            self.scan_history[target] = findings
            if self.db:
                self.db.insert_log({
                    "event": "RECON_COMPLETED",
                    "action": f"recon_{scan_type}",
                    "status": "success",
                    "operator_id": operator_id,
                    "details": {"target": target, "findings_count": len(findings["findings"])},
                })

            logger.info(f"Recon complete for {target}: {len(findings['findings'])} findings")
            return findings

        except Exception as e:
            logger.error(f"Reconnaissance scan failed: {e}")
            findings["error"] = str(e)
            findings["status"] = "failed"
            return findings

    # ------------------------------------------------------------------
    # Nmap
    # ------------------------------------------------------------------

    def _nmap_scan(self, target: str) -> List[Dict[str, Any]]:
        timeout = getattr(self.config, "NMAP_TIMEOUT", 120) if self.config else 120
        cmd = ["nmap", "-sV", "-sC", "-oX", "-", target]

        try:
            result = subprocess.run(
                cmd, shell=False, capture_output=True, text=True, timeout=timeout + 30
            )
            open_ports = self._parse_nmap_xml(result.stdout)
            logger.info(f"Nmap found {len(open_ports)} open ports on {target}")
            return open_ports
        except FileNotFoundError:
            logger.warning("nmap not installed -- returning clearly-labeled demo data")
            return self._demo_nmap_results(target)
        except subprocess.TimeoutExpired:
            logger.warning(f"nmap timed out against {target}")
            return []
        except Exception as e:
            logger.error(f"Nmap scan failed: {e}")
            return []

    @staticmethod
    def _parse_nmap_xml(xml_output: str) -> List[Dict[str, Any]]:
        """Real XML parsing. Handles missing product/version fields correctly,
        which the previous regex-based parser silently dropped or mis-matched."""
        ports: List[Dict[str, Any]] = []
        if not xml_output.strip():
            return ports

        try:
            root = ET.fromstring(xml_output)
        except ET.ParseError as e:
            logger.warning(f"Could not parse nmap XML: {e}")
            return ports

        for host in root.findall("host"):
            for port_el in host.findall("./ports/port"):
                state_el = port_el.find("state")
                if state_el is None or state_el.get("state") != "open":
                    continue

                service_el = port_el.find("service")
                service = service_el.get("name", "unknown") if service_el is not None else "unknown"
                product = service_el.get("product", "") if service_el is not None else ""
                version = service_el.get("version", "") if service_el is not None else ""

                ports.append({
                    "port": int(port_el.get("portid")),
                    "protocol": port_el.get("protocol", "tcp"),
                    "service": service,
                    "product": product,
                    "version": version,
                    "state": "open",
                    "severity": ReconAgent._assess_port_severity(service),
                })

        return ports

    # ------------------------------------------------------------------
    # Service enumeration / banner grabbing
    # ------------------------------------------------------------------

    def _service_enumeration(self, target: str, ports: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        services = []
        for port_info in ports:
            detail = {
                "port": port_info["port"],
                "service": port_info["service"],
                "product": port_info["product"],
                "version": port_info["version"],
                "banners": [],
            }
            banner = self._grab_banner(target, port_info["port"])
            if banner:
                detail["banners"].append(banner)
            services.append(detail)
        return services

    @staticmethod
    def _grab_banner(target: str, port: int) -> Optional[str]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect((target, port))
                banner = s.recv(1024).decode("utf-8", errors="ignore")
                return banner.strip() or None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Nuclei
    # ------------------------------------------------------------------

    def _nuclei_scan(self, target: str) -> List[Dict[str, Any]]:
        timeout = getattr(self.config, "NUCLEI_TIMEOUT", 120) if self.config else 120
        templates_path = getattr(self.config, "NUCLEI_TEMPLATES_PATH", None) if self.config else None

        cmd = ["nuclei", "-u", target, "-jsonl", "-timeout", str(timeout)]
        if templates_path:
            cmd.extend(["-t", templates_path])

        try:
            result = subprocess.run(
                cmd, shell=False, capture_output=True, text=True, timeout=timeout + 30
            )
            vulns = self._parse_nuclei_jsonl(result.stdout)
            logger.info(f"Nuclei found {len(vulns)} findings on {target}")
            return vulns
        except FileNotFoundError:
            logger.warning("nuclei not installed -- returning clearly-labeled demo data")
            return self._demo_nuclei_results(target)
        except subprocess.TimeoutExpired:
            logger.warning(f"nuclei timed out against {target}")
            return []
        except Exception as e:
            logger.error(f"Nuclei scan failed: {e}")
            return []

    @staticmethod
    def _parse_nuclei_jsonl(jsonl_output: str) -> List[Dict[str, Any]]:
        vulnerabilities = []
        for line in jsonl_output.strip().split("\n"):
            if not line:
                continue
            try:
                finding = json.loads(line)
            except json.JSONDecodeError:
                continue
            info = finding.get("info", {})
            vulnerabilities.append({
                "template_id": finding.get("template-id"),
                "name": info.get("name"),
                "severity": info.get("severity"),
                "url": finding.get("matched-at"),
                "type": finding.get("type"),
                "description": info.get("description"),
            })
        return vulnerabilities

    # ------------------------------------------------------------------
    # DNS
    # ------------------------------------------------------------------

    def _dns_enumeration(self, target: str) -> List[Dict[str, Any]]:
        records = []
        try:
            import dns.resolver
            for record_type in ["A", "MX", "NS", "TXT", "CNAME"]:
                try:
                    answers = dns.resolver.resolve(target, record_type)
                    for rdata in answers:
                        records.append({
                            "type": record_type,
                            "target": target,
                            "value": str(rdata),
                            "ttl": answers.rrset.ttl,
                        })
                except Exception:
                    pass
        except ImportError:
            logger.warning("dnspython not installed; skipping DNS enumeration")
        return records

    # ------------------------------------------------------------------
    # Compilation / helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compile_findings(scan_results: Dict[str, Any]) -> List[str]:
        findings = []
        for p in scan_results.get("open_ports", []):
            desc = f"{p['product']} {p['version']}".strip()
            findings.append(f"Open port {p['port']}/{p['protocol']} running {p['service']}" + (f" ({desc})" if desc else ""))
        for v in scan_results.get("vulnerabilities", []):
            sev = (v.get("severity") or "unknown").upper()
            findings.append(f"[{sev}] {v.get('name')} ({v.get('template_id')}): {v.get('description')}")
        for d in scan_results.get("dns_records", []):
            findings.append(f"DNS {d['type']} record: {d['value']}")
        return findings

    @staticmethod
    def _assess_port_severity(service: str) -> str:
        high = {"ssh", "telnet", "ftp", "smtp", "snmp", "ldap"}
        medium = {"http", "https", "mysql", "postgresql", "redis", "mongodb"}
        s = service.lower()
        if any(x in s for x in high):
            return "high"
        if any(x in s for x in medium):
            return "medium"
        return "low"

    @staticmethod
    def _demo_nmap_results(target: str) -> List[Dict[str, Any]]:
        """Clearly-labeled demo data, used only when nmap isn't installed."""
        return [
            {"port": 22, "protocol": "tcp", "service": "ssh", "product": "OpenSSH", "version": "9.x", "state": "open", "severity": "high", "demo_data": True},
            {"port": 80, "protocol": "tcp", "service": "http", "product": "nginx", "version": "1.25", "state": "open", "severity": "medium", "demo_data": True},
        ]

    @staticmethod
    def _demo_nuclei_results(target: str) -> List[Dict[str, Any]]:
        return [
            {"template_id": "demo/example-finding", "name": "[DEMO DATA] Nuclei not installed", "severity": "info", "url": target, "type": "http", "description": "Install nuclei to get real findings."}
        ]
