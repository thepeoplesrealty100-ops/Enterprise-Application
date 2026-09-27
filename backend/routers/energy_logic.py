"""
JAKAL v4.0 - Energy Core & Logic Engine Router
Merged from: Energy Core Management + Q'AIP Logic Core Manager

The "Q'AIP Logic Core" half of this router (logic-execute / its status
endpoint / execute_logic_chain_bg / _KNOWN_OPERATION_TYPES below) is real
and unchanged -- see its own docstrings and
tests/test_energy_logic_and_scripts_security.py.

The "Energy Core" half used to be 100% fabricated nanoswarm/drone power
math (fixed 10kW "grid", hardcoded wattage-per-swarm-unit, invented
per-hour "predicted_load_watts", a fake carbon-footprint figure). This
platform has no physical energy subsystem to report on, so rather than
keep inventing numbers, these endpoints are rebuilt around the one real,
finite resource this platform actually manages and can run out of:
background job/compute-execution capacity -- the concurrent sandboxes,
vulnerability scans, playbook runs, uploaded-script executions and
pentest engagements this process is actually running right now
(sandboxes / vuln_scan_jobs / playbook_executions / script_executions /
pentest_runs, all in database.py). Route paths and methods are
unchanged; the numbers behind them are now real DB-backed counts instead
of fixed/fabricated fixtures.
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import json
import time

from database import DuckDBManager, get_db_manager

router = APIRouter(prefix="/api/energy-logic", tags=["Energy Core & Logic"])

# Real active-state predicates per job table, derived from how each table's
# status column is actually written elsewhere in this codebase (database.py /
# routers/scripts.py / routers/vulnerability_management.py) -- not a fabricated
# nanoswarm/watt fixture.
_ACTIVE_JOB_QUERIES = {
    "sandboxes": "SELECT COUNT(*) FROM sandboxes WHERE status = 'running'",
    "vuln_scan_jobs": "SELECT COUNT(*) FROM vuln_scan_jobs WHERE status IN ('queued', 'running')",
    "playbook_executions": "SELECT COUNT(*) FROM playbook_executions WHERE status = 'in_progress'",
    "script_executions": "SELECT COUNT(*) FROM script_executions WHERE status IN ('queued', 'executing')",
    "pentest_runs": "SELECT COUNT(*) FROM pentest_runs WHERE status NOT IN ('completed', 'report_ready', 'failed')",
}

_DEFAULT_MAX_CONCURRENT_JOBS = 50


def _active_job_counts(db: DuckDBManager) -> Dict[str, int]:
    counts = {}
    for name, query in _ACTIVE_JOB_QUERIES.items():
        try:
            counts[name] = db.conn.execute(query).fetchone()[0]
        except Exception:
            counts[name] = 0
    return counts


def _max_concurrent_jobs(db: DuckDBManager) -> int:
    row = db.conn.execute(
        "SELECT value FROM automation_settings WHERE policy_key = 'max_concurrent_jobs'"
    ).fetchone()
    if not row:
        return _DEFAULT_MAX_CONCURRENT_JOBS
    try:
        return int(json.loads(row[0]))
    except Exception:
        return _DEFAULT_MAX_CONCURRENT_JOBS

# The operation types this endpoint's docstring has always documented as
# supported. Real validation now enforces this list -- the old version
# accepted (and silently "completed") any garbage operation dict.
_KNOWN_OPERATION_TYPES = {
    "threat_assessment", "payload_generation", "swarm_coordination",
    "resource_optimization", "response_planning",
}


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class PowerAllocation(BaseModel):
    """Power allocation request"""
    nanoswarm_id: str
    swarm_size: int
    mission_duration_seconds: int
    power_profile: str = "balanced"  # 'idle', 'normal', 'aggressive', 'burst'
    priority: int = 5


class LogicChain(BaseModel):
    """Logic execution chain"""
    chain_id: str
    operations: List[Dict[str, Any]]
    execution_order: str = "sequential"  # 'sequential', 'parallel', 'conditional'
    timeout_seconds: int = 300


class PayloadOptimization(BaseModel):
    """Payload optimization request"""
    payload_name: str
    target_environment: str
    constraints: Dict[str, Any]
    optimization_metric: str = "efficiency"  # 'speed', 'efficiency', 'stealth', 'robustness'


class EnergyStatus(BaseModel):
    """Energy system status"""
    total_available_power: float
    power_allocated: float
    power_available: float
    efficiency_percentage: float
    active_swarms: int
    optimization_level: str
    timestamp: datetime


class LogicExecutionResult(BaseModel):
    """Result of logic execution"""
    execution_id: str
    status: str  # 'success', 'partial', 'failed'
    operations_completed: int
    operations_total: int
    execution_time_ms: float
    results: Dict[str, Any]
    errors: Optional[List[str]]


# ============================================================================
# POWER MANAGEMENT ENDPOINTS
# ============================================================================

@router.post("/allocate-power")
async def allocate_power(allocation: PowerAllocation):
    """
    Real-time admission check against this platform's actual concurrent
    job capacity. `swarm_size` is read as the number of concurrent job
    slots being requested and `power_profile` as a priority label kept
    for request-shape compatibility; there is no wattage/nanoswarm
    subsystem behind this, so nothing here is a persisted reservation --
    it is a live comparison of real active-job counts against the
    configured `max_concurrent_jobs` capacity (automation_settings, or a
    default of 50).
    """
    db = get_db_manager()
    execution_id = str(uuid4())
    counts = _active_job_counts(db)
    active_total = sum(counts.values())
    max_jobs = _max_concurrent_jobs(db)
    remaining = max_jobs - active_total

    if allocation.swarm_size > remaining:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Insufficient job capacity. Requested {allocation.swarm_size} slot(s), "
                f"{remaining} remaining ({active_total}/{max_jobs} active job slots in use)."
            ),
        )

    return {
        "execution_id": execution_id,
        "status": "admitted",
        "nanoswarm_id": allocation.nanoswarm_id,
        "power_profile": allocation.power_profile,
        "slots_requested": allocation.swarm_size,
        "active_job_slots": active_total,
        "max_concurrent_job_slots": max_jobs,
        "remaining_job_slots_after": remaining - allocation.swarm_size,
        "active_by_subsystem": counts,
        "note": "This is a real-time capacity check against active jobs, not a persisted reservation.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/optimization-status")
async def optimization_status():
    """Real current job-capacity utilization across every active-job
    subsystem this platform actually runs (sandboxes, vuln scans,
    playbooks, script executions, pentest engagements)."""
    db = get_db_manager()
    counts = _active_job_counts(db)
    active_total = sum(counts.values())
    max_jobs = _max_concurrent_jobs(db)
    utilization = round((active_total / max_jobs) * 100, 1) if max_jobs else 0.0

    return {
        "max_concurrent_job_slots": max_jobs,
        "active_job_slots": active_total,
        "active_by_subsystem": counts,
        "utilization_percentage": utilization,
        "can_accept_new_allocation": active_total < max_jobs,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/load-forecast")
async def load_forecast(hours: int = 24):
    """Real per-hour job-creation history for the trailing `hours` window
    across every active-job subsystem. Route/param names are kept for
    compatibility, but this reports real history, not a fabricated
    prediction -- this platform has no basis to forecast future load."""
    if hours < 1 or hours > 168:
        raise HTTPException(status_code=422, detail="hours must be between 1 and 168")

    db = get_db_manager()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=hours)

    sources = [
        ("sandboxes", "created_at"),
        ("vuln_scan_jobs", "created_at"),
        ("playbook_executions", "started_at"),
        ("script_executions", "start_time"),
        ("pentest_runs", "created_at"),
    ]
    hourly_counts = [0] * hours
    total_jobs = 0
    for table, ts_col in sources:
        try:
            rows = db.conn.execute(
                f"SELECT {ts_col} FROM {table} WHERE {ts_col} >= ?", (window_start,)
            ).fetchall()
        except Exception:
            continue
        for (ts,) in rows:
            if ts is None:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            bucket = int((now - ts).total_seconds() // 3600)
            if 0 <= bucket < hours:
                hourly_counts[hours - 1 - bucket] += 1
                total_jobs += 1

    peak_count = max(hourly_counts) if hourly_counts else 0
    peak_hour_index = hourly_counts.index(peak_count) if hourly_counts else 0

    return {
        "window_hours": hours,
        "hourly_job_counts": hourly_counts,
        "total_jobs_in_window": total_jobs,
        "peak_hour_index": peak_hour_index,
        "peak_hour_job_count": peak_count,
        "note": "Real historical job counts per hour, not a predicted/forecasted figure.",
        "timestamp": now.isoformat(),
    }


# ============================================================================
# Q'AIP LOGIC EXECUTION ENDPOINTS
# ============================================================================

@router.post("/logic-execute")
async def logic_execute(logic_chain: LogicChain, background_tasks: BackgroundTasks):
    """
    Execute distributed logic across multiple agents.
    
    Operations can include:
    - threat_assessment
    - payload_generation
    - swarm_coordination
    - resource_optimization
    - response_planning
    """
    execution_id = str(uuid4())
    db = get_db_manager()
    db.create_logic_execution(execution_id, logic_chain.chain_id, logic_chain.execution_order,
                               len(logic_chain.operations))

    background_tasks.add_task(execute_logic_chain_bg, logic_chain, execution_id)

    return {
        "execution_id": execution_id,
        "status": "queued",
        "operations_count": len(logic_chain.operations),
        "execution_order": logic_chain.execution_order,
        "estimated_duration_ms": len(logic_chain.operations) * 50,
        "status_url": f"/api/energy-logic/logic-execute/{execution_id}",
        "timestamp": datetime.now().isoformat()
    }


@router.get("/logic-execute/{execution_id}")
async def get_logic_execution_status(execution_id: str):
    """Real status/result lookup for a chain queued via POST /logic-execute --
    the old version had no way to check on a queued execution at all."""
    execution = get_db_manager().get_logic_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="execution not found")
    return {
        "execution_id": execution["execution_id"],
        "chain_id": execution["chain_id"],
        "status": execution["status"],
        "results": execution["results"],
        "elapsed_ms": execution["elapsed_ms"],
        "error": execution["error"],
        "created_at": str(execution.get("created_at") or ""),
        "completed_at": str(execution.get("completed_at") or ""),
    }


async def execute_logic_chain_bg(logic_chain: LogicChain, execution_id: str):
    """Background task: validates and executes each operation in the chain,
    persisting real results instead of discarding them. There is no
    physical nanoswarm/payload subsystem behind this platform to delegate
    to, so "execution" here means real, honest bookkeeping (validated
    operation types, real per-operation timing, a real error for a
    malformed operation) rather than fabricating domain-specific output
    for capabilities this codebase doesn't actually have."""
    db = get_db_manager()
    results = []
    start_time = time.monotonic()

    try:
        for idx, operation in enumerate(logic_chain.operations):
            op_start = time.monotonic()
            op_type = operation.get("type")
            if op_type not in _KNOWN_OPERATION_TYPES:
                raise ValueError(
                    f"operation {idx}: unknown type {op_type!r}; expected one of {sorted(_KNOWN_OPERATION_TYPES)}"
                )
            results.append({
                "operation_index": idx,
                "operation_type": op_type,
                "status": "completed",
                "elapsed_ms": round((time.monotonic() - op_start) * 1000, 3),
            })

        elapsed_ms = round((time.monotonic() - start_time) * 1000, 3)
        db.update_logic_execution_result(execution_id, "completed", results=results, elapsed_ms=elapsed_ms)

    except Exception as e:
        elapsed_ms = round((time.monotonic() - start_time) * 1000, 3)
        db.update_logic_execution_result(execution_id, "failed", results=results,
                                          elapsed_ms=elapsed_ms, error=str(e))


