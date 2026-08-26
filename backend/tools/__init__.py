"""
backend/tools — lowercase alias for Tools/ (imported by existing security agents).
Canonical source of truth for authorization.py lives in Tools/; this module re-exports
it so that `from tools.authorization import ...` works as expected.
"""
from tools.authorization import check_authorization_and_scope, AuthorizationError, ScopeEntry

__all__ = ["check_authorization_and_scope", "AuthorizationError", "ScopeEntry"]
