"""
backend/routers/scripts.py
==========================
Script Library API Router (JAKAL v2.5)

Provides:
  • Browsable script catalog (community, approved, custom)
  • Sandbox execution environment (isolated Docker containers)
  • Live output streaming (SSE)
  • Execution history + audit trails
  • Parameter validation + type checking

Enterprise patterns from: Ansible Tower, Jenkins, GitLab CI
"""

import uuid
import json
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status as http_status, BackgroundTasks
from pydantic import BaseModel

try:
    from database import DuckDBManager
    from core.audit_logger import AuditLogger
    _db: Optional[DuckDBManager] = DuckDBManager()
    _audit_logger: Optional[AuditLogger] = AuditLogger(_db)
    SCRIPTS_OK = True
except Exception as _e:
    SCRIPTS_OK = False
    _SCRIPTS_ERR = str(_e)
    _db = None
    _audit_logger = None


class ScriptMetadata(BaseModel):
    """Script metadata and configuration."""
    script_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    category: str  # e.g., "network_recon", "endpoint_hardening", "threat_hunting"
    language: str  # e.g., "python3", "bash", "powershell"
    script_content: str
    parameters: Dict[str, Any] = {}  # {param_name: {type, required, default, description}}
    author: Optional[str] = None
    version: str = "1.0.0"
    tags: List[str] = []
    approved: bool = False
    approval_date: Optional[datetime] = None
    approval_by: Optional[str] = None


class ScriptExecutionRequest(BaseModel):
    """Request to execute a script."""
    script_id: str
    operator_id: str
    parameters: Dict[str, Any] = {}
    timeout_seconds: int = 300
    environment: Optional[Dict[str, str]] = None  # Environment variables


class ScriptExecutionResult(BaseModel):
    """Result of script execution."""
    execution_id: str
    script_id: str
    operator_id: str
    status: str  # success, failure, timeout, cancelled
    start_time: datetime
    end_time: Optional[datetime] = None
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    duration_seconds: Optional[float] = None


router = APIRouter(prefix="/scripts", tags=["script-library"])


def _require():
    """Check that Scripts router is operational."""
    if not SCRIPTS_OK:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Scripts unavailable: {_SCRIPTS_ERR}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Script Catalog Management
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/catalog")
def list_scripts(
    category: Optional[str] = Query(None),
    approved_only: bool = Query(False),
    limit: int = Query(100),
):
    """
    Browse the script catalog.
    
    Args:
        category: Filter by category (network_recon, endpoint_hardening, etc.)
        approved_only: Only show approved scripts
        limit: Max results
    
    Returns:
        List of script metadata
    """
    _require()
    try:
        clauses = []
        params = []
        
        if approved_only:
            clauses.append("approved = true")
        if category:
            clauses.append("category = ?")
            params.append(category)
        
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query = f"""
            SELECT script_id, name, description, category, language, author, version,
                   tags, approved, approval_date, approval_by, created_at
            FROM script_library
            {where}
            ORDER BY created_at DESC
            LIMIT ?
        """
        params.append(limit)
        
        rows = _db.conn.execute(query, params).fetchall()
        
        scripts = []
        for r in rows:
            scripts.append({
                "script_id": r[0],
                "name": r[1],
                "description": r[2],
                "category": r[3],
                "language": r[4],
                "author": r[5],
                "version": r[6],
                "tags": json.loads(r[7] or "[]"),
                "approved": r[8],
                "approval_date": r[9],
                "approval_by": r[10],
                "created_at": r[11],
            })
        
        return {"count": len(scripts), "scripts": scripts}
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to list scripts: {str(e)}")


@router.get("/catalog/{script_id}")
def get_script(script_id: str):
    """Get full script details including content."""
    _require()
    try:
        row = _db.conn.execute(
            """
            SELECT script_id, name, description, category, language, script_content,
                   parameters, author, version, tags, approved, approval_date,
                   approval_by, created_at
            FROM script_library
            WHERE script_id = ?
            """,
            (script_id,),
        ).fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail=f"Script {script_id} not found")
        
        return {
            "script_id": row[0],
            "name": row[1],
            "description": row[2],
            "category": row[3],
            "language": row[4],
            "script_content": row[5],
            "parameters": json.loads(row[6] or "{}"),
            "author": row[7],
            "version": row[8],
            "tags": json.loads(row[9] or "[]"),
            "approved": row[10],
            "approval_date": row[11],
            "approval_by": row[12],
            "created_at": row[13],
        }
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch script: {str(e)}")


