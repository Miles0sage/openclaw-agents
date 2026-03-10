"""
PC Dispatch Router — FastAPI routes for sending tasks to Miles' PC via SSH.

Endpoints:
  POST /api/dispatch/pc — Create and dispatch a Claude Code task
  POST /api/dispatch/ollama — Dispatch an Ollama inference task
  GET /api/dispatch/status/{job_id} — Check job status
  GET /api/dispatch/pc/health — Check PC connectivity
  GET /api/dispatch/jobs — List all jobs
"""

import logging
import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from datetime import datetime, timezone

from pc_dispatcher import (
    create_pc_job,
    get_pc_job,
    list_pc_jobs,
    check_pc_health,
    execute_job_background,
)

logger = logging.getLogger("openclaw.routers.dispatch")

router = APIRouter(prefix="/api/dispatch", tags=["dispatch"])


# ═══════════════════════════════════════════════════════════════════════════
# Request/Response Models
# ═══════════════════════════════════════════════════════════════════════════


class DispatchClaudeRequest(BaseModel):
    """Request to dispatch a Claude Code task to PC."""

    prompt: str
    timeout: Optional[int] = 300
    metadata: Optional[dict] = None


class DispatchOllamaRequest(BaseModel):
    """Request to dispatch an Ollama inference task to PC."""

    prompt: str
    model: Optional[str] = None
    timeout: Optional[int] = 300
    metadata: Optional[dict] = None


class JobStatus(BaseModel):
    """Job status response."""

    job_id: str
    task_type: str
    status: str
    prompt: str
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    result: Optional[dict]
    error: Optional[str]
    timeout: int
    metadata: dict


# ═══════════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/pc")
async def dispatch_pc(req: DispatchClaudeRequest) -> dict:
    """
    Dispatch a Claude Code task to Miles' PC via SSH.

    Request:
        {
            "prompt": "Fix the login button color to red",
            "timeout": 300,
            "metadata": {"project": "barber-crm"}
        }

    Response:
        {
            "job_id": "pc_abc123def456",
            "status": "pending",
            "message": "Task dispatched to PC"
        }
    """
    try:
        job_id = create_pc_job(
            task_type="claude_code",
            prompt=req.prompt,
            timeout=req.timeout or 300,
            metadata=req.metadata or {},
        )

        # Start execution in background (non-blocking)
        asyncio.create_task(execute_job_background(job_id))

        logger.info(f"Dispatched Claude Code task: {job_id}")

        return {
            "job_id": job_id,
            "status": "pending",
            "message": "Task dispatched to PC. Use /api/dispatch/status/{job_id} to check progress.",
        }

    except Exception as e:
        logger.error(f"Error dispatching Claude Code task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ollama")
async def dispatch_ollama(req: DispatchOllamaRequest) -> dict:
    """
    Dispatch an Ollama inference task to PC.

    Request:
        {
            "prompt": "Explain quantum computing",
            "model": "qwen2.5-coder:7b",
            "timeout": 300
        }

    Response:
        {
            "job_id": "pc_xyz789abc123",
            "status": "pending",
            "message": "Inference dispatched to PC"
        }
    """
    try:
        job_id = create_pc_job(
            task_type="ollama",
            prompt=req.prompt,
            timeout=req.timeout or 300,
            metadata={"model": req.model or "qwen2.5-coder:7b"},
        )

        # Start execution in background
        asyncio.create_task(execute_job_background(job_id))

        logger.info(f"Dispatched Ollama task: {job_id}")

        return {
            "job_id": job_id,
            "status": "pending",
            "message": "Inference dispatched to PC. Use /api/dispatch/status/{job_id} to check progress.",
        }

    except Exception as e:
        logger.error(f"Error dispatching Ollama task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{job_id}")
async def get_job_status(job_id: str) -> JobStatus:
    """
    Check the status of a dispatched job.

    Response:
        {
            "job_id": "pc_abc123def456",
            "task_type": "claude_code",
            "status": "completed",
            "prompt": "Fix the login button",
            "created_at": "2026-03-07T12:34:56.789Z",
            "started_at": "2026-03-07T12:34:57.123Z",
            "completed_at": "2026-03-07T12:35:10.456Z",
            "result": {...},
            "error": null,
            "timeout": 300,
            "metadata": {...}
        }
    """
    job = get_pc_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return JobStatus(
        job_id=job["job_id"],
        task_type=job["task_type"],
        status=job["status"],
        prompt=job["prompt"],
        created_at=job["created_at"],
        started_at=job["started_at"],
        completed_at=job["completed_at"],
        result=job["result"],
        error=job["error"],
        timeout=job["timeout"],
        metadata=job["metadata"],
    )


@router.get("/pc/health")
async def check_pc() -> dict:
    """
    Check if PC is reachable and ready.

    Response:
        {
            "healthy": true,
            "status": "ssh_ok",
            "pc_ip": "100.67.6.27",
            "ssh_latency_ms": 45.3,
            "claude_available": true,
            "ollama_available": true,
            "timestamp": "2026-03-07T12:34:56.789Z"
        }
    """
    try:
        health = await check_pc_health()
        return health
    except Exception as e:
        logger.error(f"Error checking PC health: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs")
async def list_jobs(status: Optional[str] = None) -> dict:
    """
    List all PC dispatch jobs, optionally filtered by status.

    Query params:
        status: "pending" | "running" | "completed" | "failed" | null (all)

    Response:
        {
            "total": 42,
            "status_filter": "completed",
            "jobs": [...]
        }
    """
    try:
        jobs = list_pc_jobs(status=status)
        return {
            "total": len(jobs),
            "status_filter": status,
            "jobs": jobs,
        }
    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_summary() -> dict:
    """Simple health check for dispatcher itself."""
    return {
        "status": "operational",
        "service": "pc_dispatcher",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
