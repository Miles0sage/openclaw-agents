"""
OpenClaw Client Intake API Routes

Endpoints for the client-facing job intake portal:
- POST /api/intake         — Submit a new job
- GET  /api/jobs           — List all jobs (with filters)
- GET  /api/jobs/{job_id}  — Get single job details
- GET  /api/jobs/{id}/progress — Detailed progress log
- DELETE /api/jobs/{job_id} — Cancel a job
- GET  /api/intake/stats   — Dashboard statistics
"""

from fastapi import APIRouter, HTTPException, Query, Path, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import json
import os
import uuid
import logging
from datetime import datetime, timezone
from client_auth import authenticate_client, can_submit_job, deduct_job_credit

router = APIRouter(tags=["intake"])
logger = logging.getLogger("openclaw_intake")

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "os.environ.get("OPENCLAW_DATA_DIR", "./data")")
INTAKE_FILE = os.path.join(DATA_DIR, "jobs", "intake.json")

VALID_TASK_TYPES = {
    "feature_build", "bug_fix", "security_audit",
    "code_review", "deployment", "full_project", "other",
}
VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}
VALID_STATUSES = {
    "queued", "researching", "planning", "executing",
    "reviewing", "delivering", "done", "failed", "cancelled",
}
ACTIVE_STATUSES = {"queued", "researching", "planning", "executing", "reviewing", "delivering"}

PHASE_ORDER = ["queued", "researching", "planning", "executing", "reviewing", "delivering", "done"]

# Agent assignment heuristic (maps task_type -> default agent)
AGENT_MAP = {
    "feature_build": "CodeGen Pro",
    "bug_fix": "CodeGen Pro",
    "security_audit": "Pentest AI",
    "code_review": "CodeGen Elite",
    "deployment": "Overseer",
    "full_project": "Overseer",
    "other": "Overseer",
}


