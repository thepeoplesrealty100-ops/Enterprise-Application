# backend/tools/authorization.py
from datetime import datetime
import json
from database import DuckDBManager

db = DuckDBManager()

def check_authorization_and_scope(target: str, action: str, operator_id: str) -> dict:
    """
    Real-time legal, scope, and insurance validation.
    Blocks execution if any check fails.
    """
    scopes = db.query("SELECT * FROM scopes WHERE status = 'active'")
    insurance = db.query(
        "SELECT * FROM insurance_policies WHERE status = 'active' AND expiry > ?",
        (datetime.utcnow(),)
    )
    
    # Expand with proper CIDR / domain matching as needed
    in_scope = any(target in str(s) for s in scopes) if scopes else False
    has_insurance = len(insurance) > 0
    
    if not in_scope or not has_insurance:
        db.insert_log({
            "event": "AUTHORIZATION_DENIED",
            "action": action,
            "status": "blocked",
            "operator_id": operator_id,
            "details": {"target": target, "reason": "scope or insurance failure"}
        })
        raise PermissionError(
            "Target outside authorized scope or insurance not valid. Operation blocked."
        )
    
    db.insert_log({
        "event": "AUTHORIZATION_GRANTED",
        "action": action,
        "status": "approved",
        "operator_id": operator_id,
        "details": {"target": target}
    })
    return {"authorized": True, "timestamp": datetime.utcnow().isoformat()}
