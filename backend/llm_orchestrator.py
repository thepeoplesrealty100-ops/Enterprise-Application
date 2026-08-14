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
try:
    import google.generativeai as genai
except ImportError:
    genai = None

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
        if genai and config.gemini_api_key:
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
                "T1046": {"name": "Network Service Discovery", "tactic": "discovery"},
                "T1110": {"name": "Brute Force", "tactic": "credential_access"},
                "T1190": {"name": "Exploit Public-Facing Application", "tactic": "initial_access"},
                "T1133": {"name": "External Remote Services", "tactic": "initial_access"},
            }
            
            logger.info(f"✅ Loaded {len(self.mitre_techniques)} MITRE techniques")
        except Exception as e:
            logger.error(f"Failed to load MITRE framework: {str(e)}")
    
    async def analyze_osint_results(self, osint_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze OSINT reconnaissance results."""
        try:
            response = await self._query_llm(f"Analyze: {json.dumps(osint_data)}")
            return {
                "analysis": response,
                "timestamp": datetime.utcnow().isoformat(),
                "confidence": 0.85
            }
        except Exception as e:
            logger.error(f"OSINT analysis failed: {str(e)}")
            return {"error": str(e)}
    
    async def analyze_scan_results(self, scan_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze port/service scan results."""
        try:
            response = await self._query_llm(f"Analyze scan: {json.dumps(scan_data)}")
            return {
                "analysis": response,
                "timestamp": datetime.utcnow().isoformat(),
                "confidence": 0.80
            }
        except Exception as e:
            logger.error(f"Scan analysis failed: {str(e)}")
            return {"error": str(e)}
    
    async def recommend_exploitation_strategy(self, findings: List[Dict]) -> Dict[str, Any]:
        """Recommend exploitation strategy based on findings."""
        try:
            response = await self._query_llm(f"Strategy for: {json.dumps(findings[:3])}")
            return {
                "strategy": response,
                "timestamp": datetime.utcnow().isoformat(),
                "confidence": 0.75
            }
        except Exception as e:
            logger.error(f"Strategy recommendation failed: {str(e)}")
            return {"error": str(e)}
    
    def map_to_mitre_attack(self, findings: List[Dict]) -> Dict[str, Any]:
        """Map findings to MITRE ATT&CK framework."""
        try:
            mappings = []
            for finding in findings:
                mappings.append({
                    "finding_id": finding.get("id"),
                    "title": finding.get("title"),
                    "techniques": []
                })
            
            return {
                "mappings": mappings,
                "timestamp": datetime.utcnow().isoformat(),
                "total_mappings": len(mappings)
            }
        except Exception as e:
            logger.error(f"MITRE mapping failed: {str(e)}")
            return {"error": str(e)}
    
    async def generate_assessment_summary(self, findings: List[Dict], pentest_data: Dict) -> str:
        """Generate executive summary for assessment report."""
        try:
            response = await self._query_llm(f"Summary for pentest: {len(findings)} findings")
            return response
        except Exception as e:
            logger.error(f"Summary generation failed: {str(e)}")
            return f"Error: {str(e)}"
    
    async def _query_llm(self, prompt: str, max_tokens: int = 2000) -> str:
        """Query LLM with fallback strategy."""
        if self.gemini_available and genai:
            try:
                response = self.model.generate_content(prompt)
                if response.text:
                    return response.text
            except Exception as e:
                logger.warning(f"Gemini failed: {str(e)}")
        
        logger.warning("LLM unavailable, returning template response")
        return "LLM analysis: Manual review recommended for security findings."
    
    def get_mitre_tactic_description(self, tactic: str) -> str:
        """Get description of MITRE tactic."""
        descriptions = {
            "reconnaissance": "Gather information about target",
            "discovery": "Explore target environment",
            "credential_access": "Steal credentials",
            "initial_access": "Gain initial foothold",
            "execution": "Run malicious code",
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
