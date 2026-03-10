"""
Tests for Coding Factory Cron System
====================================

Coverage:
  - Database operations (CRUD, schema, integrity)
  - Rate limiting logic (per-engine tracking, 60-minute window)
  - Task status lifecycle (pending -> running -> done/failed)
  - Task execution flow
  - Priority queue ordering
  - Cost and duration tracking
"""

import os
import sys
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from coding_factory_cron import (
    CodingTask,
    TaskStatus,
    Engine,
    add_task,
    get_pending_tasks,
    get_running_count,
    get_recent_completions,
    update_task_status,
    _can_run_engine,
    RATE_LIMIT_PER_ENGINE,
    _init_db,
    get_db,
)


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def temp_db_path(tmp_path, monkeypatch):
    """Create a temporary database path and set env var + monkeypatch module."""
    import coding_factory_cron

    test_db_path = str(tmp_path / "test_coding_factory.db")

    # Monkeypatch the module-level constants
    monkeypatch.setenv("OPENCLAW_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(coding_factory_cron, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(coding_factory_cron, "DB_PATH", test_db_path)

    # Initialize database
    conn = sqlite3.connect(test_db_path, timeout=10.0)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS coding_tasks (
            id TEXT PRIMARY KEY,
            repo TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            engine TEXT DEFAULT 'any',
            priority INTEGER DEFAULT 5,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            branch TEXT,
            result TEXT,
            cost_usd REAL DEFAULT 0.0,
            duration_seconds REAL DEFAULT 0.0,
            github_issue_number INTEGER DEFAULT 0,
            github_issue_url TEXT,
            error_message TEXT,
            UNIQUE(repo, github_issue_number)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON coding_tasks(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_engine ON coding_tasks(engine)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON coding_tasks(created_at)")

    conn.commit()
    conn.close()

    yield test_db_path

    if os.path.exists(test_db_path):
        os.unlink(test_db_path)


# ═══════════════════════════════════════════════════════════════════════════
# CodingTask Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCodingTask:
    """Test CodingTask dataclass."""
    
    def test_create_task_with_defaults(self):
        """Test task creation with default values."""
        task = CodingTask(
            id="task-123",
            repo="owner/repo",
            title="Fix button",
            description="Button color wrong"
        )
        assert task.id == "task-123"
        assert task.repo == "owner/repo"
        assert task.status == "pending"
        assert task.priority == 5
        assert task.cost_usd == 0.0
        assert task.engine == "any"
    
    def test_create_task_with_custom_engine(self):
        """Test task with custom engine."""
        task = CodingTask(
            id="task-1",
            repo="owner/repo",
            title="Test",
            description="Test",
            engine="claude",
            priority=8
        )
        assert task.engine == "claude"
        assert task.priority == 8
    
    def test_task_to_tuple(self):
        """Test conversion to SQL tuple."""
        now = datetime.now(timezone.utc).isoformat()
        task = CodingTask(
            id="task-1",
            repo="owner/repo",
            title="Test",
            description="Desc",
            engine="claude",
            priority=7,
            status="pending",
            created_at=now,
            github_issue_number=42,
        )
        tup = task.to_tuple()
        assert len(tup) == 17
        assert tup[0] == "task-1"
        assert tup[1] == "owner/repo"
        assert tup[4] == "claude"
        assert tup[14] == 42


# ═══════════════════════════════════════════════════════════════════════════
# Database Operations Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDatabaseOperations:
    """Test database CRUD operations."""
    
    def test_add_task(self, temp_db_path):
        """Test adding a task."""
        os.environ["OPENCLAW_DATA_DIR"] = str(Path(temp_db_path).parent)
        task = CodingTask(
            id="task-123",
            repo="owner/repo",
            title="Test Task",
            description="Testing",
        )
        result = add_task(
            repo=task.repo,
            title=task.title,
            description=task.description,
        )
        assert result is not None
        assert result.repo == "owner/repo"
    
    def test_add_task_with_github_issue(self, temp_db_path):
        """Test adding task with GitHub issue tracking."""
        os.environ["OPENCLAW_DATA_DIR"] = str(Path(temp_db_path).parent)
        result = add_task(
            repo="owner/repo",
            title="Issue",
            description="Desc",
            github_issue_number=42,
            github_issue_url="https://github.com/owner/repo/issues/42"
        )
        assert result.github_issue_number == 42
        assert result.github_issue_url == "https://github.com/owner/repo/issues/42"
    
    def test_get_pending_tasks(self, temp_db_path):
        """Test fetching pending tasks."""
        os.environ["OPENCLAW_DATA_DIR"] = str(Path(temp_db_path).parent)

        # Add tasks with different priorities (use different repos or issue numbers to avoid UNIQUE constraint)
        for i, priority in enumerate([3, 7, 5]):
            add_task(
                repo=f"owner/repo-{i}",
                title=f"Task {i}",
                description=f"Desc {i}",
                priority=priority,
            )

        pending = get_pending_tasks(limit=10)
        assert len(pending) == 3
        # Should be ordered by priority (descending)
        assert pending[0].priority == 7
        assert pending[1].priority == 5
        assert pending[2].priority == 3
    
    def test_get_running_count(self, temp_db_path):
        """Test counting running tasks."""
        os.environ["OPENCLAW_DATA_DIR"] = str(Path(temp_db_path).parent)

        # Add 3 tasks (use different repos to avoid UNIQUE constraint)
        for i in range(3):
            add_task(
                repo=f"owner/repo-{i}",
                title=f"Task {i}",
                description=f"Desc {i}",
            )

        # Mark 2 as running
        tasks = get_pending_tasks()
        update_task_status(tasks[0].id, TaskStatus.RUNNING.value)
        update_task_status(tasks[1].id, TaskStatus.RUNNING.value)

        count = get_running_count()
        assert count == 2
    
    def test_update_task_status(self, temp_db_path):
        """Test updating task status."""
        os.environ["OPENCLAW_DATA_DIR"] = str(Path(temp_db_path).parent)
        
        task = add_task(
            repo="owner/repo",
            title="Test",
            description="Test",
        )
        
        # Update to RUNNING
        update_task_status(task.id, TaskStatus.RUNNING.value)
        
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status, started_at FROM coding_tasks WHERE id=?", (task.id,))
        row = cursor.fetchone()
        conn.close()
        
        assert row[0] == "running"
        assert row[1] is not None
    
    def test_update_task_completion(self, temp_db_path):
        """Test updating task with result and cost."""
        os.environ["OPENCLAW_DATA_DIR"] = str(Path(temp_db_path).parent)

        task = add_task(
            repo="owner/repo",
            title="Test",
            description="Test",
        )
        update_task_status(task.id, TaskStatus.RUNNING.value)

        # Simulate completion
        update_task_status(
            task_id=task.id,
            status=TaskStatus.DONE.value,
            result="PR created: #42",
            cost_usd=0.50,
            duration_seconds=120.0,
            branch="claude/task-1"
        )
        
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status, result, cost_usd, duration_seconds, branch FROM coding_tasks WHERE id=?",
            (task.id,)
        )
        row = cursor.fetchone()
        conn.close()
        
        assert row[0] == "done"
        assert row[1] == "PR created: #42"
        assert row[2] == 0.50
        assert row[3] == 120.0
        assert row[4] == "claude/task-1"


# ═══════════════════════════════════════════════════════════════════════════
# Rate Limiting Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRateLimiting:
    """Test rate limiting logic."""

    def test_can_run_engine_first_task(self, temp_db_path):
        """Test that first task can always run."""
        os.environ["OPENCLAW_DATA_DIR"] = str(Path(temp_db_path).parent)
        can_run, msg = _can_run_engine("claude")
        assert can_run is True

    def test_can_run_engine_under_limit(self, temp_db_path):
        """Test that tasks under limit can run."""
        os.environ["OPENCLAW_DATA_DIR"] = str(Path(temp_db_path).parent)
        now = datetime.now(timezone.utc)

        # Add 2 completed tasks (use different repos to avoid UNIQUE constraint)
        for i in range(2):
            task = add_task(
                repo=f"owner/repo-{i}",
                title=f"Task {i}",
                description=f"Desc {i}",
                engine="claude",
            )
            update_task_status(task.id, TaskStatus.RUNNING.value)
            completed_at = (now - timedelta(minutes=10)).isoformat()
            conn = sqlite3.connect(temp_db_path)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE coding_tasks SET status=?, completed_at=? WHERE id=?",
                (TaskStatus.DONE.value, completed_at, task.id)
            )
            conn.commit()
            conn.close()

        # Should still be able to run (2 < 3)
        can_run, msg = _can_run_engine("claude")
        assert can_run is True

    def test_can_run_engine_at_limit(self, temp_db_path):
        """Test that tasks at limit cannot run."""
        os.environ["OPENCLAW_DATA_DIR"] = str(Path(temp_db_path).parent)
        now = datetime.now(timezone.utc)

        # Add 3 completed tasks within last hour
        for i in range(3):
            task = add_task(
                repo=f"owner/repo-{i}",
                title=f"Task {i}",
                description=f"Desc {i}",
                engine="claude",
            )
            update_task_status(task.id, TaskStatus.RUNNING.value)
            completed_at = (now - timedelta(minutes=10)).isoformat()
            conn = sqlite3.connect(temp_db_path)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE coding_tasks SET status=?, completed_at=? WHERE id=?",
                (TaskStatus.DONE.value, completed_at, task.id)
            )
            conn.commit()
            conn.close()

        # Should not be able to run (3 >= 3)
        can_run, msg = _can_run_engine("claude")
        assert can_run is False

    def test_can_run_engine_outside_window(self, temp_db_path):
        """Test that old completions don't count toward limit."""
        os.environ["OPENCLAW_DATA_DIR"] = str(Path(temp_db_path).parent)
        now = datetime.now(timezone.utc)

        # Add 3 completed tasks OUTSIDE the window (> 1 hour ago)
        for i in range(3):
            task = add_task(
                repo=f"owner/repo-{i}",
                title=f"Task {i}",
                description=f"Desc {i}",
                engine="claude",
            )
            update_task_status(task.id, TaskStatus.RUNNING.value)
            completed_at = (now - timedelta(hours=2)).isoformat()
            conn = sqlite3.connect(temp_db_path)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE coding_tasks SET status=?, completed_at=? WHERE id=?",
                (TaskStatus.DONE.value, completed_at, task.id)
            )
            conn.commit()
            conn.close()

        # Should be able to run (old tasks don't count)
        can_run, msg = _can_run_engine("claude")
        assert can_run is True


