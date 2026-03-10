"""
Dead-letter queue for permanently failed jobs.
"""

from datetime import datetime, timezone
from typing import Optional
import logging

logger = logging.getLogger("openclaw.dlq")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_supabase():
    from supabase_client import get_client
    return get_client()


def send_to_dlq(
    job_id: str,
    failure_reason: str,
    last_error: str = "",
    attempt_count: int = 1,
    cost_total: float = 0.0,
    metadata: dict = None,
) -> bool:
    """
    Move a job to the dead-letter queue.
    Returns True on success, False if DLQ write failed (non-fatal).
    """
    try:
        sb = _get_supabase()
        if not sb:
            return False
        sb.table("dead_letter_queue").insert({
            "job_id": job_id,
            "failure_reason": failure_reason,
            "last_error": (last_error or "")[:2000],
            "attempt_count": int(attempt_count or 1),
            "cost_total": round(float(cost_total or 0.0), 6),
            "dlq_at": _now_iso(),
            "metadata": metadata or {},
        }).execute()
        logger.warning("[DLQ] Job %s sent to DLQ: %s", job_id, failure_reason)
        return True
    except Exception as exc:
        logger.error("[DLQ] Failed to write %s to DLQ: %s", job_id, exc)
        return False


def retry_from_dlq(job_id: str) -> bool:
    """
    Re-queue a DLQ job back to pending.
    Increments retry_count, updates last_retry_at.
    """
    try:
        from job_manager import update_job_status

        sb = _get_supabase()
        if not sb:
            return False

        latest = (
            sb.table("dead_letter_queue")
            .select("*")
            .eq("job_id", job_id)
            .eq("resolved", False)
            .order("dlq_at", desc=True)
            .limit(1)
            .execute()
        )
        if not latest.data:
            return False

        row = latest.data[0]
        retry_count = int(row.get("retry_count", 0) or 0) + 1
        sb.table("dead_letter_queue").update({
            "retry_count": retry_count,
            "last_retry_at": _now_iso(),
        }).eq("id", row.get("id")).execute()

        update_job_status(job_id, "pending", error=None, started_at=None, completed_at=None)
        logger.info("[DLQ] Job %s re-queued from DLQ", job_id)
        return True
    except Exception as exc:
        logger.error("[DLQ] Failed to retry %s: %s", job_id, exc)
        return False


def resolve_dlq(job_id: str) -> bool:
    """Mark unresolved DLQ entries for a job as resolved."""
    try:
        sb = _get_supabase()
        if not sb:
            return False
        sb.table("dead_letter_queue").update({
            "resolved": True,
            "resolved_at": _now_iso(),
        }).eq("job_id", job_id).eq("resolved", False).execute()
        return True
    except Exception as exc:
        logger.error("[DLQ] Failed to resolve %s: %s", job_id, exc)
        return False


def get_dlq_jobs(limit: int = 50, unresolved_only: bool = True) -> list:
    """Fetch DLQ entries for dashboard/monitoring."""
    try:
        sb = _get_supabase()
        if not sb:
            return []
        query = sb.table("dead_letter_queue").select("*").order("dlq_at", desc=True).limit(limit)
        if unresolved_only:
            query = query.eq("resolved", False)
        result = query.execute()
        return result.data or []
    except Exception as exc:
        logger.error("[DLQ] Failed to fetch DLQ: %s", exc)
        return []


def record_attempt_start(job_id: str, execution_id: str, attempt_num: int) -> bool:
    """Insert a job attempt row. Non-fatal."""
    try:
        sb = _get_supabase()
        if not sb:
            return False
        sb.table("job_attempts").insert({
            "job_id": job_id,
            "attempt_num": int(attempt_num),
            "execution_id": execution_id,
            "started_at": _now_iso(),
            "outcome": "running",
        }).execute()
        return True
    except Exception as exc:
        logger.debug("[DLQ] attempt start failed for %s: %s", job_id, exc)
        return False


def record_attempt_finish(
    job_id: str,
    execution_id: str,
    *,
    outcome: str,
    cost: float = 0.0,
    error: str = "",
    phase_reached: str = "",
) -> bool:
    """Update an existing attempt row with terminal metadata. Non-fatal."""
    try:
        sb = _get_supabase()
        if not sb:
            return False
        sb.table("job_attempts").update({
            "finished_at": _now_iso(),
            "outcome": outcome,
            "cost": round(float(cost or 0.0), 6),
            "error": (error or "")[:2000] if error else "",
            "phase_reached": phase_reached or "",
        }).eq("job_id", job_id).eq("execution_id", execution_id).execute()
        return True
    except Exception as exc:
        logger.debug("[DLQ] attempt finish failed for %s: %s", job_id, exc)
        return False


def get_next_attempt_num(job_id: str) -> int:
    """Compute next attempt number from persisted attempts. Defaults to 1."""
    try:
        sb = _get_supabase()
        if not sb:
            return 1
        result = (
            sb.table("job_attempts")
            .select("attempt_num")
            .eq("job_id", job_id)
            .order("attempt_num", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return 1
        return int(result.data[0].get("attempt_num", 0) or 0) + 1
    except Exception:
        return 1
