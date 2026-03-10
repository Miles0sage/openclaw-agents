"""
Cursor Task Runner — Drop a .task file, Cursor picks it up and runs it.

How it works:
1. VPS writes a JSON file to ./services/cursor-tasks/queue/
2. Cursor's workspace task watcher detects it
3. Cursor runs the task via its built-in AI
4. Result written back to ./services/cursor-tasks/done/

File format (.task JSON):
{
    "id": "task_abc123",
    "prompt": "Build a login page with Tailwind CSS",
    "project_path": ".",
    "priority": "normal",
    "created_at": "2026-03-07T23:30:00Z"
}
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

QUEUE_DIR = Path("./services/cursor-tasks/queue")
DONE_DIR = Path("./services/cursor-tasks/done")
QUEUE_DIR.mkdir(parents=True, exist_ok=True)
DONE_DIR.mkdir(parents=True, exist_ok=True)


def create_task(prompt: str, project_path: str = ".", priority: str = "normal") -> str:
    """Create a new task file in the queue."""
    task_id = f"cursor_{uuid.uuid4().hex[:10]}"
    task = {
        "id": task_id,
        "prompt": prompt,
        "project_path": project_path,
        "priority": priority,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    task_path = QUEUE_DIR / f"{task_id}.task"
    with open(task_path, "w") as f:
        json.dump(task, f, indent=2)
    return task_id


def list_tasks(status: str = None) -> list:
    """List tasks in queue and done dirs."""
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
    """Mark a task as done and move to done dir."""
    src = QUEUE_DIR / f"{task_id}.task"
    if not src.exists():
        return False
    with open(src) as f:
        task = json.load(f)
    task["status"] = "completed" if success else "failed"
    task["result"] = result
    task["completed_at"] = datetime.now(timezone.utc).isoformat()
    dst = DONE_DIR / f"{task_id}.task"
    with open(dst, "w") as f:
        json.dump(task, f, indent=2)
    src.unlink()
    return True


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python task-runner.py <prompt>")
        print("       python task-runner.py --list")
        sys.exit(1)

    if sys.argv[1] == "--list":
        for t in list_tasks():
            print(f"[{t['status']:>9}] {t['id']} — {t['prompt'][:60]}")
    else:
        prompt = " ".join(sys.argv[1:])
        tid = create_task(prompt)
        print(f"Task created: {tid}")
        print(f"Queue: {QUEUE_DIR / f'{tid}.task'}")
