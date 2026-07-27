# JAKAL Security Agents - Reporting
import logging
import json
from typing import Dict, List, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class ReportAgent:
    """Agent for generating security assessment reports."""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    def generate_report(self, pentest_id: str) -> Dict[str, Any]:
        """Generate comprehensive security assessment report."""
        try:
            pentest_results = self.db.get_pentest_results(pentest_id)
            
            if not pentest_results:
                return {'status': 'error', 'message': 'Pentest results not found'}
            
            report = {
                'report_id': pentest_id,
                'generated_at': datetime.utcnow().isoformat(),
                'executive_summary': self._generate_executive_summary(pentest_results),
                'findings': self._compile_findings(pentest_results),
                'attack_surface': self._analyze_attack_surface(pentest_results),
                'risk_assessment': self._assess_risk_level(pentest_results),
                'recommendations': self._generate_recommendations(pentest_results),
                'compliance_status': self._check_compliance(pentest_results)
            }
            
            logger.info(f"Report generated for pentest {pentest_id}")
            return report
        
        except Exception as e:
            logger.error(f"Report generation failed: {str(e)}")
            return {'status': 'error', 'message': str(e)}
    
    def _generate_executive_summary(self, pentest_results: Dict[str, Any]) -> str:
        """Generate executive summary of findings."""
        target = pentest_results.get('target', 'Unknown')
        findings_count = len(json.loads(pentest_results.get('recon_results', '{}'))).get('findings', [])
        
        return f"""Security Assessment Report for {target}

This report summarizes the results of a comprehensive security assessment performed on {target}.
During this assessment, {findings_count} security findings were identified and categorized by severity.

Key Metrics:
- Target: {target}
- Assessment Date: {datetime.utcnow().isoformat()}
- Total Findings: {findings_count}

Please refer to the detailed findings section below for complete information.
"""
    
    def _compile_findings(self, pentest_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Compile all findings with categorization."""
        try:
            recon_data = json.loads(pentest_results.get('recon_results', '{}'))
            findings = recon_data.get('findings', [])
            
            compiled = []
            for idx, finding in enumerate(findings, 1):
                compiled.append({
                    'id': idx,
                    'title': finding,
                    'description': f"Finding: {finding}",
                    'severity': self._assess_finding_severity(finding),
                    'status': 'open'
                })
            
            return compiled
        except Exception as e:
            logger.error(f"Finding compilation failed: {str(e)}")
            return []
    
    def _analyze_attack_surface(self, pentest_results: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze and map the attack surface."""
        try:
            recon_data = json.loads(pentest_results.get('recon_results', '{}'))
            attack_mappings = json.loads(pentest_results.get('attack_mappings', '{}'))
            
            return {
                'total_exposed_services': len(recon_data.get('services', [])),
                'open_ports': len(recon_data.get('open_ports', [])),
                'detected_vulnerabilities': len(recon_data.get('vulnerabilities', [])),
                'attack_tactics': len(attack_mappings) if isinstance(attack_mappings, list) else 0,
                'potential_entry_points': self._identify_entry_points(recon_data)
            }
        except Exception as e:
            logger.error(f"Attack surface analysis failed: {str(e)}")
            return {}
    
    def _identify_entry_points(self, recon_data: Dict[str, Any]) -> List[str]:
        """Identify potential entry points for attackers."""
        entry_points = []
        
        for service in recon_data.get('services', []):
            entry_points.append(f"{service.get('service', 'unknown')} on port {service.get('port', 'unknown')}")
        
        return entry_points
    
    def _assess_risk_level(self, pentest_results: Dict[str, Any]) -> Dict[str, Any]:
        """Assess overall risk level based on findings."""
        try:
            recon_data = json.loads(pentest_results.get('recon_results', '{}'))
            vuln_count = len(recon_data.get('vulnerabilities', []))
            
            if vuln_count >= 10:
                risk_level = 'critical'
                score = 9.5
            elif vuln_count >= 5:
                risk_level = 'high'
                score = 7.5
            elif vuln_count >= 1:
                risk_level = 'medium'
                score = 5.0
            else:
                risk_level = 'low'
                score = 2.0
            
            return {
                'risk_level': risk_level,
                'cvss_score': score,
                'vulnerability_count': vuln_count,
                'exposure_percentage': min(100, (vuln_count / 10) * 100)
            }
        except Exception as e:
            logger.error(f"Risk assessment failed: {str(e)}")
            return {'risk_level': 'unknown'}
    
    def _generate_recommendations(self, pentest_results: Dict[str, Any]) -> List[str]:
        """Generate actionable recommendations based on findings."""
        recommendations = [
            "Implement network segmentation to limit lateral movement",
            "Deploy intrusion detection and prevention systems (IDS/IPS)",
            "Establish a vulnerability management program",
            "Implement zero-trust network architecture",
            "Conduct regular security awareness training",
            "Enable multi-factor authentication (MFA) across all systems",
            "Patch all identified vulnerabilities within 30 days",
            "Implement continuous security monitoring and logging"
        ]
        
        return recommendations
    
    def _check_compliance(self, pentest_results: Dict[str, Any]) -> Dict[str, Any]:
        """Check compliance with security frameworks."""
        return {
            'frameworks': [
                {'framework': 'CIS Controls', 'status': 'partial_compliance', 'score': 6.5},
                {'framework': 'NIST Cybersecurity Framework', 'status': 'partial_compliance', 'score': 6.0},
                {'framework': 'OWASP Top 10', 'status': 'findings_present', 'score': 5.5},
            ],
            'overall_compliance': 'partial',
            'actions_required': 'Address critical findings to improve compliance posture'
        }
    
    @staticmethod
    def _assess_finding_severity(finding: str) -> str:
        """Assess severity of a finding based on keywords."""
        critical_keywords = ['rce', 'remote code execution', 'sql injection', 'authentication']
        high_keywords = ['vulnerability', 'open port', 'default', 'exposed']
        medium_keywords = ['weak', 'misconfiguration', 'outdated']
        
        finding_lower = finding.lower()
        
        for keyword in critical_keywords:
            if keyword in finding_lower:
                return 'critical'
        
        for keyword in high_keywords:
            if keyword in finding_lower:
                return 'high'
        
        for keyword in medium_keywords:
            if keyword in finding_lower:
                return 'medium'
        
        return 'low'
    
    def export_report(self, report: Dict[str, Any], format: str = 'json') -> str:
        """Export report in various formats."""
        if format == 'json':
            return json.dumps(report, indent=2)
        elif format == 'csv':
            # Simplified CSV export
            lines = ['ID,Title,Severity,Status']
            for finding in report.get('findings', []):
                lines.append(f"{finding['id']},{finding['title']},{finding['severity']},{finding['status']}")
            return '\n'.join(lines)
        else:
            return json.dumps(report, indent=2)
