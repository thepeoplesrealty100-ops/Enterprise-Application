"""
JAKAL / GACyber Tool Kit – Shodan API Integration
CPENT Phase 1 (Reconnaissance) / Phase 2 (Scanning support)

IMPORTANT:
- Requires a valid Shodan API key stored in environment variable SHODAN_API_KEY
  or passed explicitly.
- EVERY call is gated by the authorization / scope / insurance check.
- Only query targets that are explicitly in scope and under written RoE.
- Do not use for unauthorized scanning or reconnaissance.
"""

import os
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from tools.authorization import check_authorization_and_scope

logger = logging.getLogger(__name__)

# Optional dependency – install with: pip install shodan
try:
    import shodan
    SHODAN_AVAILABLE = True
except ImportError:
    SHODAN_AVAILABLE = False
    logger.warning("shodan package not installed. Run: pip install shodan")


class ShodanClient:
    """Thin wrapper around the official Shodan Python library with mandatory auth gate."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SHODAN_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Shodan API key required. Set SHODAN_API_KEY environment variable "
                "or pass api_key= to ShodanClient()."
            )
        if not SHODAN_AVAILABLE:
            raise ImportError("shodan package is not installed. pip install shodan")
        self.api = shodan.Shodan(self.api_key)

    def host(
        self,
        ip: str,
        operator_id: str = "system",
        history: bool = False,
    ) -> Dict[str, Any]:
        """
        Retrieve host information for a single IP.
        Authorization gate is enforced before any API call.
        """
        check_authorization_and_scope(ip, "shodan_host_lookup", operator_id)

        try:
            result = self.api.host(ip, history=history)
            return {
                "ip": ip,
                "data": result,
                "timestamp": datetime.utcnow().isoformat(),
                "source": "shodan",
            }
        except shodan.APIError as e:
            logger.error(f"Shodan API error for {ip}: {e}")
            return {"ip": ip, "error": str(e), "source": "shodan"}

    def search(
        self,
        query: str,
        target_hint: str,
        operator_id: str = "system",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Perform a Shodan search.
        target_hint is used for the authorization gate (must be in scope).
        """
        check_authorization_and_scope(target_hint, "shodan_search", operator_id)

        try:
            results = self.api.search(query, limit=limit)
            return {
                "query": query,
                "total": results.get("total", 0),
                "matches": results.get("matches", [])[:limit],
                "timestamp": datetime.utcnow().isoformat(),
                "source": "shodan",
            }
        except shodan.APIError as e:
            logger.error(f"Shodan search error: {e}")
            return {"query": query, "error": str(e), "source": "shodan"}

    def dns_domain(
        self,
        domain: str,
        operator_id: str = "system",
    ) -> Dict[str, Any]:
        """Resolve DNS information for a domain (authorized only)."""
        check_authorization_and_scope(domain, "shodan_dns_domain", operator_id)

        try:
            # Shodan DNS domain endpoint
            result = self.api.dns.domain_info(domain)
            return {
                "domain": domain,
                "data": result,
                "timestamp": datetime.utcnow().isoformat(),
                "source": "shodan",
            }
        except Exception as e:
            logger.error(f"Shodan DNS error for {domain}: {e}")
            return {"domain": domain, "error": str(e), "source": "shodan"}


def quick_host_lookup(ip: str, operator_id: str = "system") -> Dict[str, Any]:
    """Convenience function for one-off authorized host lookups."""
    client = ShodanClient()
    return client.host(ip, operator_id=operator_id)