def _load_jobs() -> Dict[str, Any]:
    """Load all jobs from the intake JSON file."""
    if not os.path.exists(INTAKE_FILE):
        return {}
    try:
        with open(INTAKE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        logger.warning("Corrupt intake file, resetting")
        return {}


def _save_jobs(jobs: Dict[str, Any]) -> None:
    """Persist all jobs to the intake JSON file (atomic write)."""
    tmp = INTAKE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(jobs, f, indent=2, default=str)
    os.replace(tmp, INTAKE_FILE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class IntakeRequest(BaseModel):
    project_name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=10, max_length=10000)
    task_type: str = Field(..., description="One of: feature_build, bug_fix, security_audit, code_review, deployment, full_project, other")
    priority: str = Field(default="P2", description="P0 (Critical), P1 (High), P2 (Medium), P3 (Low)")
    budget_limit: Optional[float] = Field(default=None, ge=0, description="Maximum budget in USD")
    contact_email: Optional[str] = Field(default=None, max_length=200)


class IntakeResponse(BaseModel):
    job_id: str
    status: str
    estimated_start: str
    message: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/api/intake", response_model=IntakeResponse)
async def submit_intake(req: IntakeRequest, request: Request) -> IntakeResponse:
    """
    Accept a new client job submission.

    Requires X-Client-Key header for authentication.
    Validates input, creates a job record with status 'queued',
    assigns a default agent based on task type, and returns the job ID.
    """
    # Extract and validate X-Client-Key header
    client_key = request.headers.get("X-Client-Key")
    if not client_key:
        raise HTTPException(
            status_code=401,
            detail="Missing X-Client-Key header",
        )
    
    # Authenticate the client
    client = authenticate_client(client_key)
    if not client:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired X-Client-Key",
        )
    
    client_id = client.get("client_id")

    # Optional per-key API quota enforcement (set by gateway middleware).
    api_key_record = getattr(request.state, "api_key", None)
    if api_key_record:
        try:
            from api_auth import check_job_quota
            await check_job_quota(api_key_record)
        except Exception as quota_err:
            raise HTTPException(status_code=429, detail=str(quota_err)) from quota_err
    
    # Check if client can submit a job (respects plan limits and billing cycle)
    can_submit, reason = can_submit_job(client)
    if not can_submit:
        raise HTTPException(
            status_code=402,
            detail=f"Cannot submit job: {reason}",
        )
    
    # Validate enums
    if req.task_type not in VALID_TASK_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid task_type '{req.task_type}'. Must be one of: {', '.join(sorted(VALID_TASK_TYPES))}",
        )
    if req.priority not in VALID_PRIORITIES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid priority '{req.priority}'. Must be one of: P0, P1, P2, P3",
        )

    jobs = _load_jobs()
    job_id = str(uuid.uuid4())
    now = _now_iso()

    # Estimate start based on queue depth and priority
    active_count = sum(1 for j in jobs.values() if j.get("status") in ACTIVE_STATUSES)
    priority_minutes = {"P0": 1, "P1": 5, "P2": 15, "P3": 30}
    wait_minutes = (active_count * 3) + priority_minutes.get(req.priority, 15)

    job = {
        "job_id": job_id,
        "client_id": client_id,
        "project_name": req.project_name,
        "description": req.description,
        "task_type": req.task_type,
        "priority": req.priority,
        "budget_limit": req.budget_limit,
        "contact_email": req.contact_email,
        "status": "queued",
        "assigned_agent": AGENT_MAP.get(req.task_type, "Overseer"),
        "cost_so_far": 0.0,
        "created_at": now,
        "updated_at": now,
        "phases_completed": [],
        "current_phase": "queued",
        "logs": [
            {"timestamp": now, "message": f"Job created — {req.task_type} / {req.priority}"},
            {"timestamp": now, "message": f"Assigned to {AGENT_MAP.get(req.task_type, 'Overseer')}"},
        ],
        "cost_breakdown": {},
    }
    jobs[job_id] = job
    _save_jobs(jobs)

    # Deduct credit from client for job submission
    deduct_success = deduct_job_credit(client_id)
    if deduct_success:
        logger.info("Credit deducted for job %s from client %s", job_id[:8], client_id[:8])
        job["logs"].append({"timestamp": _now_iso(), "message": "Credit deducted from account"})
        _save_jobs(jobs)
    else:
        logger.warning("Failed to deduct credit for job %s from client %s", job_id[:8], client_id[:8])

    # Also register with job_manager so the autonomous runner picks it up
    try:
        from job_manager import create_job as jm_create_job
        jm_job = jm_create_job(
            req.project_name,
            req.description,
            req.priority,
            api_key_id=api_key_record.get("id", "") if isinstance(api_key_record, dict) else "",
        )
        job["jm_job_id"] = jm_job.id
        _save_jobs(jobs)
        logger.info("Registered with job_manager as %s", jm_job.id)
        if isinstance(api_key_record, dict) and api_key_record.get("id"):
            try:
                from api_auth import increment_usage
                increment_usage(api_key_record["id"], is_job=True)
            except Exception:
                pass
    except Exception as e:
        logger.warning("Failed to register with job_manager: %s", e)

    # Signal the autonomous runner to wake up immediately (event-driven, no poll delay)
    try:
        import gateway as _gw
        runner = getattr(_gw, "runner", None)
        if runner is not None and hasattr(runner, "notify_new_job"):
            runner.notify_new_job()
            logger.debug("Runner signaled for new job %s", job_id[:8])
    except Exception as e:
        logger.debug("Could not signal runner (non-fatal): %s", e)

    logger.info("New intake job %s — %s (%s)", job_id[:8], req.project_name, req.task_type)

    estimated = f"~{wait_minutes} minutes" if wait_minutes > 0 else "immediately"

    return IntakeResponse(
        job_id=job_id,
        status="queued",
        estimated_start=estimated,
        message=f"Job queued successfully. Assigned to {job['assigned_agent']}.",
    )


