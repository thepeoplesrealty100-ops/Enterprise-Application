#!/usr/bin/env python3
"""JAKAL Authorization & Compliance Framework"""
import logging
import ipaddress
from datetime import datetime
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)

class AuthorizationGate:
    """Mandatory authorization gate before any action executes."""
    
    def __init__(self, db_manager, config):
        self.db = db_manager
        self.config = config
        logger.info("✅ Authorization gate initialized")
    
    def check_authorization_and_scope(self, target: str, action: str, operator_id: str) -> Dict:
        """Comprehensive authorization check: scope + insurance + operator."""
        timestamp = datetime.utcnow()
        
        # Check 1: Operator
        if not self._verify_operator(operator_id):
            reason = f"Operator not found or inactive: {operator_id}"
            self._log_denial(timestamp, action, target, operator_id, reason)
            raise PermissionError(reason)
        
        # Check 2: Scope
        scope_valid, scope_reason = self._validate_scope(target)
        if not scope_valid:
            reason = f"Target outside authorized scope: {scope_reason}"
            self._log_denial(timestamp, action, target, operator_id, reason)
            raise PermissionError(reason)
        
        # Check 3: Insurance
        insurance_valid, insurance_reason = self._validate_insurance()
        if not insurance_valid:
            reason = f"No active insurance policy: {insurance_reason}"
            self._log_denial(timestamp, action, target, operator_id, reason)
            raise PermissionError(reason)
        
        self._log_approval(timestamp, action, target, operator_id)
        return {"authorized": True, "timestamp": timestamp, "scope_valid": scope_valid, "insurance_valid": insurance_valid}
    
    def _verify_operator(self, operator_id: str) -> bool:
        """Verify operator exists and is active."""
        try:
            result = self.db.query_one("""
                SELECT id FROM operators WHERE operator_id = ? AND active = true
            """, (operator_id,))
            return bool(result)
        except Exception as e:
            logger.error(f"Operator verification error: {str(e)}")
            return False
    
    def _validate_scope(self, target: str) -> Tuple[bool, str]:
        """Validate target is within authorized scope."""
        try:
            scopes = self.db.query("""
                SELECT target_ips, target_domains, excluded_ips, excluded_domains
                FROM scopes WHERE status = 'active' AND expires_at > datetime('now')
            """)
            
            if not scopes:
                return False, "No active scopes"
            
            for scope in scopes:
                target_ips, target_domains, excluded_ips, excluded_domains = scope
                
                if self._is_in_list(target, excluded_ips, excluded_domains):
                    continue
                
                if self._is_in_list(target, target_ips, target_domains):
                    return True, "Target in authorized scope"
            
            return False, "Target not in any active scope"
        except Exception as e:
            logger.error(f"Scope validation error: {str(e)}")
            return False, str(e)
    
    def _is_in_list(self, target: str, ips_str: Optional[str], domains_str: Optional[str]) -> bool:
        """Check if target matches IP or domain list."""
        try:
            try:
                target_ip = ipaddress.ip_address(target)
                if ips_str:
                    for ip_range in ips_str.split(","):
                        ip_range = ip_range.strip()
                        if "/" in ip_range:
                            if target_ip in ipaddress.ip_network(ip_range, strict=False):
                                return True
                        else:
                            if target_ip == ipaddress.ip_address(ip_range):
                                return True
            except ValueError:
                pass
            
            if domains_str:
                for domain in domains_str.split(","):
                    domain = domain.strip().lower()
                    target_lower = target.lower()
                    if domain == target_lower or target_lower.endswith("." + domain):
                        return True
            
            return False
        except Exception as e:
            logger.error(f"List check error: {str(e)}")
            return False
    
    def _validate_insurance(self) -> Tuple[bool, str]:
        """Verify active insurance policy."""
        try:
            result = self.db.query_one("""
                SELECT policy_number FROM insurance_policies
                WHERE status = 'active' AND expiry > datetime('now') LIMIT 1
            """)
            
            if result:
                return True, "Active insurance verified"
            else:
                return False, "No active insurance policies"
        except Exception as e:
            logger.error(f"Insurance validation error: {str(e)}")
            return False, str(e)
    
    def _log_approval(self, timestamp: datetime, action: str, target: str, operator_id: str) -> None:
        """Log approved authorization."""
        try:
            self.db.insert_log({
                "timestamp": timestamp,
                "event": "AUTHORIZATION_APPROVED",
                "action": action,
                "status": "approved",
                "operator_id": operator_id,
                "target": target
            })
        except Exception as e:
            logger.error(f"Approval logging failed: {str(e)}")
    
    def _log_denial(self, timestamp: datetime, action: str, target: str, operator_id: str, reason: str) -> None:
        """Log denied authorization."""
        try:
            self.db.insert_log({
                "timestamp": timestamp,
                "event": "AUTHORIZATION_DENIED",
                "action": action,
                "status": "denied",
                "operator_id": operator_id,
                "target": target,
                "details": reason
            })
        except Exception as e:
            logger.error(f"Denial logging failed: {str(e)}")
    
    def add_scope(self, scope_id: str, client_name: str, target_ips: str, target_domains: str) -> int:
        """Add a new authorized scope."""
        try:
            self.db.execute("""
                INSERT INTO scopes
                (scope_id, client_name, target_ips, target_domains, status, expires_at)
                VALUES (?, ?, ?, ?, 'active', datetime('now', '+90 days'))
            """, (scope_id, client_name, target_ips, target_domains))
            
            result = self.db.query_one("SELECT last_insert_rowid()")
            logger.info(f"✅ Scope added: {scope_id}")
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Add scope failed: {str(e)}")
            raise
    
    def add_insurance_policy(self, policy_number: str, provider: str, coverage_amount: float, expiry_date: str) -> int:
        """Add active insurance policy."""
        try:
            self.db.execute("""
                INSERT INTO insurance_policies
                (policy_number, provider, coverage_amount, expiry, status)
                VALUES (?, ?, ?, datetime(?), 'active')
            """, (policy_number, provider, coverage_amount, expiry_date))
            
            result = self.db.query_one("SELECT last_insert_rowid()")
            logger.info(f"✅ Insurance policy added: {policy_number}")
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Add insurance policy failed: {str(e)}")
            raise
    
    def list_active_scopes(self) -> List[Dict]:
        """Get all active scopes."""
        try:
            scopes = self.db.query("""
                SELECT id, scope_id, client_name, target_ips, target_domains
                FROM scopes WHERE status = 'active' AND expires_at > datetime('now')
            """)
            
            return [
                {
                    "id": row[0],
                    "scope_id": row[1],
                    "client": row[2],
                    "target_ips": row[3],
                    "target_domains": row[4]
                } for row in scopes
            ] if scopes else []
        except Exception as e:
            logger.error(f"List scopes failed: {str(e)}")
            return []
    
    def list_active_insurance(self) -> List[Dict]:
        """Get all active insurance policies."""
        try:
            policies = self.db.query("""
                SELECT id, policy_number, provider, coverage_amount, expiry
                FROM insurance_policies WHERE status = 'active' AND expiry > datetime('now')
            """)
            
            return [
                {
                    "id": row[0],
                    "policy_number": row[1],
                    "provider": row[2],
                    "coverage_amount": row[3],
                    "expiry": row[4]
                } for row in policies
            ] if policies else []
        except Exception as e:
            logger.error(f"List insurance failed: {str(e)}")
            return []
