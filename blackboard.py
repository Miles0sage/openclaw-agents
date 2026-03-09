"""
Shared State / Blackboard for OpenClaw
=======================================
A persistent key-value store that allows agents and jobs to share context.
Jobs write findings (files changed, patterns discovered, outcomes) and future
jobs read them for context. Entries have optional TTL for auto-cleanup.

SQLite with WAL mode. Entries are scoped by project and job_id.

Usage:
    write("auth_pattern", "JWT with refresh tokens", job_id="job-123", project="barber-crm")
    val = read("auth_pattern", project="barber-crm")
    entries = list_by_project("barber-crm")
    cleanup_expired()
"""

import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("blackboard")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")
DB_PATH = os.path.join(DATA_DIR, "blackboard.db")


def _get_conn() -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode enabled."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table(conn: sqlite3.Connection):
    """Create the entries table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            job_id TEXT DEFAULT '',
            agent TEXT DEFAULT '',
            project TEXT DEFAULT '',
            ttl_seconds INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (key, project)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_entries_project
        ON entries(project)
    """)
    conn.commit()


def write(
    key: str,
    value: str,
    job_id: str = "",
    agent: str = "",
    project: str = "",
    ttl_seconds: int = 0,
):
    """Write or update a blackboard entry.

    Args:
        key: Entry key (e.g. "auth_pattern", "files_changed")
        value: Entry value (any string, often JSON)
        job_id: Job that wrote this entry
        agent: Agent that wrote this entry
        project: Project scope
        ttl_seconds: Auto-expire after this many seconds (0 = never expire)
    """
    conn = _get_conn()
    try:
        _ensure_table(conn)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO entries (key, value, job_id, agent, project, ttl_seconds, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(key, project) DO UPDATE SET
                   value=excluded.value,
                   job_id=excluded.job_id,
                   agent=excluded.agent,
                   ttl_seconds=excluded.ttl_seconds,
                   updated_at=excluded.updated_at""",
            (key, value, job_id, agent, project, ttl_seconds, now, now),
        )
        conn.commit()
        logger.debug(f"Blackboard write: {key} (project={project})")
    except Exception as e:
        logger.warning(f"Blackboard write failed: {e}")
    finally:
        conn.close()


def read(key: str, project: str = "") -> str | None:
    """Read a blackboard entry. Returns value or None if not found/expired."""
    conn = _get_conn()
    try:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT * FROM entries WHERE key = ? AND project = ?",
            (key, project),
        ).fetchone()

        if not row:
            return None

        # Check TTL
        if row["ttl_seconds"] > 0:
            from datetime import datetime as dt
            created = dt.fromisoformat(row["created_at"])
            age = (datetime.now(timezone.utc) - created).total_seconds()
            if age > row["ttl_seconds"]:
                # Expired — clean up
                conn.execute(
                    "DELETE FROM entries WHERE key = ? AND project = ?",
                    (key, project),
                )
                conn.commit()
                return None

        return row["value"]
    except Exception as e:
        logger.warning(f"Blackboard read failed: {e}")
        return None
    finally:
        conn.close()


def list_by_project(project: str) -> list[dict]:
    """List all non-expired entries for a project."""
    conn = _get_conn()
    try:
        _ensure_table(conn)
        rows = conn.execute(
            """SELECT key, value, job_id, agent, ttl_seconds, created_at, updated_at
               FROM entries WHERE project = ? ORDER BY updated_at DESC""",
            (project,),
        ).fetchall()

        results = []
        now = datetime.now(timezone.utc)
        for row in rows:
            # Skip expired entries
            if row["ttl_seconds"] > 0:
                from datetime import datetime as dt
                created = dt.fromisoformat(row["created_at"])
                age = (now - created).total_seconds()
                if age > row["ttl_seconds"]:
                    continue
            results.append(dict(row))

        return results
    except Exception as e:
        logger.warning(f"Blackboard list failed: {e}")
        return []
    finally:
        conn.close()


def cleanup_expired():
    """Remove all expired entries from the blackboard."""
    conn = _get_conn()
    try:
        _ensure_table(conn)
        # Find entries with ttl_seconds > 0 and check if they've expired
        rows = conn.execute(
            "SELECT key, project, ttl_seconds, created_at FROM entries WHERE ttl_seconds > 0"
        ).fetchall()

        now = datetime.now(timezone.utc)
        deleted = 0
        for row in rows:
            from datetime import datetime as dt
            created = dt.fromisoformat(row["created_at"])
            age = (now - created).total_seconds()
            if age > row["ttl_seconds"]:
                conn.execute(
                    "DELETE FROM entries WHERE key = ? AND project = ?",
                    (row["key"], row["project"]),
                )
                deleted += 1

        if deleted:
            conn.commit()
            logger.info(f"Blackboard cleanup: removed {deleted} expired entries")
    except Exception as e:
        logger.warning(f"Blackboard cleanup failed: {e}")
    finally:
        conn.close()


def get_context_for_prompt(project: str, max_entries: int = 5) -> str:
    """Get blackboard entries formatted for injection into agent prompts."""
    entries = list_by_project(project)[:max_entries]
    if not entries:
        return ""

    lines = ["SHARED CONTEXT (from previous jobs):"]
    for e in entries:
        lines.append(f"  - {e['key']}: {e['value'][:200]}")
    return "\n".join(lines)
