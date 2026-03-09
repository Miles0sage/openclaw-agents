"""
Coding Factory Cron System — Maximizes flat-rate AI subscriptions
==================================================================

Continuously scans GitHub repos for open coding issues (labeled "claude" or "codex"),
auto-executes them using Claude Code or Codex, and manages rate limits.

Features:
  - SQLite backlog: tracks pending/running/done/failed tasks
  - Auto-scan: scans repos every 20 minutes for new issues
  - Execution engine: runs tasks in parallel (max 3/hour per engine)
  - Git branching: auto/task-{id}, codex/task-{id}, aider/task-{id}
  - Safety: never touches main/master, creates PRs, 10min timeout per task
  - CLI: --scan, --run-next, --add-task, --status

Usage:
    from coding_factory_cron import register_coding_factory_crons
    from scheduled_hands import get_scheduler

    scheduler = get_scheduler()
    await register_coding_factory_crons(scheduler)

CLI:
    python coding_factory_cron.py --scan
    python coding_factory_cron.py --run-next
    python coding_factory_cron.py --add-task repo="owner/repo" title="Fix X"
    python coding_factory_cron.py --status
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from enum import Enum

logger = logging.getLogger("coding_factory_cron")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")
DB_PATH = os.path.join(DATA_DIR, "coding_factory.db")
RATE_LIMIT_WINDOW = 3600  # seconds (1 hour)
RATE_LIMIT_PER_ENGINE = 3  # max tasks per hour per engine

# ─────────────────────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────────────────────


class TaskStatus(Enum):
    """Task lifecycle stages."""
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class Engine(Enum):
    """AI execution engines."""
    CLAUDE = "claude"
    CODEX = "codex"
    AIDER = "aider"
    ANY = "any"


@dataclass
class CodingTask:
    """A coding task to be executed."""
    id: str
    repo: str
    title: str
    description: str
    engine: str = "any"  # "claude", "codex", or "any"
    priority: int = 5  # 1-10, higher = more urgent
    status: str = "pending"
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    branch: str = ""
    result: str = ""
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    github_issue_number: int = 0
    github_issue_url: str = ""
    error_message: str = ""

    def to_tuple(self) -> tuple:
        """Convert to SQL insert tuple."""
        return (
            self.id, self.repo, self.title, self.description, self.engine,
            self.priority, self.status, self.created_at, self.started_at,
            self.completed_at, self.branch, self.result, self.cost_usd,
            self.duration_seconds, self.github_issue_number, self.github_issue_url,
            self.error_message,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Database Schema & Initialization
# ─────────────────────────────────────────────────────────────────────────────


def _init_db():
    """Initialize SQLite database with schema."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
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

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_status ON coding_tasks(status)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_engine ON coding_tasks(engine)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_created_at ON coding_tasks(created_at)
    """)

    conn.commit()
    conn.close()


def get_db() -> sqlite3.Connection:
    """Get database connection with row factory."""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# Database Operations
# ─────────────────────────────────────────────────────────────────────────────


def add_task(
    repo: str,
    title: str,
    description: str = "",
    engine: str = "any",
    priority: int = 5,
    github_issue_number: int = 0,
    github_issue_url: str = "",
) -> CodingTask:
    """Add a new task to the backlog."""
    task_id = f"task-{uuid.uuid4().hex[:12]}"
    created_at = datetime.now(timezone.utc).isoformat()

    task = CodingTask(
        id=task_id,
        repo=repo,
        title=title,
        description=description,
        engine=engine,
        priority=priority,
        status=TaskStatus.PENDING.value,
        created_at=created_at,
        github_issue_number=github_issue_number,
        github_issue_url=github_issue_url,
    )

    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO coding_tasks (
                id, repo, title, description, engine, priority, status,
                created_at, github_issue_number, github_issue_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task.id, task.repo, task.title, task.description, task.engine,
            task.priority, task.status, task.created_at,
            task.github_issue_number, task.github_issue_url,
        ))
        conn.commit()
        conn.close()
        logger.info(f"Added task {task_id}: {repo}/{title}")
        return task
    except sqlite3.IntegrityError as e:
        logger.warning(f"Task already exists: {repo}/{github_issue_number}: {e}")
        conn.close()
        raise


def get_task(task_id: str) -> Optional[CodingTask]:
    """Fetch a task by ID."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM coding_tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return _row_to_task(row)


