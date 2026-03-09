"""Cursor Task Queue — API endpoints to create tasks for Cursor to pick up."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

QUEUE_DIR = Path("./services/cursor-tasks/queue")
DONE_DIR = Path("./services/cursor-tasks/done")
QUEUE_DIR.mkdir(parents=True, exist_ok=True)
DONE_DIR.mkdir(parents=True, exist_ok=True)


def create_task(prompt: str, project_path: str = ".", priority: str = "normal") -> str:
    task_id = f"cursor_{uuid.uuid4().hex[:10]}"
    task = {
        "id": task_id, "prompt": prompt, "project_path": project_path,
        "priority": priority, "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(QUEUE_DIR / f"{task_id}.task", "w") as f:
        json.dump(task, f, indent=2)
    return task_id


def list_tasks(status: str = None) -> list:
    tasks = []
    for d in [QUEUE_DIR, DONE_DIR]:
        for p in d.glob("*.task"):
            with open(p) as f:
                t = json.load(f)
                if status is None or t.get("status") == status:
                    tasks.append(t)
    tasks.sort(key=lambda t: t["created_at"], reverse=True)
    return tasks


def complete_task(task_id: str, result: str, success: bool = True):
    src = QUEUE_DIR / f"{task_id}.task"
    if not src.exists():
        return False
    with open(src) as f:
        task = json.load(f)
    task["status"] = "completed" if success else "failed"
    task["result"] = result
    task["completed_at"] = datetime.now(timezone.utc).isoformat()
    with open(DONE_DIR / f"{task_id}.task", "w") as f:
        json.dump(task, f, indent=2)
    src.unlink()
    return True

router = APIRouter(prefix="/api/cursor", tags=["cursor"])


class CursorTaskRequest(BaseModel):
    prompt: str
    project_path: str = "."
    priority: str = "normal"


@router.post("/task")
async def new_cursor_task(req: CursorTaskRequest):
    """Create a task for Cursor to execute."""
    task_id = create_task(req.prompt, req.project_path, req.priority)
    return {"task_id": task_id, "status": "queued", "message": "Task queued for Cursor"}


@router.get("/tasks")
async def get_cursor_tasks(status: Optional[str] = None):
    """List all Cursor tasks."""
    tasks = list_tasks(status)
    return {"total": len(tasks), "tasks": tasks}


@router.post("/task/{task_id}/complete")
async def mark_complete(task_id: str, result: str = "done", success: bool = True):
    """Mark a Cursor task as complete."""
    ok = complete_task(task_id, result, success)
    if not ok:
        return {"error": "Task not found in queue"}
    return {"task_id": task_id, "status": "completed" if success else "failed"}