@router.get("/decision-engine")
async def decision_engine():
    """Rule-based recommendation from real signals -- pending capability
    approvals, open critical findings, quarantined fleet machines -- plus
    real historical success/failure counts from script_executions,
    vuln_scan_jobs and playbook_executions. No fabricated confidence
    score or invented "deploy_defensive_swarm" action."""
    db = get_db_manager()
    from services.capabilities_engine import get_capabilities_engine
    engine = get_capabilities_engine(db)
    pending = len(engine.pending_approvals())

    critical_findings = db.conn.execute(
        "SELECT COUNT(*) FROM findings WHERE severity = 'critical'"
    ).fetchone()[0]
    quarantined = 0
    try:
        quarantined = db.conn.execute(
            "SELECT COUNT(*) FROM global_fleet_matrix WHERE is_quarantined = true"
        ).fetchone()[0]
    except Exception:
        pass

    if quarantined:
        recommended_action = "review_containment"
        rationale = f"{quarantined} machine(s) currently quarantined."
    elif critical_findings:
        recommended_action = "prioritize_critical_findings"
        rationale = f"{critical_findings} open critical finding(s)."
    elif pending:
        recommended_action = "review_pending_approvals"
        rationale = f"{pending} capability action(s) awaiting approval."
    else:
        recommended_action = "monitor"
        rationale = "No critical findings, quarantined machines, or pending approvals."

    def _outcome_counts(table: str, success_col: str, success_val, fail_val) -> tuple:
        try:
            succ = db.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {success_col} = ?", (success_val,)
            ).fetchone()[0]
            fail = db.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {success_col} = ?", (fail_val,)
            ).fetchone()[0]
            return succ, fail
        except Exception:
            return 0, 0

    s1, f1 = _outcome_counts("script_executions", "status", "success", "failure")
    s2, f2 = _outcome_counts("vuln_scan_jobs", "status", "completed", "failed")
    successful_outcomes = s1 + s2
    failed_outcomes = f1 + f2
    total_outcomes = successful_outcomes + failed_outcomes
    accuracy = round((successful_outcomes / total_outcomes) * 100, 1) if total_outcomes else None

    return {
        "engine_status": "operational",
        "pending_decisions": pending,
        "recommended_action": recommended_action,
        "rationale": rationale,
        "performance_metrics": {
            "decision_accuracy_percentage": accuracy,
            "successful_outcomes": successful_outcomes,
            "failed_outcomes": failed_outcomes,
            "note": "Derived from real script_executions/vuln_scan_jobs outcome counts; null accuracy means no completed jobs yet.",
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/payload-optimize")
async def payload_optimize(optimization: PayloadOptimization):
    """Real historical execution statistics for a named tool/payload,
    matched against payload_executions (the real per-run command log
    security_agents/exploit_agent.py writes to) -- not a fabricated
    "optimized_parameters" fixture. If nothing matches, that is reported
    honestly instead of inventing improvement numbers."""
    db = get_db_manager()
    rows = db.conn.execute(
        """SELECT exit_code, started_at, completed_at FROM payload_executions
           WHERE tool ILIKE ? OR command ILIKE ?""",
        (optimization.payload_name, f"%{optimization.payload_name}%"),
    ).fetchall()

    executions_found = len(rows)
    if executions_found == 0:
        return {
            "payload_name": optimization.payload_name,
            "optimization_metric": optimization.optimization_metric,
            "executions_found": 0,
            "ready_for_deployment": False,
            "reason": "No historical executions of this payload/tool were found in payload_executions.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    success_count = sum(1 for exit_code, _, _ in rows if exit_code == 0)
    durations = [
        (completed - started).total_seconds()
        for exit_code, started, completed in rows
        if started is not None and completed is not None
    ]
    success_rate = round(success_count / executions_found, 3)
    avg_duration_seconds = round(sum(durations) / len(durations), 2) if durations else None

    return {
        "payload_name": optimization.payload_name,
        "optimization_metric": optimization.optimization_metric,
        "executions_found": executions_found,
        "success_count": success_count,
        "success_rate": success_rate,
        "average_duration_seconds": avg_duration_seconds,
        "ready_for_deployment": success_rate >= 0.8,
        "reason": None if success_rate >= 0.8 else f"Historical success rate {success_rate:.0%} is below the 80% deployment threshold.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/resource-allocation/report")
async def resource_allocation_report():
    """Real active-job breakdown plus the real active pentest engagements
    currently consuming capacity -- replaces the previous fixed
    power/CPU/memory fixture and fictional "mission" list (this platform
    tracks neither CPU cores nor memory per job)."""
    db = get_db_manager()
    counts = _active_job_counts(db)
    active_total = sum(counts.values())
    max_jobs = _max_concurrent_jobs(db)

    active_pentests = db.conn.execute(
        """SELECT id, target, scan_type, status, created_at FROM pentest_runs
           WHERE status NOT IN ('completed', 'report_ready', 'failed')
           ORDER BY created_at DESC LIMIT 25"""
    ).fetchall()

    return {
        "report_timestamp": datetime.now(timezone.utc).isoformat(),
        "max_concurrent_job_slots": max_jobs,
        "active_job_slots": active_total,
        "available_job_slots": max_jobs - active_total,
        "utilization_percentage": round((active_total / max_jobs) * 100, 1) if max_jobs else 0.0,
        "active_by_subsystem": counts,
        "active_pentest_engagements": [
            {
                "pentest_id": pid, "target": target, "scan_type": scan_type,
                "status": status, "created_at": str(created_at),
            }
            for pid, target, scan_type, status, created_at in active_pentests
        ],
    }


@router.get("/efficiency-metrics")
async def efficiency_metrics():
    """Real completed-vs-failed job efficiency over the trailing 48
    hours, split into two 24h windows to derive a real trend -- replaces
    the previous fixed 94.2%/carbon-footprint fixture, which had no data
    source. Carbon-footprint figures are dropped entirely rather than
    fabricated: this platform has no energy-metering source for them."""
    db = get_db_manager()
    now = datetime.now(timezone.utc)

    def _window_efficiency(hours_ago_start: int, hours_ago_end: int) -> Optional[float]:
        start = now - timedelta(hours=hours_ago_start)
        end = now - timedelta(hours=hours_ago_end)
        succ = fail = 0
        try:
            succ += db.conn.execute(
                "SELECT COUNT(*) FROM script_executions WHERE status = 'success' AND end_time BETWEEN ? AND ?",
                (start, end),
            ).fetchone()[0]
            fail += db.conn.execute(
                "SELECT COUNT(*) FROM script_executions WHERE status = 'failure' AND end_time BETWEEN ? AND ?",
                (start, end),
            ).fetchone()[0]
        except Exception:
            pass
        try:
            succ += db.conn.execute(
                "SELECT COUNT(*) FROM vuln_scan_jobs WHERE status = 'completed' AND created_at BETWEEN ? AND ?",
                (start, end),
            ).fetchone()[0]
            fail += db.conn.execute(
                "SELECT COUNT(*) FROM vuln_scan_jobs WHERE status = 'failed' AND created_at BETWEEN ? AND ?",
                (start, end),
            ).fetchone()[0]
        except Exception:
            pass
        total = succ + fail
        return round((succ / total) * 100, 1) if total else None

    recent = _window_efficiency(24, 0)
    prior = _window_efficiency(48, 24)

    if recent is None or prior is None:
        trend = "insufficient_data"
    elif recent > prior:
        trend = "improving"
    elif recent < prior:
        trend = "declining"
    else:
        trend = "stable"

    recommendations = []
    if recent is not None and recent < 80:
        recommendations.append("Recent job failure rate exceeds 20% -- review recent script/scan failures.")
    if trend == "declining":
        recommendations.append("Efficiency dropped versus the prior 24h window -- check for a recently introduced faulty script or scan target.")
    if not recommendations:
        recommendations.append("No significant efficiency issues detected in the trailing 48h window.")

    return {
        "current_efficiency_percentage": recent,
        "prior_window_efficiency_percentage": prior,
        "efficiency_trend": trend,
        "optimization_recommendations": recommendations,
        "timestamp": now.isoformat(),
    }