# ═══════════════════════════════════════════════════════════════════════════
# Task Lifecycle Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestTaskLifecycle:
    """Test task status transitions."""
    
    def test_task_lifecycle_happy_path(self, temp_db_path):
        """Test normal task progression: pending -> running -> done."""
        os.environ["OPENCLAW_DATA_DIR"] = str(Path(temp_db_path).parent)
        
        task = add_task(
            repo="owner/repo",
            title="Test",
            description="Test",
        )
        
        # Check initial state
        pending = get_pending_tasks()
        assert len(pending) >= 1
        
        # Transition to running
        update_task_status(task.id, TaskStatus.RUNNING.value)
        running = get_running_count()
        assert running >= 1
        
        # Transition to done
        update_task_status(
            task_id=task.id,
            status=TaskStatus.DONE.value,
            result="Success",
            cost_usd=0.25,
            duration_seconds=60.0,
        )

        # Verify final state
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status, result FROM coding_tasks WHERE id=?", (task.id,))
        row = cursor.fetchone()
        conn.close()
        assert row[0] == "done"
        assert row[1] == "Success"
    
    def test_task_lifecycle_failure(self, temp_db_path):
        """Test task failure: pending -> running -> failed."""
        os.environ["OPENCLAW_DATA_DIR"] = str(Path(temp_db_path).parent)

        task = add_task(
            repo="owner/repo",
            title="Test",
            description="Test",
        )
        update_task_status(task.id, TaskStatus.RUNNING.value)

        # Fail the task
        update_task_status(
            task_id=task.id,
            status=TaskStatus.FAILED.value,
            result="",
            cost_usd=0.10,
            duration_seconds=30.0,
            error_message="Timeout: task took too long"
        )
        
        # Verify failure state
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status, error_message FROM coding_tasks WHERE id=?",
            (task.id,)
        )
        row = cursor.fetchone()
        conn.close()
        assert row[0] == "failed"
        assert "Timeout" in row[1]


