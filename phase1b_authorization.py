#!/usr/bin/env python3
"""
JAKAL Authorization & Compliance Framework
Mandatory gates before any action executes
"""

import logging
import ipaddress
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class AuthorizationResult:
    """Result of an authorization check."""
    authorized: bool
    reason: str
    timestamp: datetime
    scope_valid: bool
    insurance_valid: bool
    operator_approved: bool

class AuthorizationGate:
    """
    Mandatory authorization gate that blocks unauthorized actions.
    Every network-facing action MUST pass this gate.
    """
    
    def __init__(self, db_manager, config):
        self.db = db_manager
        self.config = config
        logger.info("Authorization gate initialized")
    
    def check_authorization_and_scope(
        self,
        target: str,
        action: str,
        operator_id: str
    ) -> AuthorizationResult:
        """
        Comprehensive authorization check: scope + insurance + operator.
        
        Args:
            target: IP address, domain, or CIDR range
            action: Action type (scan, exploit, pentest, etc.)
            operator_id: User requesting the action
        
        Returns:
            AuthorizationResult with detailed status
        
        Raises:
            PermissionError if any check fails
        """
        timestamp = datetime.utcnow()
        
        # Check 1: Operator exists and is active
        operator_result = self._verify_operator(operator_id)
        if not operator_result[0]:
            reason = f"Operator not found or inactive: {operator_id}"
            self._log_authorization_denial(timestamp, action, target, operator_id, reason)
            raise PermissionError(reason)
        
        # Check 2: Scope validation
        scope_result, scope_reason = self._validate_scope(target)
        if not scope_result:
            reason = f"Target outside authorized scope: {scope_reason}"
            self._log_authorization_denial(timestamp, action, target, operator_id, reason)
            raise PermissionError(reason)
        
        # Check 3: Insurance validation
        insurance_result, insurance_reason = self._validate_insurance()
        if not insurance_result:
            reason = f"No active insurance policy: {insurance_reason}"
            self._log_authorization_denial(timestamp, action, target, operator_id, reason)
            raise PermissionError(reason)
        
        # All checks passed
        self._log_authorization_approval(
            timestamp, action, target, operator_id,
            scope_result, insurance_result, operator_result[1]
        )
        
        return AuthorizationResult(
            authorized=True,
            reason="All authorization checks passed",
            timestamp=timestamp,
            scope_valid=scope_result,
            insurance_valid=insurance_result,
            operator_approved=True
        )
    
    def _verify_operator(self, operator_id: str) -> Tuple[bool, Optional[str]]:
        """Verify operator exists, is active, and has valid role."""
        try:
            result = self.db.query_one("""
                SELECT id, role, active FROM operators 
                WHERE operator_id = ? AND active = true
            """, (operator_id,))
            
            if result:
                return True, result[1]  # Return role
            else:
                logger.warning(f"Operator verification failed: {operator_id}")
                return False, None
        except Exception as e:
            logger.error(f"Operator verification error: {str(e)}")
            return False, None
    
    def _validate_scope(self, target: str) -> Tuple[bool, str]:
        """
        Validate that target is within authorized scope.
        Supports: single IPs, IP ranges (CIDR), domain names
        """
        try:
            # Get all active scopes
            scopes = self.db.query("""
                SELECT id, target_ips, target_domains, excluded_ips, excluded_domains
                FROM scopes
                WHERE status = 'active'
                AND end_date > datetime('now')
            """)
            
            if not scopes:
                return False, "No active scopes"
            
            for scope in scopes:
                scope_id, target_ips_str, target_domains_str, excluded_ips_str, excluded_domains_str = scope
                
                # Check excluded targets first
                if self._is_in_list(target, excluded_ips_str, excluded_domains_str):
                    logger.warning(f"Target in exclusion list: {target}")
                    continue
                
                # Check included targets
                if self._is_in_list(target, target_ips_str, target_domains_str):
                    return True, f"Matched scope {scope_id}"
            
            return False, "Target not in any active scope"
        
        except Exception as e:
            logger.error(f"Scope validation error: {str(e)}")
            return False, str(e)
    
    def _is_in_list(self, target: str, ips_str: Optional[str], domains_str: Optional[str]) -> bool:
        """Check if target matches IP list or domain list."""
        try:
            # Try to parse as IP address
            try:
                target_ip = ipaddress.ip_address(target)
                if ips_str:
                    for ip_range in ips_str.split(","):
                        ip_range = ip_range.strip()
                        if "/" in ip_range:
                            # CIDR notation
                            if target_ip in ipaddress.ip_network(ip_range, strict=False):
                                return True
                        else:
                            # Single IP
                            if target_ip == ipaddress.ip_address(ip_range):
                                return True
            except ValueError:
                # Not an IP, treat as domain
                pass
            
            # Check domain list
            if domains_str:
                for domain in domains_str.split(","):
                    domain = domain.strip().lower()
                    target_lower = target.lower()
                    if domain == target_lower or target_lower.endswith("." + domain):
                        return True
            
            return False
        except Exception as e:
            logger.error(f"List membership check error: {str(e)}")
            return False
    
    def _validate_insurance(self) -> Tuple[bool, str]:
        """Verify active insurance policy with valid expiry."""
        try:
            result = self.db.query_one("""
                SELECT policy_number, coverage_amount, expiry
                FROM insurance_policies
                WHERE status = 'active'
                AND expiry > datetime('now')
                LIMIT 1
            """)
            
            if result:
                policy_number, coverage_amount, expiry = result
                logger.info(f"Active insurance verified: {policy_number} (${coverage_amount})")
                return True, f"Policy {policy_number} active until {expiry}"
            else:
                return False, "No active insurance policies found"
        except Exception as e:
            logger.error(f"Insurance validation error: {str(e)}")
            return False, str(e)
    
    def _log_authorization_approval(
        self,
        timestamp: datetime,
        action: str,
        target: str,
        operator_id: str,
        scope_valid: bool,
        insurance_valid: bool,
        operator_role: str
    ) -> None:
        """Log approved authorization to compliance checkpoint."""
        try:
            self.db.insert_log({
                "timestamp": timestamp,
                "event": "AUTHORIZATION_APPROVED",
                "action": action,
                "status": "approved",
                "operator_id": operator_id,
                "target": target,
                "details": {
                    "scope_valid": scope_valid,
                    "insurance_valid": insurance_valid,
                    "operator_role": operator_role
                }
            })
            logger.info(f"Authorization approved: {operator_id} → {action} on {target}")
        except Exception as e:
            logger.error(f"Authorization logging failed: {str(e)}")
    
    def _log_authorization_denial(
        self,
        timestamp: datetime,
        action: str,
        target: str,
        operator_id: str,
        reason: str
    ) -> None:
        """Log denied authorization to compliance checkpoint."""
        try:
            self.db.insert_log({
                "timestamp": timestamp,
                "event": "AUTHORIZATION_DENIED",
                "action": action,
                "status": "denied",
                "operator_id": operator_id,
                "target": target,
                "details": {
                    "reason": reason
                }
            })
            logger.warning(f"Authorization denied: {operator_id} → {action} on {target} ({reason})")
        except Exception as e:
            logger.error(f"Authorization denial logging failed: {str(e)}")
    
    def add_scope(self, scope_id: str, client_name: str, target_ips: str, target_domains: str, roe_path: str) -> int:
        """Add a new authorized scope (RoE - Rules of Engagement)."""
        try:
            # Check if scope already exists
            existing = self.db.query_one("""
                SELECT id FROM scopes WHERE scope_id = ?
            """, (scope_id,))
            
            if existing:
                raise ValueError(f"Scope {scope_id} already exists")
            
            self.db.execute("""
                INSERT INTO scopes
                (scope_id, client_name, target_ips, target_domains, roe_document_path, status, start_date, end_date, expires_at)
                VALUES (?, ?, ?, ?, ?, 'active', datetime('now'), datetime('now', '+90 days'), datetime('now', '+90 days'))
            """, (scope_id, client_name, target_ips, target_domains, roe_path))
            
            logger.info(f"Scope added: {scope_id} for {client_name}")
            
            # Log this action
            self.db.insert_log({
                "timestamp": datetime.utcnow(),
                "event": "SCOPE_ADDED",
                "action": "add_scope",
                "status": "created",
                "operator_id": "system",
                "details": {
                    "scope_id": scope_id,
                    "client": client_name,
                    "targets_ips": target_ips,
                    "targets_domains": target_domains
                }
            })
            
            result = self.db.query_one("SELECT last_insert_rowid()")
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Add scope failed: {str(e)}")
            raise
    
    def add_insurance_policy(self, policy_number: str, provider: str, coverage_amount: float, expiry_date: str) -> int:
        """Add active insurance policy."""
        try:
            self.db.execute("""
                INSERT INTO insurance_policies
                (policy_number, provider, coverage_amount, expiry, status, expires_at)
                VALUES (?, ?, ?, datetime(?), 'active', datetime(?))
            """, (policy_number, provider, coverage_amount, expiry_date, expiry_date))
            
            logger.info(f"Insurance policy added: {policy_number}")
            
            self.db.insert_log({
                "timestamp": datetime.utcnow(),
                "event": "INSURANCE_POLICY_ADDED",
                "action": "add_policy",
                "status": "created",
                "operator_id": "system",
                "details": {
                    "policy_number": policy_number,
                    "provider": provider,
                    "coverage": coverage_amount
                }
            })
            
            result = self.db.query_one("SELECT last_insert_rowid()")
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Add insurance policy failed: {str(e)}")
            raise
    
    def list_active_scopes(self) -> List[Dict]:
        """Get all active scopes."""
        try:
            scopes = self.db.query("""
                SELECT id, scope_id, client_name, target_ips, target_domains, start_date, end_date
                FROM scopes
                WHERE status = 'active'
                AND end_date > datetime('now')
                ORDER BY created_at DESC
            """)
            
            return [
                {
                    "id": row[0],
                    "scope_id": row[1],
                    "client": row[2],
                    "target_ips": row[3],
                    "target_domains": row[4],
                    "start_date": row[5],
                    "end_date": row[6]
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
                FROM insurance_policies
                WHERE status = 'active'
                AND expiry > datetime('now')
                ORDER BY created_at DESC
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
