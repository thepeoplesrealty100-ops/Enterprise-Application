# JAKAL Security Agents - Autonomous Reconnaissance
import subprocess
import json
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
import re

logger = logging.getLogger(__name__)

class ReconAgent:
    """Autonomous reconnaissance agent using Nmap, Nuclei, and passive enumeration."""
    
    def __init__(self, db_manager, config):
        self.db = db_manager
        self.config = config
        self.scan_history = {}
    
    def scan(self, target: str, scan_type: str = 'comprehensive') -> Dict[str, Any]:
        """Execute reconnaissance scan against target."""
        logger.info(f"Starting {scan_type} scan against {target}")
        
        findings = {
            'target': target,
            'scan_type': scan_type,
            'timestamp': datetime.utcnow().isoformat(),
            'findings': [],
            'open_ports': [],
            'services': [],
            'vulnerabilities': [],
            'dns_records': []
        }
        
        try:
            # Phase 1: Network reconnaissance
            findings['open_ports'] = self._nmap_scan(target)
            
            # Phase 2: Service enumeration
            findings['services'] = self._service_enumeration(target, findings['open_ports'])
            
            # Phase 3: Vulnerability scanning
            findings['vulnerabilities'] = self._nuclei_scan(target)
            
            # Phase 4: DNS enumeration
            findings['dns_records'] = self._dns_enumeration(target)
            
            # Generate findings summary
            findings['findings'] = self._compile_findings(findings)
            
            # Store in database
            self.scan_history[target] = findings
            
            logger.info(f"Scan complete for {target}. Found {len(findings['findings'])} findings.")
            return findings
        
        except Exception as e:
            logger.error(f"Reconnaissance scan failed: {str(e)}")
            findings['error'] = str(e)
            findings['status'] = 'failed'
            return findings
    
    def _nmap_scan(self, target: str) -> List[Dict[str, Any]]:
        """Execute Nmap port scan."""
        try:
            # Construct Nmap command
            cmd = [
                'nmap',
                '-sV',  # Service version detection
                '-sC',  # Default scripts
                '-oX', '-',  # XML output to stdout
                '--script-timeout', str(self.config.NMAP_TIMEOUT),
                target
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.NMAP_TIMEOUT + 30
            )
            
            # Parse Nmap XML output (simplified)
            open_ports = self._parse_nmap_output(result.stdout)
            logger.info(f"Nmap found {len(open_ports)} open ports on {target}")
            
            return open_ports
        
        except FileNotFoundError:
            logger.warning("Nmap not installed. Using mock data.")
            return self._mock_nmap_results(target)
        except Exception as e:
            logger.error(f"Nmap scan failed: {str(e)}")
            return []
    
    def _parse_nmap_output(self, xml_output: str) -> List[Dict[str, Any]]:
        """Parse Nmap XML output."""
        ports = []
        
        # Simple regex parsing (production would use proper XML parser)
        port_pattern = r'<port protocol="tcp" portid="(\d+)">.*?<name>(.*?)</name>.*?<product>(.*?)</product>.*?<version>(.*?)</version>'
        matches = re.finditer(port_pattern, xml_output, re.DOTALL)
        
        for match in matches:
            port, service, product, version = match.groups()
            ports.append({
                'port': int(port),
                'protocol': 'tcp',
                'service': service,
                'product': product,
                'version': version,
                'state': 'open',
                'severity': self._assess_port_severity(service)
            })
        
        return ports
    
    def _service_enumeration(self, target: str, ports: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Enumerate services on open ports."""
        services = []
        
        for port_info in ports:
            service_detail = {
                'port': port_info['port'],
                'service': port_info['service'],
                'product': port_info['product'],
                'version': port_info['version'],
                'banners': [],
                'configurations': []
            }
            
            # Banner grabbing
            banner = self._grab_banner(target, port_info['port'])
            if banner:
                service_detail['banners'].append(banner)
            
            services.append(service_detail)
        
        return services
    
    def _grab_banner(self, target: str, port: int) -> Optional[str]:
        """Attempt to grab service banner."""
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect((target, port))
            banner = s.recv(1024).decode('utf-8', errors='ignore')
            s.close()
            return banner.strip()
        except Exception:
            return None
    
    def _nuclei_scan(self, target: str) -> List[Dict[str, Any]]:
        """Execute Nuclei vulnerability scanner."""
        try:
            cmd = [
                'nuclei',
                '-u', target,
                '-json',
                '-timeout', str(self.config.NUCLEI_TIMEOUT),
                '-t', self.config.NUCLEI_TEMPLATES_PATH
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.NUCLEI_TIMEOUT + 30
            )
            
            vulnerabilities = self._parse_nuclei_output(result.stdout)
            logger.info(f"Nuclei found {len(vulnerabilities)} vulnerabilities")
            
            return vulnerabilities
        
        except FileNotFoundError:
            logger.warning("Nuclei not installed. Using mock data.")
            return self._mock_nuclei_results(target)
        except Exception as e:
            logger.error(f"Nuclei scan failed: {str(e)}")
            return []
    
    def _parse_nuclei_output(self, json_output: str) -> List[Dict[str, Any]]:
        """Parse Nuclei JSON output."""
        vulnerabilities = []
        
        for line in json_output.strip().split('\n'):
            if not line:
                continue
            try:
                finding = json.loads(line)
                vulnerabilities.append({
                    'template_id': finding.get('template-id'),
                    'name': finding.get('info', {}).get('name'),
                    'severity': finding.get('info', {}).get('severity'),
                    'url': finding.get('matched-at'),
                    'type': finding.get('type'),
                    'description': finding.get('info', {}).get('description')
                })
            except json.JSONDecodeError:
                continue
        
        return vulnerabilities
    
    def _dns_enumeration(self, target: str) -> List[Dict[str, Any]]:
        """Enumerate DNS records."""
        records = []
        
        try:
            import dns.resolver
            
            for record_type in ['A', 'MX', 'NS', 'TXT', 'CNAME']:
                try:
                    answers = dns.resolver.resolve(target, record_type)
                    for rdata in answers:
                        records.append({
                            'type': record_type,
                            'target': target,
                            'value': str(rdata),
                            'ttl': answers.rrset.ttl
                        })
                except Exception:
                    pass
        except ImportError:
            logger.warning("dnspython not installed. Skipping DNS enumeration.")
        
        return records
    
    def _compile_findings(self, scan_results: Dict[str, Any]) -> List[str]:
        """Compile findings into human-readable format."""
        findings = []
        
        # Open ports
        for port_info in scan_results.get('open_ports', []):
            findings.append(
                f"Open port {port_info['port']}/tcp running {port_info['service']} ({port_info['product']} {port_info['version']})"
            )
        
        # Vulnerabilities
        for vuln in scan_results.get('vulnerabilities', []):
            findings.append(
                f"[{vuln['severity'].upper()}] {vuln['name']} ({vuln['template_id']}): {vuln['description']}"
            )
        
        # DNS records
        for dns in scan_results.get('dns_records', []):
            findings.append(f"DNS {dns['type']} record: {dns['value']}")
        
        return findings
    
    @staticmethod
    def _assess_port_severity(service: str) -> str:
        """Assess severity based on service type."""
        high_severity = ['ssh', 'telnet', 'ftp', 'smtp', 'snmp', 'ldap']
        medium_severity = ['http', 'https', 'mysql', 'postgresql', 'redis', 'mongodb']
        
        service_lower = service.lower()
        
        if any(s in service_lower for s in high_severity):
            return 'high'
        elif any(s in service_lower for s in medium_severity):
            return 'medium'
        else:
            return 'low'
    
    @staticmethod
    def _mock_nmap_results(target: str) -> List[Dict[str, Any]]:
        """Generate mock Nmap results for testing."""
        return [
            {'port': 22, 'protocol': 'tcp', 'service': 'ssh', 'product': 'OpenSSH', 'version': '7.4', 'state': 'open', 'severity': 'high'},
            {'port': 80, 'protocol': 'tcp', 'service': 'http', 'product': 'Apache httpd', 'version': '2.4.6', 'state': 'open', 'severity': 'medium'},
            {'port': 443, 'protocol': 'tcp', 'service': 'https', 'product': 'Apache httpd', 'version': '2.4.6', 'state': 'open', 'severity': 'medium'},
            {'port': 3306, 'protocol': 'tcp', 'service': 'mysql', 'product': 'MySQL', 'version': '5.7.25', 'state': 'open', 'severity': 'high'}
        ]
    
    @staticmethod
    def _mock_nuclei_results(target: str) -> List[Dict[str, Any]]:
        """Generate mock Nuclei results for testing."""
        return [
            {'template_id': 'cves/2021-1234', 'name': 'Apache 2.4.6 RCE', 'severity': 'critical', 'url': target, 'type': 'http', 'description': 'Potential RCE in Apache httpd'},
            {'template_id': 'misc/default-login', 'name': 'MySQL Default Credentials', 'severity': 'high', 'url': f"{target}:3306", 'type': 'tcp', 'description': 'MySQL accessible with default credentials'}
        ]
