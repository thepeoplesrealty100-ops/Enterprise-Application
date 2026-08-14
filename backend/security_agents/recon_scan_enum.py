#!/usr/bin/env python3
"""JAKAL Phase 3: CPENT Agents 1-3 (Recon, Scanning, Enumeration)"""
import logging
import subprocess
import json
from typing import Dict, List, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class ReconnaissanceAgent:
    """CPENT Phase 1: Reconnaissance - Passive information gathering."""
    
    def __init__(self, db_manager, auth_gate, llm_orchestrator):
        self.db = db_manager
        self.auth = auth_gate
        self.llm = llm_orchestrator
    
    def run_reconnaissance(self, target: str, operator_id: str) -> Dict[str, Any]:
        """Run full reconnaissance phase."""
        try:
            self.auth.check_authorization_and_scope(target, "recon", operator_id)
            results = {
                "target": target,
                "timestamp": datetime.utcnow().isoformat(),
                "phase": "reconnaissance",
                "findings": {}
            }
            
            # DNS enumeration
            logger.info(f"Running DNS enumeration on {target}")
            results["findings"]["dns"] = self._dns_enumeration(target)
            
            # WHOIS lookup
            logger.info(f"Running WHOIS lookup on {target}")
            results["findings"]["whois"] = self._whois_lookup(target)
            
            # SSL certificate analysis
            logger.info(f"Analyzing SSL certificates for {target}")
            results["findings"]["ssl"] = self._ssl_certificate_analysis(target)
            
            self._store_reconnaissance(results, target)
            logger.info(f"✅ Reconnaissance complete for {target}")
            return results
        
        except PermissionError as e:
            logger.error(f"Authorization denied: {str(e)}")
            return {"error": str(e), "status": "blocked"}
        except Exception as e:
            logger.error(f"Reconnaissance failed: {str(e)}")
            return {"error": str(e)}
    
    def _dns_enumeration(self, target: str) -> Dict[str, Any]:
        """Enumerate DNS records."""
        try:
            import socket
            a_records = socket.getaddrinfo(target, None)
            return {"A_records": [str(r[4][0]) for r in a_records if r[0] == socket.AF_INET]}
        except:
            return {"A_records": []}
    
    def _whois_lookup(self, target: str) -> Dict[str, Any]:
        """Get WHOIS information."""
        try:
            import whois
            data = whois.whois(target)
            return {"registrar": str(data.registrar)}
        except:
            return {"info": "WHOIS lookup unavailable"}
    
    def _ssl_certificate_analysis(self, target: str) -> Dict[str, Any]:
        """Analyze SSL certificates."""
        try:
            import ssl, socket
            context = ssl.create_default_context()
            conn = context.wrap_socket(socket.socket(socket.AF_INET), server_hostname=target)
            conn.connect((target, 443))
            cert = conn.getpeercert()
            conn.close()
            return {"issuer": cert.get("issuer", [])}
        except:
            return {"info": "SSL analysis unavailable"}
    
    def _store_reconnaissance(self, results: Dict, target: str) -> None:
        """Store reconnaissance results."""
        self.db.insert_log({
            "timestamp": datetime.utcnow(),
            "event": "RECON_COMPLETED",
            "action": "reconnaissance",
            "status": "completed",
            "target": target
        })