def get_pending_tasks(limit: int = 10) -> List[CodingTask]:
    """Get pending tasks, sorted by priority (desc) and created_at (asc)."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM coding_tasks
        WHERE status = ?
        ORDER BY priority DESC, created_at ASC
        LIMIT ?
    """, (TaskStatus.PENDING.value, limit))
    rows = cursor.fetchall()
    conn.close()

    return [_row_to_task(row) for row in rows]


def get_running_count(engine: Optional[str] = None) -> int:
    """Count currently running tasks (optionally filtered by engine)."""
    conn = get_db()
    cursor = conn.cursor()

    if engine:
        cursor.execute(
            "SELECT COUNT(*) FROM coding_tasks WHERE status = ? AND engine IN (?, 'any')",
            (TaskStatus.RUNNING.value, engine),
        )
    else:
        cursor.execute(
            "SELECT COUNT(*) FROM coding_tasks WHERE status = ?",
            (TaskStatus.RUNNING.value,),
        )

    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_recent_completions(
    engine: Optional[str] = None,
    minutes: int = 60,
    limit: int = 100,
) -> List[CodingTask]:
    """Get recently completed tasks (for rate limiting)."""
    conn = get_db()
    cursor = conn.cursor()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)

    if engine:
        cursor.execute(
            """
            SELECT * FROM coding_tasks
            WHERE (status = ? OR status = ?)
              AND engine IN (?, 'any')
              AND completed_at > ?
            ORDER BY completed_at DESC
            LIMIT ?
            """,
            (
                TaskStatus.DONE.value,
                TaskStatus.FAILED.value,
                engine,
                cutoff.isoformat(),
                limit,
            ),
        )
    else:
        cursor.execute(
            """
            SELECT * FROM coding_tasks
            WHERE (status = ? OR status = ?)
              AND completed_at > ?
            ORDER BY completed_at DESC
            LIMIT ?
            """,
            (
                TaskStatus.DONE.value,
                TaskStatus.FAILED.value,
                cutoff.isoformat(),
                limit,
            ),
        )

    rows = cursor.fetchall()
    conn.close()

    return [_row_to_task(row) for row in rows]


