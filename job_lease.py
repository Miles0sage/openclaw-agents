"""
Atomic job leases for OpenClaw queue execution.

Lease flow:
1. acquire_lease() atomically transitions a pending job to running with execution_id
2. JobLease heartbeat keeps lease_expires_at fresh while the runner is alive
3. mark_completed()/mark_failed() finalize only when execution_id still matches
4. reclaim_stale_leases() resets expired running jobs for crash recovery
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger("openclaw.job_lease")

LEASE_DURATION_SECONDS = 300
HEARTBEAT_INTERVAL_SECONDS = 60


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_rows(response: Any) -> list[dict]:
    rows = getattr(response, "data", None)
    return rows if isinstance(rows, list) else []


class JobLease:
    """Holds a lease on one job and sends periodic heartbeat updates."""

    def __init__(self, job_id: str, execution_id: str, supabase_client):
        self.job_id = job_id
        self.execution_id = execution_id
        self._client = supabase_client
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._released = False

    async def start_heartbeat(self):
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self):
        while not self._released:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            if self._released:
                break
            try:
                await self._send_heartbeat()
            except Exception as err:
                logger.warning("Heartbeat failed for %s: %s", self.job_id, err)

    async def _send_heartbeat(self):
        new_expiry = (
            datetime.now(timezone.utc) + timedelta(seconds=LEASE_DURATION_SECONDS)
        ).isoformat()
        response = (
            self._client.table("jobs")
            .update({"lease_expires_at": new_expiry})
            .eq("id", self.job_id)
            .eq("execution_id", self.execution_id)
            .eq("status", "running")
            .execute()
        )
        if not _extract_rows(response):
            logger.error("Heartbeat lost lease on %s", self.job_id)
            self._released = True

    async def release(self):
        self._released = True
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass


async def acquire_lease(job_id: str, supabase_client) -> Optional[JobLease]:
    """
    Atomically acquire a lease for a pending job.

    Returns:
        JobLease on success, None when already leased/taken.
    """
    if not supabase_client:
        logger.error("Cannot acquire lease for %s: Supabase client unavailable", job_id)
        return None

    execution_id = str(uuid.uuid4())
    lease_expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=LEASE_DURATION_SECONDS)
    ).isoformat()

    try:
        response = (
            supabase_client.table("jobs")
            .update(
                {
                    "status": "running",
                    "execution_id": execution_id,
                    "lease_expires_at": lease_expires_at,
                    "started_at": _utc_now_iso(),
                    "error": None,
                }
            )
            .eq("id", job_id)
            .eq("status", "pending")
            .execute()
        )
    except Exception as err:
        logger.error("Failed to acquire lease on %s: %s", job_id, err)
        return None

    if not _extract_rows(response):
        logger.debug("Lease not acquired for %s (already taken or not pending)", job_id)
        return None

    lease = JobLease(job_id=job_id, execution_id=execution_id, supabase_client=supabase_client)
    await lease.start_heartbeat()
    logger.info("Acquired lease on %s with execution_id=%s", job_id, execution_id)
    return lease


async def mark_completed(
    job_id: str,
    execution_id: str,
    result: dict,
    supabase_client,
    *,
    final_status: str = "done",
    extra_updates: Optional[dict] = None,
) -> bool:
    """
    Mark a job terminal-success only if execution_id still matches.
    """
    if not supabase_client:
        return False

    updates = {
        "status": final_status,
        "completed_at": _utc_now_iso(),
        "lease_expires_at": None,
        "execution_id": None,
    }
    if isinstance(extra_updates, dict):
        updates.update(extra_updates)

    try:
        response = (
            supabase_client.table("jobs")
            .update(updates)
            .eq("id", job_id)
            .eq("execution_id", execution_id)
            .execute()
        )
    except Exception as err:
        logger.error("Failed to mark %s completed: %s", job_id, err)
        return False

    if not _extract_rows(response):
        logger.error(
            "Lease mismatch while completing %s (execution_id=%s)",
            job_id,
            execution_id,
        )
        return False
    return True


async def mark_failed(
    job_id: str,
    execution_id: str,
    error: str,
    supabase_client,
    *,
    final_status: str = "failed",
    extra_updates: Optional[dict] = None,
) -> bool:
    """
    Mark a job terminal-failed only if execution_id still matches.
    """
    if not supabase_client:
        return False

    updates = {
        "status": final_status,
        "error": error,
        "completed_at": _utc_now_iso(),
        "lease_expires_at": None,
        "execution_id": None,
    }
    if isinstance(extra_updates, dict):
        updates.update(extra_updates)

    try:
        response = (
            supabase_client.table("jobs")
            .update(updates)
            .eq("id", job_id)
            .eq("execution_id", execution_id)
            .execute()
        )
    except Exception as err:
        logger.error("Failed to mark %s failed: %s", job_id, err)
        return False

    return bool(_extract_rows(response))


async def reclaim_stale_leases(supabase_client) -> int:
    """
    Requeue running jobs whose lease has expired.
    """
    if not supabase_client:
        return 0
    try:
        response = (
            supabase_client.table("jobs")
            .update(
                {
                    "status": "pending",
                    "execution_id": None,
                    "lease_expires_at": None,
                    "started_at": None,
                }
            )
            .eq("status", "running")
            .lt("lease_expires_at", _utc_now_iso())
            .execute()
        )
    except Exception as err:
        logger.error("Failed to reclaim stale leases: %s", err)
        return 0

    rows = _extract_rows(response)
    if rows:
        logger.warning("Reclaimed %s stale lease(s)", len(rows))
    return len(rows)
