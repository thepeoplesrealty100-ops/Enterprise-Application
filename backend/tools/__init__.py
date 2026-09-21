"""
backend/tools — authorization and shared tool helpers.

Canonical module: tools/authorization.py
Imported by security agents as `from tools.authorization import ...`.
"""
from tools.authorization import check_authorization_and_scope, AuthorizationError, ScopeEntry

__all__ = ["check_authorization_and_scope", "AuthorizationError", "ScopeEntry"]