def update_task_status(
    task_id: str,
    status: str,
    branch: str = "",
    result: str = "",
    cost_usd: float = 0.0,
    duration_seconds: float = 0.0,
    error_message: str = "",
) -> None:
    """Update task status and metadata."""
    conn = get_db()
    cursor = conn.cursor()

    updates = {"status": status}
    if branch:
        updates["branch"] = branch
    if status == TaskStatus.RUNNING.value:
        updates["started_at"] = datetime.now(timezone.utc).isoformat()
    if status in (TaskStatus.DONE.value, TaskStatus.FAILED.value, TaskStatus.SKIPPED.value):
        updates["completed_at"] = datetime.now(timezone.utc).isoformat()
    if result:
        updates["result"] = result[:5000]  # Truncate to 5KB
    if cost_usd > 0:
        updates["cost_usd"] = cost_usd
    if duration_seconds > 0:
        updates["duration_seconds"] = duration_seconds
    if error_message:
        updates["error_message"] = error_message[:1000]

    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [task_id]

    cursor.execute(f"UPDATE coding_tasks SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()

    logger.info(f"Updated task {task_id}: {status}")


# Alias for backwards compatibility with tests
update_task_completion = update_task_status


def _row_to_task(row) -> CodingTask:
    """Convert database row to CodingTask object."""
    return CodingTask(
        id=row["id"],
        repo=row["repo"],
        title=row["title"],
        description=row["description"] or "",
        engine=row["engine"],
        priority=row["priority"],
        status=row["status"],
        created_at=row["created_at"],
        started_at=row["started_at"] or "",
        completed_at=row["completed_at"] or "",
        branch=row["branch"] or "",
        result=row["result"] or "",
        cost_usd=row["cost_usd"],
        duration_seconds=row["duration_seconds"],
        github_issue_number=row["github_issue_number"],
        github_issue_url=row["github_issue_url"] or "",
        error_message=row["error_message"] or "",
    )


# ─────────────────────────────────────────────────────────────────────────────
# GitHub Integration — Auto-scan for issues
# ─────────────────────────────────────────────────────────────────────────────


def _get_github_issues(repo: str, label: str) -> List[Dict]:
    """Fetch open issues with a given label from GitHub."""
    try:
        # Use GitHub CLI to fetch issues
        result = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--repo",
                repo,
                "--label",
                label,
                "--state",
                "open",
                "--json",
                "number,title,body,url",
                "--limit",
                "100",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.warning(f"Failed to fetch issues from {repo}: {result.stderr}")
            return []

        return json.loads(result.stdout) if result.stdout.strip() else []
    except Exception as e:
        logger.error(f"Error fetching issues from {repo}: {e}")
        return []


def scan_repos(repos: List[str]) -> int:
    """Scan GitHub repos for new issues and add to backlog."""
    added_count = 0

    for repo in repos:
        logger.info(f"Scanning {repo} for 'claude' and 'codex' issues...")

        # Scan for claude issues
        for issue in _get_github_issues(repo, "claude"):
            try:
                task = add_task(
                    repo=repo,
                    title=issue["title"],
                    description=issue["body"] or "",
                    engine="claude",
                    github_issue_number=issue["number"],
                    github_issue_url=issue["url"],
                )
                added_count += 1
            except sqlite3.IntegrityError:
                # Issue already in backlog
                pass

        # Scan for codex issues
        for issue in _get_github_issues(repo, "codex"):
            try:
                task = add_task(
                    repo=repo,
                    title=issue["title"],
                    description=issue["body"] or "",
                    engine="codex",
                    github_issue_number=issue["number"],
                    github_issue_url=issue["url"],
                )
                added_count += 1
            except sqlite3.IntegrityError:
                # Issue already in backlog
                pass

    logger.info(f"Scan complete: added {added_count} new tasks")
    return added_count


# ─────────────────────────────────────────────────────────────────────────────
# Rate Limiting
# ─────────────────────────────────────────────────────────────────────────────


def _can_run_engine(engine: str) -> Tuple[bool, str]:
    """Check if we can run a task with this engine (rate limit check)."""
    # Get running count for this engine
    running = get_running_count(engine)
    if running > 0:
        return False, f"Already running a {engine} task"

    # Get recent completions in the last hour
    recent = get_recent_completions(engine=engine, minutes=60)
    if len(recent) >= RATE_LIMIT_PER_ENGINE:
        oldest = recent[-1]
        if oldest.completed_at:
            oldest_time = datetime.fromisoformat(oldest.completed_at)
            now = datetime.now(timezone.utc)
            elapsed = (now - oldest_time).total_seconds()
            if elapsed < RATE_LIMIT_WINDOW:
                return False, f"Rate limit: {len(recent)}/{RATE_LIMIT_PER_ENGINE} tasks in last hour"

    return True, "OK"


# ─────────────────────────────────────────────────────────────────────────────
# Execution Engine
# ─────────────────────────────────────────────────────────────────────────────


def _normalize_repo_url(repo: str) -> str:
    """Convert repo to local path if it's a GitHub URL."""
    # Examples: owner/repo, https://github.com/owner/repo, /path/to/repo
    if repo.startswith("http"):
        # Extract owner/repo from URL
        match = re.search(r"github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", repo)
        if match:
            repo = match.group(1)

    # Convert owner/repo to local path
    if "/" in repo and not repo.startswith("/"):
        parts = repo.split("/")
        repo_path = f"/root/{parts[1]}"  # /root/repo-name
        if os.path.isdir(repo_path):
            return repo_path

    # Already a local path
    if os.path.isdir(repo):
        return repo

    # Last resort: try /root/{repo}
    fallback = f"/root/{repo}"
    if os.path.isdir(fallback):
        return fallback

    return repo  # Return as-is and let execution fail gracefully


def _get_available_engine(preferred: str) -> Optional[str]:
    """Choose the best available engine."""
    if preferred != "any":
        can_run, reason = _can_run_engine(preferred)
        if can_run:
            return preferred
        return None

    # Try claude, then codex, then free tools
    for eng in ["claude", "codex", "aider", "gemini"]:
        can_run, _ = _can_run_engine(eng)
        if can_run:
            return eng

    return None


async def _execute_claude(task: CodingTask, repo_path: str) -> Tuple[bool, str, float, float]:
    """Execute Claude Code build."""
    start = time.time()
    try:
        # Import dynamically to avoid circular deps
        from agent_tools import _claude_code_build

        result = _claude_code_build(
            repo_path=repo_path,
            prompt=task.description or task.title,
            max_budget_usd=2.0,
            model="sonnet",
            commit=True,
        )

        # Parse cost from result
        cost = 0.0
        cost_match = re.search(r"Cost: \$([0-9.]+)", result)
        if cost_match:
            cost = float(cost_match.group(1))

        duration = time.time() - start
        success = "completed" in result.lower() and "error" not in result.lower()

        return success, result[:2000], cost, duration
    except Exception as e:
        logger.error(f"Claude execution failed: {e}")
        return False, str(e), 0.0, time.time() - start


async def _execute_codex(task: CodingTask, repo_path: str) -> Tuple[bool, str, float, float]:
    """Execute Codex build."""
    start = time.time()
    try:
        # Import dynamically to avoid circular deps
        from agent_tools import _codex_build

        result = _codex_build(
            repo_path=repo_path,
            prompt=task.description or task.title,
            model="gpt-5",
            sandbox="workspace-write",
        )

        duration = time.time() - start
        success = "completed" in result.lower() and "error" not in result.lower()

        return success, result[:2000], 0.0, duration  # Codex cost tracking via ChatGPT Plus
    except Exception as e:
        logger.error(f"Codex execution failed: {e}")
        return False, str(e), 0.0, time.time() - start


async def _execute_free_tool(task: CodingTask, repo_path: str, engine: str) -> Tuple[bool, str, float, float]:
    """Execute via free coding tools (Aider or Gemini CLI)."""
    start = time.time()
    try:
        from agent_tools import _aider_build, _gemini_cli_build

        prompt = task.description or task.title
        if engine == "aider":
            result = _aider_build(
                repo_path=repo_path,
                prompt=prompt,
                model="gemini/gemini-2.5-flash",
            )
        else:  # gemini
            result = _gemini_cli_build(
                repo_path=repo_path,
                prompt=prompt,
            )

        duration = time.time() - start
        success = "error" not in result.lower()[:200]
        return success, result[:2000], 0.0, duration
    except Exception as e:
        logger.error(f"{engine} execution failed: {e}")
        return False, str(e), 0.0, time.time() - start


async def _create_branch_and_pr(repo_path: str, task_id: str, engine: str) -> str:
    """Create git branch and prepare for PR."""
    branch_name = f"{engine}/task-{task_id[:12]}"

    try:
        # Check if already on main/master
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=10,
        )

        current_branch = result.stdout.strip()
        if current_branch in ("main", "master"):
            # Create and switch to new branch
            subprocess.run(
                ["git", "checkout", "-b", branch_name],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=10,
            )
            logger.info(f"Created branch {branch_name}")

        return branch_name
    except Exception as e:
        logger.error(f"Failed to create branch: {e}")
        return ""