@router.get("/api/jobs")
async def list_jobs(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """
    List all jobs with optional status filter and pagination.

    Merges jobs from both the intake portal (intake.json) and the
    autonomous runner (jobs.jsonl) into a single unified list, sorted
    by creation time (newest first).
    """
    # --- Source 1: Intake portal jobs ---
    intake_jobs = _load_jobs()

    # --- Source 2: Runner/MCP jobs from jobs.jsonl ---
    jsonl_path = os.path.join(DATA_DIR, "jobs", "jobs.jsonl")
    runner_jobs: Dict[str, Any] = {}
    if os.path.exists(jsonl_path):
        try:
            with open(jsonl_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    j = json.loads(line)
                    jid = j.get("id", j.get("job_id", ""))
                    runner_jobs[jid] = j
        except (json.JSONDecodeError, IOError):
            logger.warning("Error reading jobs.jsonl, skipping runner jobs")

    # --- Normalise runner jobs to the same summary shape ---
    def _normalise_runner(j: dict) -> dict:
        return {
            "job_id": j.get("id", j.get("job_id", "")),
            "project_name": j.get("project", j.get("project_name", "unknown")),
            "description": (j.get("task", j.get("description", "")))[:200],
            "task_type": j.get("task_type", "other"),
            "priority": j.get("priority", "P2"),
            "status": j.get("status", "unknown"),
            "assigned_agent": j.get("assigned_agent"),
            "cost_so_far": j.get("cost_so_far", 0.0),
            "budget_limit": j.get("budget_limit"),
            "contact_email": j.get("contact_email"),
            "created_at": j.get("created_at", ""),
            "updated_at": j.get("updated_at", j.get("completed_at", j.get("created_at", ""))),
        }

    # Merge: intake jobs take priority if same ID exists in both
    merged: Dict[str, dict] = {}
    for jid, j in runner_jobs.items():
        merged[jid] = _normalise_runner(j)
    for jid, j in intake_jobs.items():
        merged[jid] = j  # intake overwrites runner if duplicate

    all_jobs = sorted(merged.values(), key=lambda j: j.get("created_at", ""), reverse=True)

    if status:
        all_jobs = [j for j in all_jobs if j.get("status") == status]

    total = len(all_jobs)
    page = all_jobs[offset : offset + limit]

    return {"jobs": page, "total": total, "limit": limit, "offset": offset}


@router.get("/api/jobs/{job_id}")
async def get_job(job_id: str = Path(..., description="The job UUID")) -> Dict[str, Any]:
    """
    Get full details for a single job including logs and cost breakdown.
    """
    jobs = _load_jobs()
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@router.get("/api/jobs/{job_id}/progress")
async def get_job_progress(job_id: str = Path(..., description="The job UUID")) -> Dict[str, Any]:
    """
    Get detailed progress information for a job.

    Returns phases completed, current phase, execution logs,
    and per-agent cost breakdown.
    """
    jobs = _load_jobs()
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    current_idx = PHASE_ORDER.index(job["status"]) if job["status"] in PHASE_ORDER else -1

    return {
        "job_id": job_id,
        "status": job["status"],
        "current_phase": job.get("current_phase", job["status"]),
        "phases_completed": job.get("phases_completed", []),
        "phases_remaining": PHASE_ORDER[current_idx + 1:] if current_idx >= 0 else [],
        "progress_pct": round((current_idx / (len(PHASE_ORDER) - 1)) * 100) if current_idx >= 0 else 0,
        "assigned_agent": job.get("assigned_agent"),
        "cost_so_far": job.get("cost_so_far", 0.0),
        "cost_breakdown": job.get("cost_breakdown", {}),
        "logs": job.get("logs", []),
        "created_at": job["created_at"],
        "updated_at": job.get("updated_at", job["created_at"]),
    }


@router.delete("/api/jobs/{job_id}")
async def cancel_job(job_id: str = Path(..., description="The job UUID")) -> Dict[str, Any]:
    """
    Cancel an active job.

    Only jobs in active statuses (queued through delivering) can be cancelled.
    Completed, failed, or already cancelled jobs cannot be cancelled.
    """
    jobs = _load_jobs()
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    if job["status"] not in ACTIVE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel job in '{job['status']}' status",
        )

    now = _now_iso()
    old_status = job["status"]
    job["status"] = "cancelled"
    job["current_phase"] = "cancelled"
    job["updated_at"] = now
    job["logs"].append({"timestamp": now, "message": "Job cancelled by client"})
    _save_jobs(jobs)

    logger.info("Job %s cancelled", job_id[:8])

    # Trigger email notification (non-blocking)
    try:
        from email_notifications import notify_status_change
        notify_status_change(job_id, old_status, "cancelled", job)
    except Exception as e:
        logger.error("Failed to trigger email notification: %s", e)

    return {"job_id": job_id, "status": "cancelled", "message": "Job cancelled successfully"}


@router.get("/api/intake/stats")
async def intake_stats() -> Dict[str, Any]:
    """
    Dashboard statistics: total jobs, breakdown by status,
    total cost incurred, and average completion time.
    """
    jobs = _load_jobs()
    all_jobs = list(jobs.values())

    status_counts = {}
    for j in all_jobs:
        s = j.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    total_cost = sum(j.get("cost_so_far", 0.0) for j in all_jobs)

    # Calculate average completion time for done jobs
    done_jobs = [j for j in all_jobs if j.get("status") == "done"]
    avg_completion_seconds = 0.0
    if done_jobs:
        durations = []
        for j in done_jobs:
            try:
                start = datetime.fromisoformat(j["created_at"])
                end = datetime.fromisoformat(j.get("updated_at", j["created_at"]))
                durations.append((end - start).total_seconds())
            except (ValueError, KeyError):
                pass
        if durations:
            avg_completion_seconds = sum(durations) / len(durations)

    active_count = sum(1 for j in all_jobs if j.get("status") in ACTIVE_STATUSES)

    return {
        "total_jobs": len(all_jobs),
        "active_jobs": active_count,
        "completed_jobs": status_counts.get("done", 0),
        "failed_jobs": status_counts.get("failed", 0),
        "cancelled_jobs": status_counts.get("cancelled", 0),
        "total_cost": round(total_cost, 2),
        "avg_completion_seconds": round(avg_completion_seconds, 1),
        "by_status": status_counts,
        "by_priority": _count_by(all_jobs, "priority"),
        "by_task_type": _count_by(all_jobs, "task_type"),
    }


# ---------------------------------------------------------------------------
# HTML route — serve the portal
# ---------------------------------------------------------------------------

@router.get("/client-portal", response_class=HTMLResponse)
async def serve_portal():
    """Serve the client intake portal HTML."""
    portal_path = os.path.join(os.path.dirname(__file__), "client_portal.html")
    if not os.path.exists(portal_path):
        raise HTTPException(status_code=500, detail="Portal HTML file not found")
    with open(portal_path, "r") as f:
        return HTMLResponse(content=f.read())


# ---------------------------------------------------------------------------
# Internal helpers (called by other modules to update job state)
# ---------------------------------------------------------------------------

def update_job_status(job_id: str, status: str, log_message: str = None, cost_delta: float = 0.0, agent: str = None) -> bool:
    """
    Update a job's status and optionally append a log entry.

    Called by the orchestrator/agents to advance job state.
    Returns True if the job was found and updated, False otherwise.
    """
    if status not in VALID_STATUSES:
        logger.error("Invalid status '%s' for job %s", status, job_id[:8])
        return False

    jobs = _load_jobs()
    if job_id not in jobs:
        logger.warning("Job %s not found for status update", job_id[:8])
        return False

    job = jobs[job_id]
    now = _now_iso()

    # Track phase completion
    old_status = job["status"]
    if old_status in PHASE_ORDER and old_status != status:
        completed = job.get("phases_completed", [])
        if old_status not in completed:
            completed.append(old_status)
        job["phases_completed"] = completed

    job["status"] = status
    job["current_phase"] = status
    job["updated_at"] = now

    if cost_delta > 0:
        job["cost_so_far"] = round(job.get("cost_so_far", 0.0) + cost_delta, 4)
        breakdown = job.get("cost_breakdown", {})
        agent_name = agent or job.get("assigned_agent", "unknown")
        breakdown[agent_name] = round(breakdown.get(agent_name, 0.0) + cost_delta, 4)
        job["cost_breakdown"] = breakdown

    if agent:
        job["assigned_agent"] = agent

    if log_message:
        job["logs"].append({"timestamp": now, "message": log_message})

    _save_jobs(jobs)
    logger.info("Job %s: %s -> %s", job_id[:8], old_status, status)

    # Trigger email notification (non-blocking)
    try:
        from email_notifications import notify_status_change
        notify_status_change(job_id, old_status, status, job)
    except Exception as e:
        logger.error("Failed to trigger email notification: %s", e)

    return True


def append_job_log(job_id: str, message: str) -> bool:
    """Append a log entry to a job without changing status."""
    jobs = _load_jobs()
    if job_id not in jobs:
        return False
    jobs[job_id]["logs"].append({"timestamp": _now_iso(), "message": message})
    jobs[job_id]["updated_at"] = _now_iso()
    _save_jobs(jobs)
    return True


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _count_by(jobs: list, key: str) -> Dict[str, int]:
    counts = {}
    for j in jobs:
        v = j.get(key, "unknown")
        counts[v] = counts.get(v, 0) + 1
    return counts