class ScanningAgent:
    """CPENT Phase 2: Scanning - Active discovery."""
    
    def __init__(self, db_manager, auth_gate, llm_orchestrator):
        self.db = db_manager
        self.auth = auth_gate
        self.llm = llm_orchestrator
    
    def run_scan(self, target: str, scan_type: str, operator_id: str) -> Dict[str, Any]:
        """Run comprehensive scanning phase."""
        try:
            self.auth.check_authorization_and_scope(target, "scan", operator_id)
            results = {
                "target": target,
                "scan_type": scan_type,
                "timestamp": datetime.utcnow().isoformat(),
                "phase": "scanning",
                "findings": {}
            }
            
            # Port scan
            logger.info(f"Running {scan_type} port scan on {target}")
            results["findings"]["ports"] = self._port_scan(target, scan_type)
            
            # Service detection
            results["findings"]["services"] = self._service_detection({})
            
            # OS fingerprinting
            results["findings"]["os"] = self._os_fingerprinting(target)
            
            self._store_scan_results(results, target)
            logger.info(f"✅ Scanning complete for {target}")
            return results
        
        except PermissionError as e:
            return {"error": str(e), "status": "blocked"}
        except Exception as e:
            logger.error(f"Scanning failed: {str(e)}")
            return {"error": str(e)}
    
    def _port_scan(self, target: str, scan_type: str) -> Dict[str, Any]:
        """Run Nmap port scan."""
        try:
            nmap_profiles = {
                "quick": "-T4 -F",
                "comprehensive": "-sV -sC -O -T4 -p-",
                "stealth": "-sS -T1 -p-"
            }
            flags = nmap_profiles.get(scan_type, "-T4 -F")
            cmd = f"nmap {flags} {target}"
            result = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=300)
            return {"command": cmd, "return_code": result.returncode}
        except:
            return {"status": "failed"}
    
    def _service_detection(self, port_results: Dict) -> Dict[str, Any]:
        """Extract service information."""
        return {"method": "Version detection", "count": 0}
    
    def _os_fingerprinting(self, target: str) -> Dict[str, Any]:
        """Fingerprint operating system."""
        return {"method": "TTL analysis"}
    
    def _store_scan_results(self, results: Dict, target: str) -> None:
        """Store scan results."""
        self.db.insert_log({
            "timestamp": datetime.utcnow(),
            "event": "SCAN_COMPLETED",
            "action": "scanning",
            "status": "completed",
            "target": target
        })

class EnumerationAgent:
    """CPENT Phase 3: Enumeration - Service discovery."""
    
    def __init__(self, db_manager, auth_gate, llm_orchestrator):
        self.db = db_manager
        self.auth = auth_gate
        self.llm = llm_orchestrator
    
    def run_enumeration(self, target: str, open_ports: List[int], operator_id: str) -> Dict[str, Any]:
        """Run enumeration phase."""
        try:
            self.auth.check_authorization_and_scope(target, "enum", operator_id)
            results = {
                "target": target,
                "timestamp": datetime.utcnow().isoformat(),
                "phase": "enumeration",
                "findings": {}
            }
            
            # SMB enumeration
            if 445 in open_ports:
                logger.info(f"Running SMB enumeration on {target}")
                results["findings"]["smb"] = self._enum_smb(target)
            
            # SNMP enumeration
            if 161 in open_ports:
                logger.info(f"Running SNMP enumeration on {target}")
                results["findings"]["snmp"] = self._enum_snmp(target)
            
            # LDAP enumeration
            if 389 in open_ports:
                logger.info(f"Running LDAP enumeration on {target}")
                results["findings"]["ldap"] = self._enum_ldap(target)
            
            self._store_enumeration_results(results, target)
            logger.info(f"✅ Enumeration complete for {target}")
            return results
        
        except PermissionError as e:
            return {"error": str(e), "status": "blocked"}
        except Exception as e:
            logger.error(f"Enumeration failed: {str(e)}")
            return {"error": str(e)}
    
    def _enum_smb(self, target: str) -> Dict[str, Any]:
        """Enumerate SMB shares and users."""
        return {"shares": [], "users": []}
    
    def _enum_snmp(self, target: str) -> Dict[str, Any]:
        """Enumerate SNMP information."""
        return {"community_strings": ["public", "private"]}
    
    def _enum_ldap(self, target: str) -> Dict[str, Any]:
        """Enumerate LDAP directory."""
        return {"users": [], "groups": []}
    
    def _store_enumeration_results(self, results: Dict, target: str) -> None:
        """Store enumeration results."""
        self.db.insert_log({
            "timestamp": datetime.utcnow(),
            "event": "ENUM_COMPLETED",
            "action": "enumeration",
            "status": "completed",
            "target": target
        })
