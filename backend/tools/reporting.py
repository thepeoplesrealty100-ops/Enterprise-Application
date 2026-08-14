#!/usr/bin/env python3
"""Assessment & Reporting Module - Generate professional pen-test reports"""

from datetime import datetime
from typing import List, Dict, Optional
import json
import logging

logger = logging.getLogger(__name__)

class AssessmentReport:
    """Generate professional assessment reports"""
    
    def __init__(self, pentest_id: int, db_manager):
        self.pentest_id = pentest_id
        self.db = db_manager
        self.report_date = datetime.utcnow()
    
    def generate_technical_report(self) -> Dict:
        """Generate technical detailed report"""
        pentest = self.db.query_one("""
            SELECT test_id, target, scan_type, status FROM pentest_runs WHERE id = ?
        """, (self.pentest_id,))
        
        findings = self.db.query("""
            SELECT id, title, severity, cvss_score, description, remediation
            FROM findings WHERE pentest_id = ?
            ORDER BY cvss_score DESC
        """, (self.pentest_id,))
        
        severity_breakdown = self._calculate_severity_breakdown(findings)
        
        return {
            "report_type": "technical",
            "title": "Technical Penetration Test Report",
            "test_id": pentest[0] if pentest else None,
            "target": pentest[1] if pentest else None,
            "report_date": self.report_date.isoformat(),
            "findings_count": len(findings) if findings else 0,
            "severity_breakdown": severity_breakdown,
            "findings": self._format_findings(findings),
            "recommendations": self._generate_recommendations(findings)
        }
    
    def generate_executive_summary(self) -> Dict:
        """Generate executive summary for management"""
        pentest = self.db.query_one("""
            SELECT test_id, target, scan_type FROM pentest_runs WHERE id = ?
        """, (self.pentest_id,))
        
        findings = self.db.query("""
            SELECT severity, COUNT(*) as count FROM findings
            WHERE pentest_id = ? GROUP BY severity
        """, (self.pentest_id,))
        
        severity_map = {row[0]: row[1] for row in findings} if findings else {}
        
        risk_level = self._calculate_risk_level(severity_map)
        
        return {
            "report_type": "executive",
            "title": "Executive Summary - Penetration Test Results",
            "target": pentest[1] if pentest else None,
            "report_date": self.report_date.isoformat(),
            "risk_level": risk_level,
            "findings_summary": {
                "critical": severity_map.get("CRITICAL", 0),
                "high": severity_map.get("HIGH", 0),
                "medium": severity_map.get("MEDIUM", 0),
                "low": severity_map.get("LOW", 0),
                "informational": severity_map.get("INFO", 0)
            },
            "total_findings": sum(severity_map.values()),
            "key_recommendations": self._generate_executive_recommendations(severity_map)
        }
    
    def generate_rfp_response(self, client_name: str, scope: str) -> Dict:
        """Generate RFP response document"""
        return {
            "document_type": "rfp_response",
            "client_name": client_name,
            "response_date": self.report_date.isoformat(),
            "methodology": {
                "phases": [
                    "Reconnaissance",
                    "Scanning & Enumeration",
                    "Vulnerability Assessment",
                    "Exploitation",
                    "Post-Exploitation",
                    "Reporting"
                ],
                "framework": "OWASP Top 10 & MITRE ATT&CK",
                "tools": ["Nmap", "Nikto", "Burp Suite", "Metasploit", "SQLMap"]
            },
            "timeline": {
                "phase_1_recon": "1-2 days",
                "phase_2_scanning": "2-3 days",
                "phase_3_exploitation": "3-5 days",
                "phase_4_reporting": "2-3 days",
                "total": "8-13 days"
            },
            "pricing": {
                "internal_network": "$3,000-5,000",
                "web_application": "$5,000-8,000",
                "comprehensive": "$8,000-12,000"
            },
            "insurance": "Professional Liability: $2,000,000",
            "qualifications": [
                "OSCP Certified",
                "15+ years security experience",
                "MITRE ATT&CK Expert",
                "Quantum-Resistant Encryption Support"
            ]
        }
    
    def _calculate_severity_breakdown(self, findings: List) -> Dict:
        """Calculate severity distribution"""
        breakdown = {
            "CRITICAL": 0,
            "HIGH": 0,
            "MEDIUM": 0,
            "LOW": 0,
            "INFO": 0
        }
        
        for finding in findings or []:
            severity = finding[2]  # severity column
            if severity in breakdown:
                breakdown[severity] += 1
        
        return breakdown
    
    def _calculate_risk_level(self, severity_map: Dict) -> str:
        """Calculate overall risk level"""
        if severity_map.get("CRITICAL", 0) > 0:
            return "CRITICAL"
        elif severity_map.get("HIGH", 0) > 3:
            return "HIGH"
        elif severity_map.get("HIGH", 0) > 0 or severity_map.get("MEDIUM", 0) > 5:
            return "MEDIUM"
        else:
            return "LOW"
    
    def _format_findings(self, findings: List) -> List[Dict]:
        """Format findings for report"""
        result = []
        for finding in findings or []:
            result.append({
                "title": finding[1],
                "severity": finding[2],
                "cvss_score": float(finding[3]) if finding[3] else None,
                "description": finding[4],
                "remediation": finding[5]
            })
        return result
    
    def _generate_recommendations(self, findings: List) -> List[str]:
        """Generate technical recommendations"""
        recommendations = [
            "Implement Web Application Firewall (WAF)",
            "Enable Multi-Factor Authentication (MFA)",
            "Keep systems and software patched",
            "Implement network segmentation",
            "Deploy intrusion detection systems",
            "Conduct regular security awareness training",
            "Implement security information & event management (SIEM)"
        ]
        
        # Add specific recommendations based on findings
        if findings:
            findings_titles = [f[1].lower() for f in findings]
            if any("sql" in t for t in findings_titles):
                recommendations.insert(0, "Implement parameterized queries and input validation")
            if any("xss" in t for t in findings_titles):
                recommendations.insert(0, "Enable Content Security Policy (CSP) headers")
        
        return recommendations
    
    def _generate_executive_recommendations(self, severity_map: Dict) -> List[str]:
        """Generate executive-level recommendations"""
        recommendations = []
        
        if severity_map.get("CRITICAL", 0) > 0:
            recommendations.append("Immediate action required to address critical vulnerabilities")
        
        if severity_map.get("HIGH", 0) > 0:
            recommendations.append("Remediate high-severity findings within 30 days")
        
        if severity_map.get("MEDIUM", 0) > 0:
            recommendations.append("Schedule medium-severity fixes within 60 days")
        
        recommendations.extend([
            "Implement continuous security monitoring",
            "Establish incident response procedures",
            "Schedule regular penetration tests (annually recommended)"
        ])
        
        return recommendations

class RFPGenerator:
    """Generate RFP responses for new business"""
    
    @staticmethod
    def generate_proposal(client_name: str, service_type: str, duration_days: int) -> Dict:
        """Generate a complete proposal"""
        pricing_matrix = {
            "internal_network": 5000,
            "web_application": 7000,
            "mobile_application": 8000,
            "cloud_infrastructure": 10000,
            "comprehensive": 12000
        }
        
        return {
            "proposal_type": "penetration_testing",
            "client_name": client_name,
            "service_type": service_type,
            "proposal_date": datetime.utcnow().isoformat(),
            "duration_days": duration_days,
            "cost": pricing_matrix.get(service_type, 8000),
            "payment_terms": "50% upfront, 50% upon completion",
            "scope": {
                "included": [
                    "Full penetration test",
                    "Detailed reporting",
                    "Remediation consultation",
                    "30-day re-test discount (50%)"
                ],
                "excluded": [
                    "Social engineering",
                    "Physical testing",
                    "Denial of Service testing"
                ]
            },
            "timeline": f"{duration_days} business days",
            "deliverables": [
                "Technical report",
                "Executive summary",
                "Remediation roadmap",
                "CVE/CWE mapping"
            ]
        }