# ═══════════════════════════════════════════════════════════════════════════
# Priority and Sorting Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPriorityOrdering:
    """Test task sorting by priority."""
    
    def test_pending_ordered_by_priority_descending(self, temp_db_path):
        """Test that pending tasks are ordered by priority (high first)."""
        os.environ["OPENCLAW_DATA_DIR"] = str(Path(temp_db_path).parent)

        # Add tasks in random priority order
        priorities = [5, 9, 2, 8, 1]
        for i, p in enumerate(priorities):
            add_task(
                repo=f"owner/repo-{i}",
                title=f"Task {i}",
                description=f"Desc {i}",
                priority=p,
            )
        
        # Fetch and verify order
        pending = get_pending_tasks()
        fetched_priorities = [task.priority for task in pending]
        expected_order = [9, 8, 5, 2, 1]
        assert fetched_priorities == expected_order
    
    def test_pending_excludes_running(self, temp_db_path):
        """Test that pending tasks don't include running tasks."""
        os.environ["OPENCLAW_DATA_DIR"] = str(Path(temp_db_path).parent)

        tasks = []
        for i in range(3):
            task = add_task(
                repo=f"owner/repo-{i}",
                title=f"Task {i}",
                description=f"Desc {i}",
            )
            tasks.append(task)
        
        # Mark one as running
        update_task_status(tasks[1].id, TaskStatus.RUNNING.value)
        
        # Get pending should exclude the running task
        pending = get_pending_tasks()
        pending_ids = [task.id for task in pending]
        assert tasks[1].id not in pending_ids
        assert tasks[0].id in pending_ids
        assert tasks[2].id in pending_ids