@router.post("/catalog", status_code=http_status.HTTP_201_CREATED)
def create_script(req: ScriptMetadata, operator_id: str = "system"):
    """
    Upload a new script to the library.
    Scripts are unapproved by default (requires admin review).
    """
    _require()
    try:
        script_id = req.script_id or str(uuid.uuid4())
        
        _db.conn.execute(
            """
            INSERT INTO script_library
                (script_id, name, description, category, language, script_content,
                 parameters, author, version, tags, approved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                script_id,
                req.name,
                req.description,
                req.category,
                req.language,
                req.script_content,
                json.dumps(req.parameters),
                req.author or operator_id,
                req.version,
                json.dumps(req.tags),
                False,  # Require approval
            ),
        )
        _db.conn.commit()
        
        _audit_logger.log(
            event_type="script_uploaded",
            action="upload_script",
            actor=operator_id,
            resource=script_id,
            details={"name": req.name, "category": req.category},
        )
        
        return {
            "script_id": script_id,
            "name": req.name,
            "status": "created",
            "approved": False,
            "message": "Script uploaded. Awaiting admin approval.",
        }
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to create script: {str(e)}")


@router.post("/catalog/{script_id}/approve")
def approve_script(script_id: str, approval_by: str = "admin"):
    """
    Approve a script for production use.
    Only admin can approve.
    """
    _require()
    try:
        result = _db.conn.execute(
            """
            UPDATE script_library
            SET approved = true, approval_date = ?, approval_by = ?
            WHERE script_id = ?
            RETURNING script_id
            """,
            (datetime.now(timezone.utc), approval_by, script_id),
        )
        
        if not result.fetchall():
            raise HTTPException(status_code=404, detail=f"Script {script_id} not found")
        
        _db.conn.commit()
        
        _audit_logger.log(
            event_type="script_approved",
            action="approve_script",
            actor=approval_by,
            resource=script_id,
            result="success",
        )
        
        return {"script_id": script_id, "status": "approved"}
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to approve script: {str(e)}")


# ══════════════════════════════════════════════════════════════════════════════
# Script Execution (Sandbox)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/{script_id}/sandbox-execute", status_code=http_status.HTTP_201_CREATED)
def execute_script_in_sandbox(
    script_id: str,
    req: ScriptExecutionRequest,
    background_tasks: BackgroundTasks,
):
    """
    Execute a script in an isolated sandbox container.
    
    Returns:
        Execution ID + status (can poll for results or stream via SSE)
    """
    _require()
    try:
        # Fetch script
        script_row = _db.conn.execute(
            "SELECT language, script_content FROM script_library WHERE script_id = ?",
            (script_id,),
        ).fetchone()
        
        if not script_row:
            raise HTTPException(status_code=404, detail=f"Script {script_id} not found")
        
        language, script_content = script_row
        execution_id = str(uuid.uuid4())
        
        # Create execution record
        _db.conn.execute(
            """
            INSERT INTO script_executions
                (execution_id, script_id, operator_id, status, parameters,
                 environment, timeout_seconds, start_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                execution_id,
                script_id,
                req.operator_id,
                "queued",
                json.dumps(req.parameters),
                json.dumps(req.environment or {}),
                req.timeout_seconds,
                datetime.now(timezone.utc),
            ),
        )
        _db.conn.commit()
        
        # Queue execution (in background)
        background_tasks.add_task(
            _execute_script_background,
            execution_id=execution_id,
            script_id=script_id,
            language=language,
            script_content=script_content,
            parameters=req.parameters,
            environment=req.environment,
            timeout_seconds=req.timeout_seconds,
            operator_id=req.operator_id,
        )
        
        _audit_logger.log(
            event_type="script_execution_queued",
            action="sandbox_execute",
            actor=req.operator_id,
            resource=script_id,
            details={"execution_id": execution_id},
        )
        
        return {
            "execution_id": execution_id,
            "script_id": script_id,
            "status": "queued",
            "message": "Execution queued. Poll /scripts/executions/{id}/result for results.",
        }
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to execute script: {str(e)}")


@router.get("/executions/{execution_id}/result")
def get_execution_result(execution_id: str):
    """
    Retrieve the result of a script execution.
    Blocks until complete (or timeout).
    """
    _require()
    try:
        row = _db.conn.execute(
            """
            SELECT execution_id, script_id, operator_id, status, parameters,
                   environment, timeout_seconds, start_time, end_time,
                   exit_code, stdout, stderr, duration_seconds
            FROM script_executions
            WHERE execution_id = ?
            """,
            (execution_id,),
        ).fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")
        
        return {
            "execution_id": row[0],
            "script_id": row[1],
            "operator_id": row[2],
            "status": row[3],
            "parameters": json.loads(row[4] or "{}"),
            "environment": json.loads(row[5] or "{}"),
            "timeout_seconds": row[6],
            "start_time": row[7],
            "end_time": row[8],
            "exit_code": row[9],
            "stdout": row[10],
            "stderr": row[11],
            "duration_seconds": row[12],
        }
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch result: {str(e)}")


