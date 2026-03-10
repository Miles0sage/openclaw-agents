"""
PA Integration — Bidirectional bridge between PA Worker and Autonomous Runner.

The PA (Personal Assistant) is a Cloudflare Worker running Gemini Flash-Lite
at <your-domain>. This module provides:

1. Request handling: PA sends structured requests, we dispatch to runner
2. Status tracking: All PA requests logged to data/pa/requests.jsonl
3. Callbacks: Send status updates back to PA worker
4. Escalation: PA can escalate jobs to higher-capability agents
"""

import json
import os
import time
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("pa_integration")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")
PA_REQUESTS_DIR = os.path.join(DATA_DIR, "pa")
PA_REQUESTS_LOG = os.path.join(PA_REQUESTS_DIR, "requests.jsonl")
PA_CALLBACK_URL = os.environ.get("PA_CALLBACK_URL", "https://<your-domain>/api/callback")

# Valid PA actions
VALID_ACTIONS = frozenset([
    "create_job",
    "monitor_job",
    "get_job_details",
    "list_jobs",
    "cancel_job",
    "approve_job",
    "escalate_job",
    "get_runner_status",
    "get_agency_status",
    "estimate_cost",
    "memory_save",
    "memory_search",
])


class PARequest:
    """Represents a PA request with tracking."""
    def __init__(self, action: str, payload: dict, request_id: str = None):
        self.request_id = request_id or str(uuid.uuid4())
        self.action = action
        self.payload = payload
        self.status = "pending"  # pending, processing, completed, failed
        self.result = None
        self.error = None
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.completed_at = None

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "action": self.action,
            "payload": self.payload,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


def _ensure_dirs():
    os.makedirs(PA_REQUESTS_DIR, exist_ok=True)


def _log_request(req: PARequest):
    """Log a PA request to JSONL."""
    _ensure_dirs()
    try:
        with open(PA_REQUESTS_LOG, "a") as f:
            f.write(json.dumps(req.to_dict()) + "\n")
    except Exception as e:
        logger.warning(f"Failed to log PA request: {e}")


