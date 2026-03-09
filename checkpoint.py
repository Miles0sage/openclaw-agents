"""
Workflow Checkpoint System for OpenClaw
========================================
Saves execution state after each successful tool call so jobs can resume
from where they left off instead of restarting from scratch.

Primary backend: Supabase (survives reboots, accessible from any device)
Fallback: SQLite with WAL mode for concurrent access.

Usage:
    save_checkpoint(job_id, phase, step_index, tool_iteration, state, messages)
    cp = get_latest_checkpoint(job_id)
    clear_checkpoints(job_id)
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("checkpoint")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")
DB_PATH = os.path.join(DATA_DIR, "checkpoints.db")


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def _sb():
    try:
        from supabase_client import table_insert, table_select, table_delete, is_connected
        return {"insert": table_insert, "select": table_select, "delete": table_delete, "connected": is_connected}
    except Exception:
        return None


def _use_supabase() -> bool:
    try:
        sb = _sb()
        return sb is not None and sb["connected"]()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# SQLite fallback
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            step_index INTEGER NOT NULL DEFAULT 0,
            tool_iteration INTEGER NOT NULL DEFAULT 0,
            state_json TEXT NOT NULL,
            messages_json TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_checkpoints_job
        ON checkpoints(job_id, created_at DESC)
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_checkpoint(
    job_id: str,
    phase: str,
    step_index: int,
    tool_iteration: int,
    state: dict,
    messages: list = None,
    session_context: dict = None,
):
    """Save a checkpoint after a successful tool execution."""
    trimmed_messages = messages[-10:] if messages else []
    now = datetime.now(timezone.utc).isoformat()

    # Merge session context into state for SQLite storage
    if session_context:
        state["_session_context"] = session_context

    # Try Supabase first
    if _use_supabase():
        sb = _sb()
        row = {
            "job_id": job_id,
            "phase": phase,
            "step_index": step_index,
            "tool_iteration": tool_iteration,
            "state": json.dumps(state, default=str),
            "messages": json.dumps(trimmed_messages, default=str),
            "created_at": now,
        }
        if session_context:
            row["session_context"] = json.dumps(session_context, default=str)
        result = sb["insert"]("checkpoints", row)
        if result:
            logger.debug(f"Checkpoint saved (Supabase): job={job_id} phase={phase} step={step_index}")
            return
        logger.warning(f"Supabase checkpoint save failed for {job_id}, falling back to SQLite")

    # SQLite fallback
    conn = _get_conn()
    try:
        _ensure_table(conn)
        conn.execute(
            """INSERT INTO checkpoints
               (job_id, phase, step_index, tool_iteration, state_json, messages_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (job_id, phase, step_index, tool_iteration,
             json.dumps(state, default=str), json.dumps(trimmed_messages, default=str), now),
        )
        conn.commit()
        logger.debug(f"Checkpoint saved (SQLite): job={job_id} phase={phase} step={step_index}")
    except Exception as e:
        logger.warning(f"Failed to save checkpoint for {job_id}: {e}")
    finally:
        conn.close()


def get_latest_checkpoint(job_id: str) -> dict | None:
    """Get the most recent checkpoint for a job."""
    # Try Supabase first
    if _use_supabase():
        sb = _sb()
        rows = sb["select"]("checkpoints", f"job_id=eq.{job_id}&order=created_at.desc", limit=1)
        if rows:
            row = rows[0]
            state = row.get("state", "{}")
            msgs = row.get("messages", "[]")
            return {
                "job_id": row["job_id"],
                "phase": row["phase"],
                "step_index": row.get("step_index", 0),
                "tool_iteration": row.get("tool_iteration", 0),
                "state": json.loads(state) if isinstance(state, str) else state,
                "messages": json.loads(msgs) if isinstance(msgs, str) else msgs,
                "created_at": row.get("created_at", ""),
            }

    # SQLite fallback
    conn = _get_conn()
    try:
        _ensure_table(conn)
        row = conn.execute(
            """SELECT * FROM checkpoints
               WHERE job_id = ? ORDER BY created_at DESC LIMIT 1""",
            (job_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "job_id": row["job_id"],
            "phase": row["phase"],
            "step_index": row["step_index"],
            "tool_iteration": row["tool_iteration"],
            "state": json.loads(row["state_json"]),
            "messages": json.loads(row["messages_json"]) if row["messages_json"] else [],
            "created_at": row["created_at"],
        }
    except Exception as e:
        logger.warning(f"Failed to get checkpoint for {job_id}: {e}")
        return None
    finally:
        conn.close()


def clear_checkpoints(job_id: str):
    """Remove all checkpoints for a completed/cancelled job."""
    if _use_supabase():
        sb = _sb()
        result = sb["delete"]("checkpoints", f"job_id=eq.{job_id}")
        if result:
            logger.debug(f"Checkpoints cleared (Supabase) for job {job_id}")
            return

    conn = _get_conn()
    try:
        _ensure_table(conn)
        conn.execute("DELETE FROM checkpoints WHERE job_id = ?", (job_id,))
        conn.commit()
        logger.debug(f"Checkpoints cleared (SQLite) for job {job_id}")
    except Exception as e:
        logger.warning(f"Failed to clear checkpoints for {job_id}: {e}")
    finally:
        conn.close()


def list_checkpoints(job_id: str = None) -> list:
    """List checkpoints, optionally filtered by job_id."""
    if _use_supabase():
        sb = _sb()
        query = "order=created_at.desc"
        if job_id:
            query = f"job_id=eq.{job_id}&{query}"
        rows = sb["select"]("checkpoints", query, limit=50)
        if rows is not None:
            return rows

    conn = _get_conn()
    try:
        _ensure_table(conn)
        if job_id:
            rows = conn.execute(
                """SELECT job_id, phase, step_index, tool_iteration, created_at
                   FROM checkpoints WHERE job_id = ? ORDER BY created_at DESC""",
                (job_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT job_id, phase, step_index, tool_iteration, created_at
                   FROM checkpoints ORDER BY created_at DESC LIMIT 50"""
            ).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.warning(f"Failed to list checkpoints: {e}")
        return []
    finally:
        conn.close()


def count_checkpoints(job_id: str) -> int:
    """Count checkpoints for a job."""
    if _use_supabase():
        sb = _sb()
        rows = sb["select"]("checkpoints", f"job_id=eq.{job_id}&select=id", limit=5000)
        if rows is not None:
            return len(rows)

    conn = _get_conn()
    try:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM checkpoints WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return row["cnt"] if row else 0
    except Exception:
        return 0
    finally:
        conn.close()
