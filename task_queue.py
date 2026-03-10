"""
Task Queue Implementation with Approval Status

Manages task lifecycle:
- Task queuing with approval status tracking
- Persistence (file-based)
- Queue monitoring endpoints
- Status transitions
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict, field
from enum import Enum
import asyncio

logger = logging.getLogger("task_queue")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")


class TaskStatus(Enum):
    """Task execution statuses"""
    PENDING = "pending"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    ABORTED = "aborted"


@dataclass
class Task:
    """Task in the queue"""
    task_id: str
    task_type: str  # "chat", "workflow", "batch", etc.
    description: str
    status: str = TaskStatus.PENDING.value
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat() + "Z")
    approved_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    estimated_cost: Optional[float] = None
    actual_cost: Optional[float] = None
    estimated_duration_ms: Optional[int] = None
    actual_duration_ms: Optional[int] = None
    approval_reason: Optional[str] = None
    rejection_reason: Optional[str] = None
    constraints: Optional[List[Dict]] = None
    result: Optional[str] = None
    error: Optional[str] = None
    logs: Optional[str] = None
    context: Optional[Dict] = None
    priority: int = 0  # Higher number = higher priority
    retry_count: int = 0
    max_retries: int = 3

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "estimated_cost": self.estimated_cost,
            "actual_cost": self.actual_cost,
            "estimated_duration_ms": self.estimated_duration_ms,
            "actual_duration_ms": self.actual_duration_ms,
            "approval_reason": self.approval_reason,
            "rejection_reason": self.rejection_reason,
            "constraints": self.constraints,
            "result": self.result,
            "error": self.error,
            "logs": self.logs,
            "context": self.context,
            "priority": self.priority,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries
        }

    @staticmethod
    def from_dict(data: Dict) -> "Task":
        """Create Task from dictionary"""
        return Task(
            task_id=data["task_id"],
            task_type=data["task_type"],
            description=data["description"],
            status=data.get("status", TaskStatus.PENDING.value),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat() + "Z"),
            approved_at=data.get("approved_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            estimated_cost=data.get("estimated_cost"),
            actual_cost=data.get("actual_cost"),
            estimated_duration_ms=data.get("estimated_duration_ms"),
            actual_duration_ms=data.get("actual_duration_ms"),
            approval_reason=data.get("approval_reason"),
            rejection_reason=data.get("rejection_reason"),
            constraints=data.get("constraints"),
            result=data.get("result"),
            error=data.get("error"),
            logs=data.get("logs"),
            context=data.get("context"),
            priority=data.get("priority", 0),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3)
        )


class TaskQueue:
    """
    In-memory task queue with file persistence

    Manages:
    - Task queuing and status tracking
    - Approval workflow
    - Persistence to disk
    - Queue monitoring
    """

    def __init__(
        self,
        persistence_dir: str = None,
        auto_save: bool = True
    ):
        """
        Initialize task queue

        Args:
            persistence_dir: Directory for persisting tasks
            auto_save: Automatically save tasks to disk
        """
        self.persistence_dir = Path(persistence_dir or os.path.join(DATA_DIR, "tasks"))
        self.persistence_dir.mkdir(exist_ok=True, parents=True)
        self.auto_save = auto_save

        # In-memory storage
        self.tasks: Dict[str, Task] = {}
        self.approval_callbacks: Dict[str, callable] = {}
        self.status_callbacks: Dict[str, callable] = {}

        # Load existing tasks from disk
        self._load_from_disk()
        logger.info(f"📁 Task queue initialized with {len(self.tasks)} tasks from disk")

    def enqueue(
        self,
        task_id: str,
        task_type: str,
        description: str,
        estimated_cost: Optional[float] = None,
        estimated_duration_ms: Optional[int] = None,
        context: Optional[Dict] = None,
        priority: int = 0
    ) -> Task:
        """
        Enqueue a new task

        Args:
            task_id: Unique task ID
            task_type: Type of task
            description: Human-readable description
            estimated_cost: Estimated API cost
            estimated_duration_ms: Estimated execution time
            context: Additional context
            priority: Task priority (higher = more important)

        Returns:
            Created Task object
        """
        task = Task(
            task_id=task_id,
            task_type=task_type,
            description=description,
            estimated_cost=estimated_cost,
            estimated_duration_ms=estimated_duration_ms,
            context=context or {},
            priority=priority
        )

        self.tasks[task_id] = task
        logger.info(f"➕ Task enqueued: {task_id} ({task_type})")

        if self.auto_save:
            self._save_to_disk()

        return task

    def set_pending_approval(
        self,
        task_id: str
    ) -> Optional[Task]:
        """
        Transition task to pending_approval status

        Args:
            task_id: Task to update

        Returns:
            Updated Task or None if not found
        """
        if task_id not in self.tasks:
            logger.warning(f"❌ Task not found: {task_id}")
            return None

        task = self.tasks[task_id]
        task.status = TaskStatus.PENDING_APPROVAL.value
        logger.info(f"⏳ Task pending approval: {task_id}")

        if self.auto_save:
            self._save_to_disk()

        return task

    def approve_task(
        self,
        task_id: str,
        reason: str,
        constraints: Optional[List[Dict]] = None
    ) -> Optional[Task]:
        """
        Mark task as approved

        Args:
            task_id: Task to approve
            reason: Approval reason
            constraints: Applied constraints

        Returns:
            Updated Task or None if not found
        """
        if task_id not in self.tasks:
            logger.warning(f"❌ Task not found: {task_id}")
            return None

        task = self.tasks[task_id]
        task.status = TaskStatus.APPROVED.value
        task.approved_at = datetime.now(timezone.utc).isoformat() + "Z"
        task.approval_reason = reason
        task.constraints = constraints
        logger.info(f"✅ Task approved: {task_id}")

        if self.auto_save:
            self._save_to_disk()

        # Call approval callback if registered
        if task_id in self.approval_callbacks:
            try:
                self.approval_callbacks[task_id](task)
            except Exception as e:
                logger.error(f"Error in approval callback: {e}")

        return task

    def reject_task(
        self,
        task_id: str,
        reason: str
    ) -> Optional[Task]:
        """
        Mark task as rejected

        Args:
            task_id: Task to reject
            reason: Rejection reason

        Returns:
            Updated Task or None if not found
        """
        if task_id not in self.tasks:
            logger.warning(f"❌ Task not found: {task_id}")
            return None

        task = self.tasks[task_id]
        task.status = TaskStatus.REJECTED.value
        task.rejection_reason = reason
        task.completed_at = datetime.now(timezone.utc).isoformat() + "Z"
        logger.warning(f"❌ Task rejected: {task_id} - {reason}")

        if self.auto_save:
            self._save_to_disk()

        return task

    def start_task(self, task_id: str) -> Optional[Task]:
        """
        Transition task to running status

        Args:
            task_id: Task to start

        Returns:
            Updated Task or None if not found
        """
        if task_id not in self.tasks:
            logger.warning(f"❌ Task not found: {task_id}")
            return None

        task = self.tasks[task_id]
        task.status = TaskStatus.RUNNING.value
        task.started_at = datetime.now(timezone.utc).isoformat() + "Z"
        logger.info(f"🚀 Task started: {task_id}")

        if self.auto_save:
            self._save_to_disk()

        return task

    def complete_task(
        self,
        task_id: str,
        result: Optional[str] = None,
        actual_cost: Optional[float] = None,
        logs: Optional[str] = None
    ) -> Optional[Task]:
        """
        Mark task as completed

        Args:
            task_id: Task to complete
            result: Task result
            actual_cost: Actual API cost
            logs: Execution logs

        Returns:
            Updated Task or None if not found
        """
        if task_id not in self.tasks:
            logger.warning(f"❌ Task not found: {task_id}")
            return None

        task = self.tasks[task_id]
        task.status = TaskStatus.COMPLETED.value
        task.completed_at = datetime.now(timezone.utc).isoformat() + "Z"
        task.result = result
        task.actual_cost = actual_cost
        task.logs = logs

        # Calculate actual duration
        if task.started_at:
            start = datetime.fromisoformat(task.started_at.replace("Z", "+00:00"))
            end = datetime.fromisoformat(task.completed_at.replace("Z", "+00:00"))
            task.actual_duration_ms = int((end - start).total_seconds() * 1000)

        logger.info(f"✅ Task completed: {task_id} (cost: ${actual_cost:.4f}, duration: {task.actual_duration_ms}ms)")

        if self.auto_save:
            self._save_to_disk()

        return task

    def fail_task(
        self,
        task_id: str,
        error: str,
        logs: Optional[str] = None
    ) -> Optional[Task]:
        """
        Mark task as failed

        Args:
            task_id: Task that failed
            error: Error message
            logs: Execution logs

        Returns:
            Updated Task or None if not found
        """
        if task_id not in self.tasks:
            logger.warning(f"❌ Task not found: {task_id}")
            return None

        task = self.tasks[task_id]
        task.status = TaskStatus.FAILED.value
        task.completed_at = datetime.now(timezone.utc).isoformat() + "Z"
        task.error = error
        task.logs = logs

        # Calculate actual duration
        if task.started_at:
            start = datetime.fromisoformat(task.started_at.replace("Z", "+00:00"))
            end = datetime.fromisoformat(task.completed_at.replace("Z", "+00:00"))
            task.actual_duration_ms = int((end - start).total_seconds() * 1000)

        logger.error(f"❌ Task failed: {task_id} - {error}")

        if self.auto_save:
            self._save_to_disk()

        return task

    def abort_task(self, task_id: str) -> Optional[Task]:
        """
        Mark task as aborted

        Args:
            task_id: Task to abort

        Returns:
            Updated Task or None if not found
        """
        if task_id not in self.tasks:
            logger.warning(f"❌ Task not found: {task_id}")
            return None

        task = self.tasks[task_id]
        task.status = TaskStatus.ABORTED.value
        task.completed_at = datetime.now(timezone.utc).isoformat() + "Z"
        logger.warning(f"🛑 Task aborted: {task_id}")

        if self.auto_save:
            self._save_to_disk()

        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID"""
        return self.tasks.get(task_id)

    def get_tasks_by_status(self, status: str) -> List[Task]:
        """Get all tasks with given status"""
        return [t for t in self.tasks.values() if t.status == status]

    def get_pending_approval(self) -> List[Task]:
        """Get all tasks pending approval"""
        return self.get_tasks_by_status(TaskStatus.PENDING_APPROVAL.value)

    def get_running_tasks(self) -> List[Task]:
        """Get all currently running tasks"""
        return self.get_tasks_by_status(TaskStatus.RUNNING.value)

    def get_queue_status(self) -> Dict[str, Any]:
        """
        Get overall queue status

        Returns:
            Dictionary with queue metrics
        """
        total = len(self.tasks)
        by_status = {}
        for status in TaskStatus:
            count = len(self.get_tasks_by_status(status.value))
            if count > 0:
                by_status[status.value] = count

        total_cost = sum(t.actual_cost or 0 for t in self.tasks.values())
        total_time_ms = sum(t.actual_duration_ms or 0 for t in self.tasks.values())

        return {
            "total_tasks": total,
            "by_status": by_status,
            "total_cost_usd": total_cost,
            "total_execution_time_ms": total_time_ms,
            "pending_approval": len(self.get_pending_approval()),
            "running": len(self.get_running_tasks()),
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
        }

    def register_approval_callback(
        self,
        task_id: str,
        callback: callable
    ):
        """
        Register callback to be called when task is approved

        Args:
            task_id: Task ID
            callback: Function to call with (Task) argument
        """
        self.approval_callbacks[task_id] = callback

    def _save_to_disk(self):
        """Save all tasks to disk"""
        try:
            tasks_file = self.persistence_dir / "tasks.json"
            data = {
                "saved_at": datetime.now(timezone.utc).isoformat() + "Z",
                "total_tasks": len(self.tasks),
                "tasks": [t.to_dict() for t in self.tasks.values()]
            }
            with open(tasks_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving tasks to disk: {e}")

    def _load_from_disk(self):
        """Load tasks from disk"""
        try:
            tasks_file = self.persistence_dir / "tasks.json"
            if tasks_file.exists():
                with open(tasks_file, 'r') as f:
                    data = json.load(f)
                    for task_data in data.get("tasks", []):
                        task = Task.from_dict(task_data)
                        self.tasks[task.task_id] = task
        except Exception as e:
            logger.error(f"Error loading tasks from disk: {e}")

    def clear_completed(self, older_than_days: int = 7):
        """
        Remove completed tasks older than specified days

        Args:
            older_than_days: Remove tasks completed before this many days ago
        """
        cutoff = datetime.now(timezone.utc).timestamp() - (older_than_days * 86400)
        to_remove = []

        for task_id, task in self.tasks.items():
            if task.status in [TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.REJECTED.value]:
                if task.completed_at:
                    completed = datetime.fromisoformat(task.completed_at.replace("Z", "+00:00")).timestamp()
                    if completed < cutoff:
                        to_remove.append(task_id)

        for task_id in to_remove:
            del self.tasks[task_id]

        if to_remove:
            logger.info(f"🧹 Cleaned up {len(to_remove)} old completed tasks")
            if self.auto_save:
                self._save_to_disk()

        return len(to_remove)