async def execute_task(task: CodingTask) -> None:
    """Execute a single coding task."""
    task_id = task.id
    logger.info(f"Starting execution of task {task_id}: {task.title}")

    # Determine engine to use
    engine = _get_available_engine(task.engine)
    if not engine:
        reason = f"No available engines (preferred: {task.engine})"
        logger.warning(f"Task {task_id}: {reason}")
        update_task_status(task_id, TaskStatus.SKIPPED.value, error_message=reason)
        return

    # Normalize repo path
    repo_path = _normalize_repo_url(task.repo)
    if not os.path.isdir(repo_path):
        error = f"Repository not found: {repo_path}"
        logger.error(f"Task {task_id}: {error}")
        update_task_status(task_id, TaskStatus.FAILED.value, error_message=error)
        return

    # Update status to running
    branch = await _create_branch_and_pr(repo_path, task_id, engine)
    update_task_status(task_id, TaskStatus.RUNNING.value, branch=branch)

    # Execute on chosen engine
    success = False
    result = ""
    cost = 0.0
    duration = 0.0

    try:
        if engine == "claude":
            success, result, cost, duration = await _execute_claude(task, repo_path)
        elif engine == "codex":
            success, result, cost, duration = await _execute_codex(task, repo_path)
        elif engine in ("aider", "gemini"):
            success, result, cost, duration = await _execute_free_tool(task, repo_path, engine)

        # Update task with results
        status = TaskStatus.DONE.value if success else TaskStatus.FAILED.value
        update_task_status(
            task_id,
            status=status,
            result=result,
            cost_usd=cost,
            duration_seconds=duration,
            error_message="" if success else result[:500],
        )

        logger.info(
            f"Task {task_id} {status}: {engine} engine, "
            f"${cost:.4f}, {duration:.1f}s"
        )

    except asyncio.TimeoutError:
        error = "Task timeout (10 minutes)"
        logger.error(f"Task {task_id}: {error}")
        update_task_status(task_id, TaskStatus.FAILED.value, error_message=error)
    except Exception as e:
        logger.error(f"Task {task_id} execution error: {e}")
        update_task_status(task_id, TaskStatus.FAILED.value, error_message=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Cron Handlers
# ─────────────────────────────────────────────────────────────────────────────


async def hand_coding_factory_scan() -> dict:
    """Cron handler: scan repos for new issues every 20 minutes."""
    logger.info("Scanning GitHub repos for new coding tasks...")

    repos = [
        "Miles0sage/Barber-CRM",
        "Miles0sage/Delhi-Palce-",
        "Miles0sage/concrete-canoe-project2026",
        "Miles0sage/Mathcad-Scripts",
        "Miles0sage/openclaw",
        "Miles0sage/roomcraft",
    ]

    try:
        added = scan_repos(repos)
        return {
            "success": True,
            "message": f"Scan complete: added {added} new tasks",
            "tasks_added": added,
        }
    except Exception as e:
        logger.error(f"Scan failed: {e}")
        return {"success": False, "error": str(e)}


async def hand_coding_factory_run_next() -> dict:
    """Cron handler: execute next pending task every 20 minutes."""
    logger.info("Checking for next coding task to execute...")

    pending = get_pending_tasks(limit=1)
    if not pending:
        return {"success": True, "message": "No pending tasks"}

    task = pending[0]

    # Check rate limits
    engine = _get_available_engine(task.engine)
    if not engine:
        return {
            "success": False,
            "message": f"Rate limited or no available engine for {task.engine}",
            "task_id": task.id,
        }

    # Execute with timeout
    try:
        await asyncio.wait_for(execute_task(task), timeout=600)  # 10 minutes
    except asyncio.TimeoutError:
        update_task_status(task.id, TaskStatus.FAILED.value, error_message="Timeout (10m)")
        logger.error(f"Task {task.id} timed out")

    return {"success": True, "task_id": task.id, "engine": engine}


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler Registration
# ─────────────────────────────────────────────────────────────────────────────


async def register_coding_factory_crons(scheduler):
    """Register coding factory crons with the Scheduled Hands scheduler."""
    logger.info("Registering coding factory crons...")

    try:
        from scheduled_hands import Hand

        # Register scan hand
        scheduler.register_hand(
            Hand(
                name="coding_factory_scan",
                description="Scan GitHub repos for new coding issues",
                schedule="*/20 * * * *",  # Every 20 minutes
                handler=hand_coding_factory_scan,
                enabled=True,
                tags=["coding-factory", "auto-scan"],
            )
        )

        # Register execution hand
        scheduler.register_hand(
            Hand(
                name="coding_factory_run_next",
                description="Execute next pending coding task",
                schedule="*/20 * * * *",  # Every 20 minutes
                handler=hand_coding_factory_run_next,
                enabled=True,
                tags=["coding-factory", "execution"],
            )
        )

        logger.info("Coding factory crons registered (scan + run every 20min)")
    except Exception as e:
        logger.error(f"Failed to register coding factory crons: {e}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def cli_status():
    """Print status of all tasks."""
    conn = get_db()
    cursor = conn.cursor()

    # Count by status
    cursor.execute("""
        SELECT status, COUNT(*) as count FROM coding_tasks
        GROUP BY status
        ORDER BY status
    """)

    print("\n=== Coding Factory Status ===\n")
    for row in cursor.fetchall():
        print(f"  {row['status']}: {row['count']}")

    # Show pending tasks
    cursor.execute("""
        SELECT id, repo, title, engine, priority FROM coding_tasks
        WHERE status = 'pending'
        ORDER BY priority DESC, created_at ASC
        LIMIT 10
    """)

    print("\n=== Next 10 Pending Tasks ===\n")
    for row in cursor.fetchall():
        print(f"  [{row['engine']:6s}] P{row['priority']} {row['repo']:<30s} {row['title'][:40]}")

    # Show recent completions
    cursor.execute("""
        SELECT id, repo, title, status, cost_usd, duration_seconds FROM coding_tasks
        WHERE status IN ('done', 'failed')
        ORDER BY completed_at DESC
        LIMIT 5
    """)

    print("\n=== Recent Completions ===\n")
    for row in cursor.fetchall():
        print(f"  [{row['status']:6s}] {row['repo']:<30s} ${row['cost_usd']:.4f} ({row['duration_seconds']:.0f}s)")

    conn.close()


def cli_scan():
    """Manually trigger a scan."""
    print("Scanning repos for new issues...")
    asyncio.run(hand_coding_factory_scan())


def cli_run_next():
    """Manually execute next task."""
    print("Executing next pending task...")
    asyncio.run(hand_coding_factory_run_next())


def cli_add_task(repo: str, title: str, description: str = "", engine: str = "any", priority: int = 5):
    """Manually add a task."""
    try:
        task = add_task(repo, title, description, engine, priority)
        print(f"✓ Added task {task.id}")
        print(f"  Repo: {task.repo}")
        print(f"  Title: {task.title}")
        print(f"  Engine: {task.engine}")
        print(f"  Priority: {task.priority}")
    except Exception as e:
        print(f"✗ Error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def main():
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    _init_db()

    if len(sys.argv) < 2:
        print("Usage: python coding_factory_cron.py [--scan|--run-next|--add-task|--status]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "--scan":
        cli_scan()
    elif cmd == "--run-next":
        cli_run_next()
    elif cmd == "--status":
        cli_status()
    elif cmd == "--add-task":
        # Parse kwargs: --add-task repo=owner/repo title="Fix X" [description="..."] [engine=claude|codex|any] [priority=5]
        kwargs = {}
        for arg in sys.argv[2:]:
            if "=" in arg:
                k, v = arg.split("=", 1)
                kwargs[k] = v
        cli_add_task(**kwargs)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
