"""
backend/routers/maya_auth_router.py
JAKAL Maya-Vigesimal Calendar 2FA API (v3.0) — verifies the calendar-
coordinate challenge security_agents/exploit_agent.py generates for every
HIGH/CRITICAL staged payload (see stage_payloads()). This is a second
factor interlocked with the existing v2.3 Human Approval Gate
(routers/approval.py), not a replacement for it: consuming a session here
only proves the operator saw and echoed back the correct challenge token;
the payload itself still requires an explicit
POST /api/approval/{request_id}/approve decision before
execute_staged_payload() will report anything beyond "still pending".

Endpoints:
  POST /verify              — consume a pending challenge with its response token
  GET  /session/{session_id} — check a session's status (never returns the token)
"""

from database import DuckDBManager, get_db_manager
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["maya-vigesimal-auth-v3"])


def get_db() -> DuckDBManager:
    return get_db_manager()


class VerifyRequest(BaseModel):
    session_id: str
    response_token: str
    operator_id: str


@router.post("/verify")
def verify_maya(body: VerifyRequest, db: DuckDBManager = Depends(get_db)):
    result = db.consume_maya_session(body.session_id, body.response_token, body.operator_id)
    if result.get("status") != "consumed":
        raise HTTPException(status_code=400, detail=result.get("message", "verification failed"))
    return result


@router.get("/session/{session_id}")
def session_status(session_id: str, db: DuckDBManager = Depends(get_db)):
    sess = db.get_maya_session(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")
    # Never return challenge_token or response_token after creation.
    return {
        "session_id": sess["session_id"],
        "status": sess["status"],
        "tzolkin_coordinate": sess["tzolkin_coordinate"],
        "haab_coordinate": sess["haab_coordinate"],
        "expires_at": sess["expires_at"],
        "payload_id": sess["payload_id"],
    }