def _send_callback(request_id: str, status: str, data: dict):
    """Send status callback to PA worker (best-effort, non-blocking)."""
    import threading
    def _do_callback():
        try:
            import urllib.request
            payload = json.dumps({
                "request_id": request_id,
                "status": status,
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{PA_CALLBACK_URL}/status/{request_id}",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
            logger.debug(f"PA callback sent: {request_id} -> {status}")
        except Exception as e:
            logger.debug(f"PA callback failed (non-critical): {e}")

    thread = threading.Thread(target=_do_callback, daemon=True)
    thread.start()


def handle_pa_request(action: str, payload: dict) -> dict:
    """
    Main dispatcher for PA requests. Routes to the appropriate handler.

    Returns dict with: request_id, status, result/error
    """
    if action not in VALID_ACTIONS:
        return {
            "error": f"Unknown action: {action}. Valid: {', '.join(sorted(VALID_ACTIONS))}",
            "status": "failed",
        }

    req = PARequest(action=action, payload=payload)
    req.status = "processing"
    _log_request(req)

    try:
        handler = _HANDLERS.get(action)
        if not handler:
            raise ValueError(f"No handler for action: {action}")

        result = handler(payload)
        req.status = "completed"
        req.result = result
        req.completed_at = datetime.now(timezone.utc).isoformat()
        _log_request(req)

        # Send callback to PA
        _send_callback(req.request_id, "completed", result)

        return {
            "request_id": req.request_id,
            "status": "completed",
            "result": result,
        }
    except Exception as e:
        req.status = "failed"
        req.error = str(e)
        req.completed_at = datetime.now(timezone.utc).isoformat()
        _log_request(req)

        _send_callback(req.request_id, "failed", {"error": str(e)})

        return {
            "request_id": req.request_id,
            "status": "failed",
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _handle_create_job(payload: dict) -> dict:
    from job_manager import create_job
    project = payload.get("project", "unknown")
    task = payload.get("task", "")
    priority = payload.get("priority", "P1")

    job = create_job(project, task, priority)

    from event_engine import get_event_engine
    engine = get_event_engine()
    if engine:
        engine.emit("job.created", {
            "job_id": job.get("id"), "project": project,
            "task": task, "priority": priority, "source": "pa",
        })

    return {"job_id": job.get("id"), "project": project, "task": task, "status": "pending"}


def _handle_monitor_job(payload: dict) -> dict:
    job_id = payload.get("job_id")
    if not job_id:
        raise ValueError("job_id required")

    from job_manager import get_job
    job = get_job(job_id)
    if not job:
        raise ValueError(f"Job not found: {job_id}")

    # Also check runner for live progress
    result = dict(job) if isinstance(job, dict) else {"job_id": job_id, "status": "unknown"}

    try:
        from autonomous_runner import get_runner
        runner = get_runner()
        if runner:
            progress = runner.get_job_progress(job_id)
            if progress:
                result["live_progress"] = progress
    except Exception:
        pass

    return result


def _handle_get_job_details(payload: dict) -> dict:
    return _handle_monitor_job(payload)  # Same logic


def _handle_list_jobs(payload: dict) -> dict:
    from job_manager import list_jobs
    status_filter = payload.get("status")
    jobs = list_jobs(status=status_filter) if status_filter else list_jobs()
    return {"jobs": jobs, "total": len(jobs)}


def _handle_cancel_job(payload: dict) -> dict:
    job_id = payload.get("job_id")
    if not job_id:
        raise ValueError("job_id required")

    from autonomous_runner import _set_kill_flag
    _set_kill_flag(job_id, "Cancelled via PA")

    try:
        from autonomous_runner import get_runner
        runner = get_runner()
        if runner:
            runner.cancel_job(job_id)
    except Exception:
        pass

    return {"job_id": job_id, "status": "cancelling", "message": "Kill flag set"}


def _handle_approve_job(payload: dict) -> dict:
    job_id = payload.get("job_id")
    if not job_id:
        raise ValueError("job_id required")

    from job_manager import update_job_status
    update_job_status(job_id, "approved", approved_by="pa_worker")

    from event_engine import get_event_engine
    engine = get_event_engine()
    if engine:
        engine.emit("job.approved", {"job_id": job_id, "approved_by": "pa_worker"})

    return {"job_id": job_id, "status": "approved", "approved_by": "pa_worker"}


def _handle_escalate_job(payload: dict) -> dict:
    """Escalate a job to a higher-capability agent."""
    job_id = payload.get("job_id")
    target_agent = payload.get("target_agent", "overseer")
    reason = payload.get("reason", "PA escalation request")

    if not job_id:
        raise ValueError("job_id required")

    from event_engine import get_event_engine
    engine = get_event_engine()
    if engine:
        engine.emit("proposal.created", {
            "title": f"PA Escalation: job {job_id}",
            "description": f"Escalated by PA: {reason}",
            "source_job_id": job_id,
            "target_agent": target_agent,
            "priority": "high",
            "proposed_action": "escalate",
            "source": "pa",
        }, skip_dedup=True)

    return {
        "job_id": job_id,
        "escalated_to": target_agent,
        "reason": reason,
        "status": "escalation_requested",
    }


def _handle_get_runner_status(payload: dict) -> dict:
    try:
        from autonomous_runner import get_runner
        runner = get_runner()
        if not runner:
            return {"running": False, "message": "Runner not initialized"}
        stats = runner.get_stats()
        active = runner.get_active_jobs()
        return {"running": runner._running, "active_jobs": active, "stats": stats}
    except Exception as e:
        return {"running": False, "error": str(e)}


def _handle_get_agency_status(payload: dict) -> dict:
    """Aggregate agency status from multiple sources."""
    result = {}

    # Runner status
    try:
        result["runner"] = _handle_get_runner_status({})
    except Exception:
        result["runner"] = {"running": False}

    # Jobs
    try:
        result["jobs"] = _handle_list_jobs({"status": None})
    except Exception:
        result["jobs"] = {"total": 0}

    # Costs
    try:
        from cost_tracker import get_cost_metrics
        result["costs"] = get_cost_metrics()
    except Exception:
        result["costs"] = {}

    # Recent events
    try:
        from event_engine import get_event_engine
        engine = get_event_engine()
        if engine:
            result["recent_events"] = engine.get_recent_events(limit=5)
    except Exception:
        result["recent_events"] = []

    return result


def _handle_estimate_cost(payload: dict) -> dict:
    """Estimate cost for a proposed task based on complexity heuristics."""
    task = payload.get("task", "")
    agent = payload.get("agent", "coder_agent")

    from cost_tracker import COST_PRICING

    # Simple heuristic: estimate tokens based on task length
    task_tokens = len(task.split()) * 4  # ~4 tokens per word
    estimated_input = max(task_tokens + 2000, 4000)  # min 4K context
    estimated_output = max(task_tokens * 2, 2000)  # estimate 2x output

    # Map agent to model
    agent_model_map = {
        "coder_agent": "kimi-2.5",
        "elite_coder": "m2.5",
        "hacker_agent": "kimi",
        "database_agent": "claude-opus-4-6",
        "project_manager": "claude-opus-4-6",
        "code_reviewer": "kimi-2.5",
        "test_generator": "kimi-2.5",
        "architecture_designer": "m2.5",
        "debugger": "claude-opus-4-6",
    }
    model = agent_model_map.get(agent, "kimi-2.5")
    pricing = COST_PRICING.get(model, {"input": 3.0, "output": 15.0})

    est_cost = round(
        (estimated_input * pricing["input"] + estimated_output * pricing["output"]) / 1_000_000,
        4,
    )

    return {
        "estimated_cost_usd": est_cost,
        "model": model,
        "agent": agent,
        "estimated_input_tokens": estimated_input,
        "estimated_output_tokens": estimated_output,
    }


def _handle_memory_save(payload: dict) -> dict:
    content = payload.get("content")
    if not content:
        raise ValueError("content required")

    importance = payload.get("importance", 5)
    tags = payload.get("tags", [])

    # Use the save_memory from agent_tools
    try:
        from agent_tools import execute_tool
        result = execute_tool("save_memory", {
            "content": content,
            "importance": importance,
            "tags": tags,
        })
    except Exception:
        result = None

    return {"saved": True, "content_preview": content[:100]}


def _handle_memory_search(payload: dict) -> dict:
    query = payload.get("query", "")
    limit = payload.get("limit", 5)

    try:
        from agent_tools import execute_tool
        result = execute_tool("search_memory", {
            "query": query,
            "limit": limit,
        })
    except Exception:
        result = None

    # Parse result if it's a string
    if isinstance(result, str):
        try:
            return json.loads(result)
        except Exception:
            return {"results": result}
    return result or {"results": []}


def get_pa_request_status(request_id: str) -> Optional[dict]:
    """Look up a PA request by ID from the log."""
    if not os.path.exists(PA_REQUESTS_LOG):
        return None

    # Read backwards to find the latest entry for this request_id
    latest = None
    try:
        with open(PA_REQUESTS_LOG, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("request_id") == request_id:
                        latest = entry
                except Exception:
                    continue
    except Exception:
        return None

    return latest


def get_recent_pa_requests(limit: int = 20) -> list:
    """Get recent PA requests from log."""
    if not os.path.exists(PA_REQUESTS_LOG):
        return []

    entries = []
    try:
        with open(PA_REQUESTS_LOG, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []

    # Return latest entries, deduped by request_id (keep latest status)
    seen = {}
    for entry in entries:
        rid = entry.get("request_id")
        if rid:
            seen[rid] = entry

    results = sorted(seen.values(), key=lambda x: x.get("created_at", ""), reverse=True)
    return results[:limit]


# Handler dispatch table
_HANDLERS = {
    "create_job": _handle_create_job,
    "monitor_job": _handle_monitor_job,
    "get_job_details": _handle_get_job_details,
    "list_jobs": _handle_list_jobs,
    "cancel_job": _handle_cancel_job,
    "approve_job": _handle_approve_job,
    "escalate_job": _handle_escalate_job,
    "get_runner_status": _handle_get_runner_status,
    "get_agency_status": _handle_get_agency_status,
    "estimate_cost": _handle_estimate_cost,
    "memory_save": _handle_memory_save,
    "memory_search": _handle_memory_search,
}
