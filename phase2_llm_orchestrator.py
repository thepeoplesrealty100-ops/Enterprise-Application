#!/usr/bin/env python3
"""
JAKAL Phase 2: LLM Orchestrator
Google Gemini 1.5 Flash integration with local Ollama fallback
"""

import logging
import json
import aiohttp
from typing import Dict, List, Optional, Any
from datetime import datetime
import google.generativeai as genai
from functools import lru_cache

logger = logging.getLogger(__name__)

class LLMOrchestrator:
    """
    Orchestrates LLM reasoning for autonomous agents.
    Primary: Google Gemini 1.5 Flash API
    Fallback: Local Ollama (llama2/qwen)
    """
    
    def __init__(self, config):
        self.config = config
        self.gemini_available = False
        self.ollama_available = False
        self.mitre_techniques = {}
        self.mitre_tactics = {}
        
        # Initialize Gemini if key available
        if config.gemini_api_key:
            try:
                genai.configure(api_key=config.gemini_api_key)
                self.model = genai.GenerativeModel(config.gemini_model)
                self.gemini_available = True
                logger.info("✅ Gemini API initialized")
            except Exception as e:
                logger.warning(f"Gemini initialization failed: {str(e)}")
                self.gemini_available = False
        
        # Check for Ollama
        self._check_ollama_availability()
        
        # Load MITRE ATT&CK framework
        self._load_mitre_framework()
    
    def _check_ollama_availability(self) -> None:
        """Check if Ollama is running locally."""
        try:
            import requests
            response = requests.get(f"{self.config.ollama_base_url}/api/tags", timeout=2)
            if response.status_code == 200:
                self.ollama_available = True
                logger.info("✅ Ollama local LLM available")
        except Exception as e:
            logger.debug(f"Ollama not available: {str(e)}")
            self.ollama_available = False
    
    def _load_mitre_framework(self) -> None:
        """Load MITRE ATT&CK framework data."""
        try:
            # Simplified MITRE framework (full version would fetch from official JSON)
            self.mitre_tactics = {
                "reconnaissance": "T1590-T1598",
                "resource_development": "T1583-T1583",
                "initial_access": "T1189-T1200",
                "execution": "T1059-T1204",
                "persistence": "T1098-T1547",
                "privilege_escalation": "T1134-T1548",
                "defense_evasion": "T1548-T1562",
                "credential_access": "T1110-T1187",
                "discovery": "T1087-T1526",
                "lateral_movement": "T1210-T1570",
                "collection": "T1123-T1557",
                "command_and_control": "T1071-T1205",
                "exfiltration": "T1020-T1567",
                "impact": "T1531-T1561"
            }
            
            self.mitre_techniques = {
                "T1595": {"name": "Active Scanning", "tactic": "reconnaissance"},
                "T1592": {"name": "Gather Victim Host Information", "tactic": "reconnaissance"},
                "T1589": {"name": "Gather Victim Identity Information", "tactic": "reconnaissance"},
                "T1590": {"name": "Gather Victim Network Information", "tactic": "reconnaissance"},
                "T1598": {"name": "Phishing for Information", "tactic": "reconnaissance"},
                "T1040": {"name": "Network Sniffing", "tactic": "discovery"},
                "T1046": {"name": "Network Service Discovery", "tactic": "discovery"},
                "T1135": {"name": "Network Share Discovery", "tactic": "discovery"},
                "T1087": {"name": "Account Discovery", "tactic": "discovery"},
                "T1526": {"name": "Cloud Service Discovery", "tactic": "discovery"},
                "T1110": {"name": "Brute Force", "tactic": "credential_access"},
                "T1187": {"name": "Forced Authentication", "tactic": "credential_access"},
                "T1081": {"name": "Credentials in Files", "tactic": "credential_access"},
                "T1111": {"name": "Multi-Factor Authentication Interception", "tactic": "credential_access"},
                "T1589": {"name": "Gather Victim Identity Information", "tactic": "reconnaissance"},
                "T1566": {"name": "Phishing", "tactic": "initial_access"},
                "T1199": {"name": "Trusted Relationship", "tactic": "initial_access"},
                "T1200": {"name": "Hardware Additions", "tactic": "initial_access"},
                "T1190": {"name": "Exploit Public-Facing Application", "tactic": "initial_access"},
                "T1133": {"name": "External Remote Services", "tactic": "initial_access"},
            }
            
            logger.info(f"✅ Loaded {len(self.mitre_techniques)} MITRE techniques")
        except Exception as e:
            logger.error(f"Failed to load MITRE framework: {str(e)}")
    
    async def analyze_osint_results(self, osint_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze OSINT reconnaissance results.
        Identifies interesting patterns, potential vulnerabilities, next steps.
        """
        try:
            prompt = f"""
            Analyze these OSINT reconnaissance results and provide security insights:
            
            OSINT Data:
            {json.dumps(osint_data, indent=2)}
            
            Provide:
            1. Key findings (what's exposed/interesting)
            2. Risk assessment (low/medium/high)
            3. Recommended next steps
            4. Potential attack vectors
            5. MITRE ATT&CK techniques applicable
            
            Be concise and actionable.
            """
            
            response = await self._query_llm(prompt)
            
            logger.info(f"OSINT analysis complete: {osint_data.get('target', 'unknown')}")
            return {
                "analysis": response,
                "timestamp": datetime.utcnow().isoformat(),
                "confidence": 0.85
            }
        except Exception as e:
            logger.error(f"OSINT analysis failed: {str(e)}")
            return {"error": str(e)}
    
    async def analyze_scan_results(self, scan_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze port/service scan results.
        Identifies vulnerable services, misconfigurations, exploitation opportunities.
        """
        try:
            prompt = f"""
            Analyze these network scan results:
            
            Scan Data:
            {json.dumps(scan_data, indent=2)}
            
            Provide:
            1. Open ports and services identified
            2. Known vulnerabilities for detected services
            3. Exploitation difficulty ranking
            4. Recommended testing sequence
            5. MITRE ATT&CK techniques applicable
            
            Be specific with version numbers and CVE references if known.
            """
            
            response = await self._query_llm(prompt)
            
            logger.info(f"Scan analysis complete for {scan_data.get('target', 'unknown')}")
            return {
                "analysis": response,
                "timestamp": datetime.utcnow().isoformat(),
                "confidence": 0.80
            }
        except Exception as e:
            logger.error(f"Scan analysis failed: {str(e)}")
            return {"error": str(e)}
    
    async def recommend_exploitation_strategy(self, findings: List[Dict]) -> Dict[str, Any]:
        """
        Recommend exploitation strategy based on findings.
        Orders exploits by success probability, suggests payloads.
        """
        try:
            prompt = f"""
            Based on these security findings, recommend an exploitation strategy:
            
            Findings:
            {json.dumps(findings, indent=2)}
            
            Provide:
            1. Exploitation priority order (highest success probability first)
            2. Recommended payload types for each target
            3. Expected difficulty (easy/medium/hard/expert)
            4. Chaining exploits for lateral movement
            5. Post-exploitation objectives
            6. Defensive measures to watch for
            
            Be tactical and realistic about success rates.
            """
            
            response = await self._query_llm(prompt)
            
            logger.info(f"Exploitation strategy recommended for {len(findings)} findings")
            return {
                "strategy": response,
                "timestamp": datetime.utcnow().isoformat(),
                "confidence": 0.75
            }
        except Exception as e:
            logger.error(f"Strategy recommendation failed: {str(e)}")
            return {"error": str(e)}
    
    def map_to_mitre_attack(self, findings: List[Dict]) -> Dict[str, Any]:
        """
        Map findings to MITRE ATT&CK framework.
        Identifies tactics and techniques applicable to each finding.
        """
        try:
            mappings = []
            
            for finding in findings:
                title = finding.get("title", "").lower()
                description = finding.get("description", "").lower()
                
                # Simple keyword-based mapping (production would use ML)
                matched_techniques = []
                
                for technique_id, technique_info in self.mitre_techniques.items():
                    technique_name = technique_info["name"].lower()
                    
                    if any(keyword in title or keyword in description 
                           for keyword in technique_name.split()):
                        matched_techniques.append({
                            "technique_id": technique_id,
                            "technique_name": technique_info["name"],
                            "tactic": technique_info["tactic"],
                            "confidence": 0.70
                        })
                
                mappings.append({
                    "finding_id": finding.get("id"),
                    "title": finding.get("title"),
                    "techniques": matched_techniques
                })
            
            logger.info(f"Mapped {len(findings)} findings to {len(self.mitre_techniques)} techniques")
            return {
                "mappings": mappings,
                "timestamp": datetime.utcnow().isoformat(),
                "total_mappings": len(mappings)
            }
        except Exception as e:
            logger.error(f"MITRE mapping failed: {str(e)}")
            return {"error": str(e)}
    
    async def generate_assessment_summary(self, findings: List[Dict], pentest_data: Dict) -> str:
        """
        Generate executive summary for assessment report.
        High-level overview of findings, risk, and recommendations.
        """
        try:
            prompt = f"""
            Generate an executive summary (2-3 paragraphs) for a penetration test report:
            
            Test Target: {pentest_data.get('target')}
            Test Date: {pentest_data.get('date')}
            Test Scope: {pentest_data.get('scope')}
            
            Findings Summary:
            - Critical: {len([f for f in findings if f.get('severity') == 'CRITICAL'])}
            - High: {len([f for f in findings if f.get('severity') == 'HIGH'])}
            - Medium: {len([f for f in findings if f.get('severity') == 'MEDIUM'])}
            - Low: {len([f for f in findings if f.get('severity') == 'LOW'])}
            
            Top 3 Findings:
            {json.dumps(findings[:3], indent=2)}
            
            Write a professional executive summary suitable for C-level stakeholders.
            Include: overall risk level, key findings, business impact, recommended actions.
            """
            
            response = await self._query_llm(prompt)
            
            logger.info("Assessment summary generated")
            return response
        except Exception as e:
            logger.error(f"Summary generation failed: {str(e)}")
            return f"Error generating summary: {str(e)}"
    
    async def _query_llm(self, prompt: str, max_tokens: int = 2000) -> str:
        """
        Query LLM with fallback strategy.
        Primary: Gemini API
        Fallback: Local Ollama
        """
        # Try Gemini first
        if self.gemini_available:
            try:
                response = self.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        max_output_tokens=max_tokens,
                        temperature=0.3,
                    ),
                    safety_settings=[
                        {
                            "category": genai.types.HarmCategory.HARM_CATEGORY_UNSPECIFIED,
                            "threshold": genai.types.HarmBlockThreshold.BLOCK_NONE,
                        },
                    ]
                )
                
                if response.text:
                    logger.debug("LLM response from Gemini API")
                    return response.text
            except Exception as e:
                logger.warning(f"Gemini query failed, trying Ollama: {str(e)}")
        
        # Fallback to Ollama
        if self.config.enable_local_llm and self.ollama_available:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{self.config.ollama_base_url}/api/generate",
                        json={
                            "model": self.config.ollama_model,
                            "prompt": prompt,
                            "stream": False,
                            "temperature": 0.3,
                        },
                        timeout=aiohttp.ClientTimeout(total=60)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            logger.debug("LLM response from Ollama")
                            return data.get("response", "No response")
            except Exception as e:
                logger.error(f"Ollama query failed: {str(e)}")
        
        # Fallback response if both fail
        logger.warning("All LLM providers unavailable, returning template response")
        return "LLM analysis unavailable - using template analysis.\n\n" + \
               "Recommendation: Review findings manually and correlate with known vulnerabilities."
    
    def get_mitre_tactic_description(self, tactic: str) -> str:
        """Get description of MITRE tactic."""
        descriptions = {
            "reconnaissance": "Techniques used to gather information about the target",
            "resource_development": "Techniques used to obtain resources for attack",
            "initial_access": "Techniques used to gain initial foothold",
            "execution": "Techniques used to run malicious code",
            "persistence": "Techniques used to maintain access",
            "privilege_escalation": "Techniques used to gain higher privileges",
            "defense_evasion": "Techniques used to evade detection",
            "credential_access": "Techniques used to steal credentials",
            "discovery": "Techniques used to explore target environment",
            "lateral_movement": "Techniques used to move within network",
            "collection": "Techniques used to gather data",
            "command_and_control": "Techniques used to communicate with compromised systems",
            "exfiltration": "Techniques used to steal data",
            "impact": "Techniques used to damage systems/data"
        }
        return descriptions.get(tactic.lower(), "Unknown tactic")
    
    def get_technique_info(self, technique_id: str) -> Optional[Dict]:
        """Get detailed info about a MITRE technique."""
        return self.mitre_techniques.get(technique_id)
    
    @property
    def available_providers(self) -> List[str]:
        """List available LLM providers."""
        providers = []
        if self.gemini_available:
            providers.append("gemini")
        if self.ollama_available:
            providers.append("ollama")
        if not providers:
            providers.append("template")
        return providers
    
    def health_check(self) -> Dict[str, bool]:
        """Check health of LLM providers."""
        return {
            "gemini": self.gemini_available,
            "ollama": self.ollama_available,
            "mitre_framework": len(self.mitre_techniques) > 0,
            "overall": self.gemini_available or self.ollama_available
        }
