"""
backend/routers/maya_auth_router.py
JAKAL Maya-Vigesimal Calendar 2FA API (v3.0) — verifies the calendar-
coordinate challenge security_agents/exploit_agent.py generates for every
HIGH/CRITICAL staged payload (see stage_payloads()). This is an internal
high-assurance step-up authenticator interlocked with the existing v2.3
Human Approval Gate (routers/approval.py) — NOT login MFA, and not a
replacement for the gate: consuming a session here proves the operator
saw and echoed back the correct challenge token, and (as of the Phase 0
interlock fix) approve_payload()/reject_payload() now actively refuse to
record a decision until the linked session's status is 'consumed'. See
security_agents/exploit_agent.py's Maya-Vigesimal module comment for the
full design rationale.

Endpoints:
  POST /verify              — consume a pending challenge with its response
                               token; on success also writes a PQC-signed
                               'maya_challenge_consumed' audit entry
                               (ExploitAgent.consume_maya_challenge()).
  GET  /session/{session_id} — check a session's status. Dual-mode display:
                               only the friendly display_issued_at/
                               display_expires_at timestamps are returned
                               by default; the raw Tzolkin/Haab calendar
                               coordinates (the actual cryptographic
                               binding material) are internal and only
                               included with ?reveal_internal=true, the
                               "Show cryptographic details" auditor
                               toggle. challenge_token/response_token are
                               never returned here regardless.
"""

from database import DuckDBManager, get_db_manager
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from security_agents.exploit_agent import ExploitAgent

router = APIRouter(tags=["maya-vigesimal-auth-v3"])


def get_db() -> DuckDBManager:
    return get_db_manager()


def get_gate(db: DuckDBManager = Depends(get_db)) -> ExploitAgent:
    return ExploitAgent(db_manager=db)


class VerifyRequest(BaseModel):
    session_id: str
    response_token: str
    operator_id: str


@router.post("/verify")
def verify_maya(body: VerifyRequest, gate: ExploitAgent = Depends(get_gate)):
    result = gate.consume_maya_challenge(body.session_id, body.response_token, body.operator_id)
    if result.get("status") != "consumed":
        raise HTTPException(status_code=400, detail=result.get("message", "verification failed"))
    return result


@router.get("/session/{session_id}")
def session_status(session_id: str, reveal_internal: bool = False, db: DuckDBManager = Depends(get_db)):
    sess = db.get_maya_session(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")
    # Never return challenge_token or response_token after creation.
    resp = {
        "session_id": sess["session_id"],
        "status": sess["status"],
        "payload_id": sess["payload_id"],
        "display_issued_at": sess["display_issued_at"].isoformat(),
        "display_expires_at": sess["display_expires_at"].isoformat(),
    }
    if reveal_internal:
        resp["tzolkin_coordinate"] = sess["tzolkin_coordinate"]
        resp["haab_coordinate"] = sess["haab_coordinate"]
        resp["expires_at"] = sess["expires_at"].isoformat()
    return resp