# ═══════════════════════════════════════════════════════════════════════════
# Cost Tracking Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCostTracking:
    """Test cost and duration tracking."""
    
    def test_track_cost_and_duration(self, temp_db_path):
        """Test recording cost and duration."""
        os.environ["OPENCLAW_DATA_DIR"] = str(Path(temp_db_path).parent)

        task = add_task(
            repo="owner/repo",
            title="Test",
            description="Test",
        )
        update_task_status(task.id, TaskStatus.RUNNING.value)

        # Record completion with cost/duration
        update_task_status(
            task_id=task.id,
            status=TaskStatus.DONE.value,
            result="Done",
            cost_usd=0.75,
            duration_seconds=125.5,
        )
        
        # Verify
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT cost_usd, duration_seconds FROM coding_tasks WHERE id=?",
            (task.id,)
        )
        row = cursor.fetchone()
        conn.close()
        
        assert row[0] == 0.75
        assert row[1] == 125.5
    
    def test_cost_aggregation(self, temp_db_path):
        """Test summing costs across tasks."""
        os.environ["OPENCLAW_DATA_DIR"] = str(Path(temp_db_path).parent)

        tasks_costs = [
            ("task-1", 0.25),
            ("task-2", 0.50),
            ("task-3", 0.75),
        ]

        for idx, (task_id, cost) in enumerate(tasks_costs):
            task = add_task(
                repo=f"owner/repo-{idx}",
                title=f"Task {task_id}",
                description="Test",
            )
            update_task_status(task.id, TaskStatus.RUNNING.value)
            update_task_status(
                task_id=task.id,
                status=TaskStatus.DONE.value,
                result="Done",
                cost_usd=cost,
                duration_seconds=60.0,
            )
        
        # Sum costs
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT SUM(cost_usd) FROM coding_tasks WHERE status=?", (TaskStatus.DONE.value,))
        total_cost = cursor.fetchone()[0]
        conn.close()
        
        assert total_cost == 1.50


# ═══════════════════════════════════════════════════════════════════════════
# Engine Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestEngineEnum:
    """Test Engine enum values."""
    
    def test_engine_values(self):
        """Test Engine enum values."""
        assert Engine.CLAUDE.value == "claude"
        assert Engine.CODEX.value == "codex"
        assert Engine.AIDER.value == "aider"
        assert Engine.ANY.value == "any"


# ═══════════════════════════════════════════════════════════════════════════
# TaskStatus Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestTaskStatusEnum:
    """Test TaskStatus enum."""
    
    def test_task_status_values(self):
        """Test TaskStatus enum values."""
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.DONE.value == "done"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.SKIPPED.value == "skipped"
    
    def test_task_status_from_string(self):
        """Test creating TaskStatus from string."""
        status = TaskStatus("done")
        assert status == TaskStatus.DONE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
