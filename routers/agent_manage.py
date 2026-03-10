"""
FastAPI router for agent management endpoints.

This module provides endpoints for managing agents, tmux panes, and task workflow.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from routers.shared import (
    CONFIG,
    TASKS_FILE,
    get_heartbeat_monitor,
)

router = APIRouter()


# ── Pydantic Models ─────────────────────────────────────────────────────

class SpawnRequest(BaseModel):
    job_id: Optional[str] = None
    prompt: str
    worktree_repo: Optional[str] = None
    use_worktree: bool = False
    cwd: Optional[str] = None
    timeout_minutes: int = 30
    claude_args: str = ""


class SpawnParallelRequest(BaseModel):
    jobs: list[dict]  # Each dict has: job_id, prompt, and optional fields


# ── Endpoints: Agent Configuration ───────────────────────────────────────

@router.get("/api/agents")
async def list_agents():
    """List agents with ACTUAL model configuration"""
    agents = []
    for agent_id, config in CONFIG.get("agents", {}).items():
        agents.append({
            "id": agent_id,
            "name": config.get("name"),
            "provider": config.get("apiProvider"),
            "model": config.get("model"),
            "role": config.get("type"),
            "status": "idle"
        })
    return {"agents": agents}


@router.get("/api/agents/status")
async def agents_status():
    """Get status of all agents for Mission Control"""
    agents_config = CONFIG.get("agents", {})
    agent_statuses = {}
    heartbeat = get_heartbeat_monitor()

    for agent_id, config in agents_config.items():
        agent_statuses[agent_id] = {
            "name": config.get("name", agent_id),
            "emoji": config.get("emoji", ""),
            "model": config.get("model", "unknown"),
            "provider": config.get("apiProvider", "unknown"),
            "type": config.get("type", "unknown"),
            "skills": config.get("skills", []),
            "signature": config.get("signature", ""),
            "costSavings": config.get("costSavings", ""),
            "status": "active",
        }

        # Check heartbeat if available
        if heartbeat:
            try:
                status_data = heartbeat.get_status()
                in_flight = heartbeat.get_in_flight_agents()
                if agent_id in [a.get("agent_id") for a in in_flight]:
                    agent_statuses[agent_id]["status"] = "busy"
                else:
                    agent_statuses[agent_id]["status"] = "idle"
            except Exception:
                pass

    return {"success": True, "agents": agent_statuses, "total": len(agent_statuses)}


# ── Endpoints: TMUX Agent Panes ─────────────────────────────────────────

@router.get("/api/agents/panes")
async def list_agent_panes():
    """List all tmux agent panes with status."""
    try:
        from tmux_spawner import get_spawner
        spawner = get_spawner()
        agents = spawner.list_agents()
        return {"success": True, "agents": agents, "count": len(agents)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/agents/spawn")
async def spawn_agent(req: SpawnRequest):
    """Spawn a single Claude Code agent in a tmux pane."""
    try:
        from tmux_spawner import get_spawner
        job_id = req.job_id or f"ui-{uuid.uuid4().hex[:8]}"
        spawner = get_spawner()
        pane_id = spawner.spawn_agent(
            job_id=job_id,
            prompt=req.prompt,
            worktree_repo=req.worktree_repo,
            use_worktree=req.use_worktree,
            cwd=req.cwd,
            timeout_minutes=req.timeout_minutes,
            claude_args=req.claude_args,
        )
        return {"success": True, "pane_id": pane_id, "job_id": job_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/agents/spawn-parallel")
async def spawn_parallel_agents(req: SpawnParallelRequest):
    """Spawn multiple agents in parallel tmux panes."""
    try:
        from tmux_spawner import get_spawner
        spawner = get_spawner()
        results = spawner.spawn_parallel(req.jobs)
        spawned = sum(1 for r in results if r["status"] == "spawned")
        return {"success": True, "results": results, "spawned": spawned, "total": len(req.jobs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/agents/panes/{pane_id:path}/output")
async def get_agent_output(pane_id: str, job_id: str = None):
    """Get the output buffer from a tmux agent pane."""
    try:
        from tmux_spawner import get_spawner
        spawner = get_spawner()
        output = spawner.collect_output(pane_id, job_id=job_id)
        status = spawner.get_agent_status(pane_id)
        return {
            "success": True,
            "pane_id": pane_id,
            "output": output,
            "status": status,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/agents/panes/{pane_id:path}")
async def kill_agent_pane(pane_id: str):
    """Kill a specific tmux agent pane."""
    try:
        from tmux_spawner import get_spawner
        spawner = get_spawner()
        killed = spawner.kill_agent(pane_id)
        return {"success": killed, "pane_id": pane_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/agents/panes/all")
async def kill_all_agent_panes():
    """Kill all tmux agent panes."""
    try:
        from tmux_spawner import get_spawner
        spawner = get_spawner()
        count = spawner.kill_all()
        return {"success": True, "killed": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Endpoints: Heartbeat & Health ───────────────────────────────────────

@router.get("/api/heartbeat/status")
async def heartbeat_status():
    """Get heartbeat monitor status and agent health"""
    heartbeat = get_heartbeat_monitor()
    if not heartbeat:
        return {
            "success": True,
            "status": "offline",
            "message": "Heartbeat monitor not initialized"
        }

    status = heartbeat.get_status()
    in_flight = heartbeat.get_in_flight_agents()

    return {
        "success": True,
        "status": "online" if status["running"] else "offline",
        "monitor": status,
        "in_flight_agents": [
            {
                "agent_id": agent.agent_id,
                "task_id": agent.task_id,
                "status": agent.status,
                "running_for_ms": int(datetime.now().timestamp() * 1000) - agent.started_at,
                "idle_for_ms": int(datetime.now().timestamp() * 1000) - agent.last_activity_at,
            }
            for agent in in_flight
        ],
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
    }


# ── Endpoints: Task Management ──────────────────────────────────────────

@router.get("/api/tasks")
async def list_tasks_endpoint():
    """List all tasks for Mission Control task board"""
    try:
        if TASKS_FILE.exists():
            with open(TASKS_FILE, 'r') as f:
                tasks = json.load(f)
        else:
            tasks = []
        return {"success": True, "tasks": tasks, "total": len(tasks)}
    except Exception as e:
        return {"success": True, "tasks": [], "total": 0}


@router.post("/api/tasks")
async def create_task_endpoint(request: Request):
    """Create a new task"""
    body = await request.json()
    try:
        if TASKS_FILE.exists():
            with open(TASKS_FILE, 'r') as f:
                tasks = json.load(f)
        else:
            tasks = []

        task = {
            "id": str(uuid.uuid4())[:8],
            "title": body.get("title", "Untitled"),
            "description": body.get("description", ""),
            "status": body.get("status", "todo"),
            "agent": body.get("agent", ""),
            "created_at": datetime.now(timezone.utc).isoformat() + "Z",
            "updated_at": datetime.now(timezone.utc).isoformat() + "Z",
        }
        tasks.append(task)

        with open(TASKS_FILE, 'w') as f:
            json.dump(tasks, f, indent=2)

        return {"success": True, "task": task}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/tasks/{task_id}")
async def update_task_endpoint(task_id: str, request: Request):
    """Update a task status"""
    body = await request.json()
    try:
        if TASKS_FILE.exists():
            with open(TASKS_FILE, 'r') as f:
                tasks = json.load(f)
        else:
            tasks = []

        for task in tasks:
            if task["id"] == task_id:
                task.update({k: v for k, v in body.items() if k in ["title", "description", "status", "agent"]})
                task["updated_at"] = datetime.now(timezone.utc).isoformat() + "Z"
                break

        with open(TASKS_FILE, 'w') as f:
            json.dump(tasks, f, indent=2)

        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
