"""
Autonomous Job Queue Manager for OpenClaw
==========================================
Manages job lifecycle: pending -> analyzing -> code_generated -> pr_ready -> done
Source of truth: Supabase (real-time, queryable, multi-device)
JSONL: audit mirror only (never used for queue dispatch decisions)
"""

import fcntl
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
import logging

logger = logging.getLogger("job_manager")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")
JOBS_DIR = Path(os.path.join(DATA_DIR, "jobs"))
JOBS_DIR.mkdir(parents=True, exist_ok=True)
JOBS_FILE = JOBS_DIR / "jobs.jsonl"

# ---------------------------------------------------------------------------
# Supabase backend
# ---------------------------------------------------------------------------

def _sb():
    """Lazy import supabase_client to avoid circular imports."""
    try:
        from supabase_client import table_insert, table_select, table_update, table_delete, is_connected
        return {
            "insert": table_insert,
            "select": table_select,
            "update": table_update,
            "delete": table_delete,
            "connected": is_connected,
        }
    except Exception:
        return None


def _use_supabase() -> bool:
    """Check if Supabase is available and connected."""
    try:
        sb = _sb()
        return sb is not None and sb["connected"]()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JSONL audit mirror (not queue source of truth)
# ---------------------------------------------------------------------------

def _locked_read_jobs() -> list:
    """Read all jobs from JSONL with file locking."""
    if not JOBS_FILE.exists():
        return []
    with open(JOBS_FILE, "r") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            return [json.loads(line) for line in f if line.strip()]
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _locked_write_jobs(jobs: list):
    """Write all jobs to JSONL with exclusive file locking."""
    # AUDIT LOG ONLY — not source of truth for job state
    with open(JOBS_FILE, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            for job in jobs:
                f.write(json.dumps(job) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _locked_append_job(job_dict: dict):
    """Append a single job to JSONL with exclusive file locking."""
    # AUDIT LOG ONLY — not source of truth for job state
    with open(JOBS_FILE, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(json.dumps(job_dict) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}
VALID_PROJECTS = {
    "barber-crm", "openclaw", "delhi-palace",
    "prestress-calc", "concrete-canoe",
}


class JobValidationError(ValueError):
    """Raised when job input fails validation."""
    pass


def validate_job(project: str, task: str, priority: str = "P1") -> None:
    """Validate job inputs. Raises JobValidationError on bad input."""
    if not task or not task.strip():
        raise JobValidationError("Task description cannot be empty")
    if len(task) > 5000:
        raise JobValidationError(f"Task too long ({len(task)} chars, max 5000)")
    if priority not in VALID_PRIORITIES:
        raise JobValidationError(f"Invalid priority '{priority}', must be one of {VALID_PRIORITIES}")
    if project and project not in VALID_PROJECTS:
        raise JobValidationError(
            f"Unknown project '{project}', must be one of {VALID_PROJECTS}"
        )


# ---------------------------------------------------------------------------
# Job model
# ---------------------------------------------------------------------------

class Job:
    def __init__(self, project: str, task: str, priority: str = "P1", api_key_id: str = ""):
        self.id = f"job-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"
        self.project = project
        self.task = task
        self.priority = priority
        self.api_key_id = api_key_id or ""
        self.status = "pending"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.pr_url = None
        self.branch_name = None
        self.approved_by = None
        self.completed_at = None
        self.analysis = {}
        self.generated_code = {}

    def to_dict(self):
        return {
            "id": self.id,
            "project": self.project,
            "task": self.task,
            "priority": self.priority,
            "api_key_id": self.api_key_id,
            "status": self.status,
            "created_at": self.created_at,
            "pr_url": self.pr_url,
            "branch_name": self.branch_name,
            "approved_by": self.approved_by,
            "completed_at": self.completed_at,
        }


# ---------------------------------------------------------------------------
# CRUD operations (Supabase-first, JSONL fallback)
# ---------------------------------------------------------------------------

def create_job(project: str, task: str, priority: str = "P1", api_key_id: str = "") -> Job:
    """Create a new job and add to queue."""
    validate_job(project, task, priority)
    job = Job(project, task, priority, api_key_id=api_key_id)
    job_dict = job.to_dict()
    job_dict["idempotency_key"] = job_dict["id"]

    if not _use_supabase():
        # AUDIT LOG ONLY — not source of truth for job state
        _locked_append_job(job_dict)
        raise RuntimeError("Supabase is required for queue state; refusing JSONL queue fallback")

    sb = _sb()
    insert_payload = {
        "id": job_dict["id"],
        "project": job_dict["project"],
        "task": job_dict["task"],
        "priority": job_dict["priority"],
        "api_key_id": job_dict.get("api_key_id") or None,
        "status": job_dict["status"],
        "created_at": job_dict["created_at"],
        "idempotency_key": job_dict["idempotency_key"],
    }
    result = sb["insert"]("jobs", insert_payload)
    if not result:
        # Migration not applied yet? Retry once with minimal columns.
        result = sb["insert"]("jobs", {
            "id": job_dict["id"],
            "project": job_dict["project"],
            "task": job_dict["task"],
            "priority": job_dict["priority"],
            "status": job_dict["status"],
            "created_at": job_dict["created_at"],
        })
    if not result:
        # AUDIT LOG ONLY — not source of truth for job state
        _locked_append_job(job_dict)
        raise RuntimeError("Supabase insert failed while creating job")
    logger.info(f"Job created (Supabase): {job.id}")

    return job


def get_job(job_id: str) -> dict:
    """Get job by ID."""
    if _use_supabase():
        sb = _sb()
        rows = sb["select"]("jobs", f"id=eq.{job_id}", limit=1)
        if rows:
            return rows[0]
    # Fallback
    for job in _locked_read_jobs():
        if job["id"] == job_id:
            return job
    return None


def get_pending_jobs(limit: int = 10):
    """Get pending jobs from Supabase only (single source of truth)."""
    if not _use_supabase():
        logger.error("Supabase unavailable; queue dispatch disabled (no JSONL fallback)")
        return []

    sb = _sb()
    rows = sb["select"](
        "jobs",
        "status=eq.pending&order=priority.asc,created_at.asc",
        limit=limit,
    )
    return rows or []


def update_job_status(
    job_id: str,
    status: str,
    execution_id: str = "",
    require_lease: bool = False,
    **kwargs,
) -> bool:
    """Update job status."""
    now = datetime.now(timezone.utc).isoformat()
    updates = {"status": status, "updated_at": now}
    updates.update(kwargs)

    if status in ("approved", "merged", "done"):
        updates["completed_at"] = now
    if status == "analyzing":
        updates["started_at"] = now

    if _use_supabase():
        sb = _sb()
        match = f"id=eq.{job_id}"
        if require_lease:
            if not execution_id:
                logger.error(
                    "Refusing lease-guarded update for %s -> %s: missing execution_id",
                    job_id,
                    status,
                )
                return False
            match = f"{match}&execution_id=eq.{execution_id}"
        result = sb["update"]("jobs", match, updates)
        if result:
            logger.info(f"Job {job_id} -> {status} (Supabase)")
            return True
        if require_lease:
            logger.warning(
                "Lease-guarded status update failed for %s -> %s (execution_id mismatch?)",
                job_id,
                status,
            )
            return False
        logger.warning(f"Supabase update failed for {job_id}, writing audit JSONL only")

    # AUDIT LOG ONLY — not source of truth for job state
    if not JOBS_FILE.exists():
        return False
    with open(JOBS_FILE, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            jobs = [json.loads(line) for line in f if line.strip()]
            for job in jobs:
                if job["id"] == job_id:
                    job.update(updates)
            f.seek(0)
            f.truncate()
            for job in jobs:
                f.write(json.dumps(job) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    logger.info(f"Job {job_id} -> {status} (JSONL)")
    return True


def list_jobs(status: str = "all", *, limit: int = 200, offset: int = 0, project: str | None = None):
    """List jobs, optionally filtered by status/project."""
    if _use_supabase():
        sb = _sb()
        query = "order=created_at.desc"
        if status != "all":
            query = f"status=eq.{status}&{query}"
        if project:
            query = f"project=eq.{project}&{query}"
        if offset:
            query = f"{query}&offset={offset}"
        rows = sb["select"]("jobs", query, limit=limit)
        if rows is not None:
            return rows

    # Fallback
    jobs = _locked_read_jobs()
    if status != "all":
        jobs = [j for j in jobs if j.get("status") == status]
    if project:
        jobs = [j for j in jobs if j.get("project") == project]
    jobs = sorted(jobs, key=lambda x: x.get("created_at", ""), reverse=True)
    if offset:
        jobs = jobs[offset:]
    if limit:
        jobs = jobs[:limit]
    return jobs


def set_kill_flag(job_id: str) -> bool:
    """Set kill flag on a job (used by kill_job MCP tool)."""
    update_job_status(job_id, "killed_manual")
    return True


if __name__ == "__main__":
    job = create_job("openclaw", "Test Supabase job manager", "P3")
    print(f"Created job: {job.id}")
    fetched = get_job(job.id)
    print(f"Fetched: {fetched['id']} status={fetched['status']}")
    update_job_status(job.id, "done")
    fetched = get_job(job.id)
    print(f"After update: status={fetched['status']}")