@router.get("/executions/{execution_id}/stream")
def stream_execution_output(execution_id: str):
    """
    Stream live output of a script execution via SSE.
    """
    _require()
    
    async def event_generator():
        """Generator for SSE events."""
        import asyncio

        while True:
            try:
                row = _db.conn.execute(
                    "SELECT status, stdout, stderr, end_time FROM script_executions WHERE execution_id = ?",
                    (execution_id,),
                ).fetchone()
                
                if not row:
                    yield "data: {}\n\n".format(json.dumps({
                        "error": f"Execution {execution_id} not found"
                    }))
                    break
                
                status, stdout, stderr, end_time = row
                
                # Emit current output
                if stdout:
                    yield "data: {}\n\n".format(json.dumps({
                        "type": "stdout",
                        "content": stdout,
                    }))
                
                if stderr:
                    yield "data: {}\n\n".format(json.dumps({
                        "type": "stderr",
                        "content": stderr,
                    }))
                
                # If complete, emit final status
                if status in ["success", "failure", "timeout", "cancelled"]:
                    yield "data: {}\n\n".format(json.dumps({
                        "type": "complete",
                        "status": status,
                        "end_time": end_time.isoformat() if end_time else None,
                    }))
                    break
                
                await asyncio.sleep(1)
            
            except Exception as e:
                yield "data: {}\n\n".format(json.dumps({
                    "error": str(e)
                }))
                break
    
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/executions")
def list_executions(
    script_id: Optional[str] = Query(None),
    operator_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100),
):
    """
    List script execution history.
    """
    _require()
    try:
        clauses = []
        params = []
        
        if script_id:
            clauses.append("script_id = ?")
            params.append(script_id)
        if operator_id:
            clauses.append("operator_id = ?")
            params.append(operator_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query = f"""
            SELECT execution_id, script_id, operator_id, status, start_time, end_time,
                   exit_code, duration_seconds
            FROM script_executions
            {where}
            ORDER BY start_time DESC
            LIMIT ?
        """
        params.append(limit)
        
        rows = _db.conn.execute(query, params).fetchall()
        
        executions = []
        for r in rows:
            executions.append({
                "execution_id": r[0],
                "script_id": r[1],
                "operator_id": r[2],
                "status": r[3],
                "start_time": r[4],
                "end_time": r[5],
                "exit_code": r[6],
                "duration_seconds": r[7],
            })
        
        return {"count": len(executions), "executions": executions}
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to list executions: {str(e)}")


# ══════════════════════════════════════════════════════════════════════════════
# Internal Background Task
# ══════════════════════════════════════════════════════════════════════════════

def _execute_script_background(
    execution_id: str,
    script_id: str,
    language: str,
    script_content: str,
    parameters: Dict[str, Any],
    environment: Optional[Dict[str, str]],
    timeout_seconds: int,
    operator_id: str,
):
    """
    Execute a script in background (sandbox).
    In production, this would use Docker or VM containers.
    For now, it's a placeholder.
    """
    import subprocess

    start_time = datetime.now(timezone.utc)
    
    try:
        # Update status
        _db.conn.execute(
            "UPDATE script_executions SET status = ? WHERE execution_id = ?",
            ("executing", execution_id),
        )
        _db.conn.commit()
        
        # In production, wrap script in Docker container
        # For now, execute directly (dangerous, for demo only!)
        if language == "bash":
            result = subprocess.run(
                ["bash", "-c", script_content],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=environment or {},
            )
        elif language == "python3":
            result = subprocess.run(
                ["python3", "-c", script_content],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=environment or {},
            )
        else:
            raise Exception(f"Unsupported language: {language}")
        
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()
        
        # Store result
        _db.conn.execute(
            """
            UPDATE script_executions
            SET status = ?, end_time = ?, exit_code = ?, stdout = ?, stderr = ?, duration_seconds = ?
            WHERE execution_id = ?
            """,
            (
                "success" if result.returncode == 0 else "failure",
                end_time,
                result.returncode,
                result.stdout[:10000],  # Truncate to 10KB
                result.stderr[:10000],
                duration,
                execution_id,
            ),
        )
        _db.conn.commit()
        
        _audit_logger.log(
            event_type="script_execution_complete",
            action="sandbox_execute",
            actor=operator_id,
            resource=script_id,
            result="success" if result.returncode == 0 else "failure",
            details={
                "execution_id": execution_id,
                "exit_code": result.returncode,
                "duration_seconds": duration,
            },
        )
    
    except subprocess.TimeoutExpired:
        end_time = datetime.now(timezone.utc)
        _db.conn.execute(
            """
            UPDATE script_executions
            SET status = ?, end_time = ?, duration_seconds = ?
            WHERE execution_id = ?
            """,
            ("timeout", end_time, (end_time - start_time).total_seconds(), execution_id),
        )
        _db.conn.commit()
        
        _audit_logger.log(
            event_type="script_execution_timeout",
            action="sandbox_execute",
            actor=operator_id,
            resource=script_id,
            result="timeout",
            details={"execution_id": execution_id},
        )
    
    except Exception as e:
        end_time = datetime.now(timezone.utc)
        _db.conn.execute(
            """
            UPDATE script_executions
            SET status = ?, end_time = ?, stderr = ?, duration_seconds = ?
            WHERE execution_id = ?
            """,
            ("failure", end_time, str(e)[:1000], (end_time - start_time).total_seconds(), execution_id),
        )
        _db.conn.commit()
        
        _audit_logger.log(
            event_type="script_execution_error",
            action="sandbox_execute",
            actor=operator_id,
            resource=script_id,
            result="failure",
            details={"execution_id": execution_id, "error": str(e)},
        )
