# JAKAL LLM Orchestrator - Agentic AI Decision Engine
import asyncio
import json
from typing import Dict, List, Any, Optional
import logging
import requests
from datetime import datetime

try:
    import anthropic
except ImportError:
    anthropic = None

logger = logging.getLogger(__name__)

class AgentOrchestrator:
    """Orchestrates agentic AI workflows using LLM for decision-making."""
    
    def __init__(self, config):
        self.config = config
        self.mitre_tactics = {}
        self.mitre_techniques = {}
        self.tool_registry = {}
        self.initialize_llm()
        self.load_mitre_database()
    
    def initialize_llm(self):
        """Initialize LLM engine (Claude or Ollama)."""
        if self.config.LLM_ENGINE == 'claude':
            if not anthropic:
                raise ImportError("anthropic not installed. Install: pip install anthropic")
            self.client = anthropic.Anthropic(api_key=self.config.CLAUDE_API_KEY)
            logger.info(f"Initialized Claude LLM: {self.config.CLAUDE_MODEL}")
        else:
            # Ollama fallback
            logger.info(f"Using Ollama LLM: {self.config.OLLAMA_MODEL}")
    
    def load_mitre_database(self):
        """Load MITRE ATT&CK framework mapping."""
        try:
            # Enterprise tactics
            self.mitre_tactics = {
                'reconnaissance': 'TA0043',
                'resource_development': 'TA0042',
                'initial_access': 'TA0001',
                'execution': 'TA0002',
                'persistence': 'TA0003',
                'privilege_escalation': 'TA0004',
                'defense_evasion': 'TA0005',
                'credential_access': 'TA0006',
                'discovery': 'TA0007',
                'lateral_movement': 'TA0008',
                'collection': 'TA0009',
                'command_control': 'TA0011',
                'exfiltration': 'TA0010',
                'impact': 'TA0040'
            }
            
            # Sample techniques (would be comprehensive in production)
            self.mitre_techniques = {
                'T1595': {'name': 'Active Scanning', 'tactic': 'reconnaissance'},
                'T1190': {'name': 'Exploit Public-Facing Application', 'tactic': 'initial_access'},
                'T1059': {'name': 'Command and Scripting Interpreter', 'tactic': 'execution'},
                'T1133': {'name': 'External Remote Services', 'tactic': 'persistence'},
                'T1098': {'name': 'Account Manipulation', 'tactic': 'persistence'},
                'T1197': {'name': 'BITS Jobs', 'tactic': 'defense_evasion'},
                'T1110': {'name': 'Brute Force', 'tactic': 'credential_access'},
                'T1087': {'name': 'Account Discovery', 'tactic': 'discovery'},
                'T1570': {'name': 'Lateral Tool Transfer', 'tactic': 'lateral_movement'},
                'T1123': {'name': 'Audio Capture', 'tactic': 'collection'},
                'T1571': {'name': 'Non-Standard Port', 'tactic': 'command_control'},
                'T1041': {'name': 'Exfiltration Over C2 Channel', 'tactic': 'exfiltration'},
            }
            logger.info("MITRE ATT&CK database loaded")
        except Exception as e:
            logger.error(f"Failed to load MITRE database: {str(e)}")
    
    def get_tactics(self) -> Dict[str, str]:
        """Return all available MITRE ATT&CK tactics."""
        return self.mitre_tactics
    
    def get_techniques(self, tactic: str) -> Dict[str, Any]:
        """Get techniques for a specific tactic."""
        return {
            technique_id: details 
            for technique_id, details in self.mitre_techniques.items() 
            if details.get('tactic') == tactic
        }
    
    async def agentic_reasoning_loop(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute agentic reasoning loop for decision-making."""
        try:
            # Prepare prompt
            prompt = self._build_reasoning_prompt(context)
            
            if self.config.LLM_ENGINE == 'claude':
                response = await self._call_claude(prompt)
            else:
                response = await self._call_ollama(prompt)
            
            # Parse decision
            decision = self._parse_llm_decision(response)
            return decision
        except Exception as e:
            logger.error(f"Agentic reasoning failed: {str(e)}")
            raise
    
    def _build_reasoning_prompt(self, context: Dict[str, Any]) -> str:
        """Build LLM prompt for agentic reasoning."""
        prompt = f"""
You are JAKAL, an autonomous penetration testing orchestrator.

Context:
- Objective: {context.get('objective', 'Security assessment')}
- Target: {context.get('target', 'Unknown')}
- Findings: {json.dumps(context.get('findings', []), indent=2)}
- MITRE ATT&CK Mapping: {json.dumps(context.get('attack_mapping', {}), indent=2)}

Your task: Recommend the next action in the penetration test workflow.

Consider:
1. MITRE ATT&CK tactics and techniques relevant to findings
2. Attack chains and lateral movement opportunities
3. Human-in-the-loop approval requirements for exploitation
4. Risk assessment and impact analysis

Respond with JSON:
{{
  "action": "stage_exploit|execute_recon|generate_report|halt",
  "reasoning": "explanation",
  "target_technique": "T1234 (optional)",
  "confidence": 0.0-1.0,
  "requires_approval": true|false
}}
"""
        return prompt
    
    async def _call_claude(self, prompt: str) -> str:
        """Call Claude API for agentic decision."""
        try:
            message = self.client.messages.create(
                model=self.config.CLAUDE_MODEL,
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3
            )
            return message.content[0].text
        except Exception as e:
            logger.error(f"Claude API call failed: {str(e)}")
            raise
    
    async def _call_ollama(self, prompt: str) -> str:
        """Call Ollama for local agentic decision."""
        try:
            response = requests.post(
                f"{self.config.OLLAMA_BASE_URL}/api/generate",
                json={
                    'model': self.config.OLLAMA_MODEL,
                    'prompt': prompt,
                    'stream': False,
                    'temperature': 0.3
                },
                timeout=30
            )
            if response.status_code == 200:
                return response.json().get('response', '')
            else:
                raise Exception(f"Ollama API error: {response.status_code}")
        except Exception as e:
            logger.error(f"Ollama API call failed: {str(e)}")
            raise
    
    def _parse_llm_decision(self, response: str) -> Dict[str, Any]:
        """Parse LLM response into structured decision."""
        try:
            decision = json.loads(response)
            return {
                'action': decision.get('action', 'halt'),
                'reasoning': decision.get('reasoning', ''),
                'target_technique': decision.get('target_technique'),
                'confidence': decision.get('confidence', 0.5),
                'requires_approval': decision.get('requires_approval', True),
                'timestamp': datetime.utcnow().isoformat()
            }
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response as JSON")
            return {
                'action': 'halt',
                'reasoning': 'Failed to parse LLM response',
                'confidence': 0.0,
                'requires_approval': True,
                'timestamp': datetime.utcnow().isoformat()
            }
    
    def map_to_attack_framework(self, recon_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Map reconnaissance findings to MITRE ATT&CK framework."""
        mappings = []
        
        findings = recon_results.get('findings', [])
        for finding in findings:
            # Simple heuristic mapping (production would use sophisticated NLP)
            if 'open port' in finding.lower():
                technique_id = 'T1595'
                tactic = 'reconnaissance'
            elif 'vulnerability' in finding.lower():
                technique_id = 'T1190'
                tactic = 'initial_access'
            elif 'credential' in finding.lower():
                technique_id = 'T1110'
                tactic = 'credential_access'
            else:
                continue
            
            mappings.append({
                'tactic': tactic,
                'technique_id': technique_id,
                'technique_name': self.mitre_techniques.get(technique_id, {}).get('name', 'Unknown'),
                'finding': finding,
                'confidence_score': 0.75
            })
        
        return mappings
    
    def register_tool(self, name: str, handler_func):
        """Register a tool for agentic use."""
        self.tool_registry[name] = handler_func
        logger.info(f"Registered tool: {name}")
    
    def get_tools(self) -> Dict[str, Any]:
        """Return available tools for agentic execution."""
        return self.tool_registry
