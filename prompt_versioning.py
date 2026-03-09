"""
Prompt Versioning System for OpenClaw
====================================

Tracks evolution of agent system prompts based on performance.
Enables prompt mutations, auto-promotion, auto-rollback, and historical analysis.

Features:
  - Store multiple prompt versions per agent with full history
  - Record success/failure outcomes per version
  - Auto-promote higher-performing variants
  - Auto-rollback degradations
  - Maintain parent-child relationships for prompt lineage
  - Query performance metrics across versions

Database: os.environ.get("OPENCLAW_DATA_DIR", "./data")/prompt_versions.db
Schema:
  - prompt_versions: version_id, agent_key, system_prompt, created_at, is_active
  - version_outcomes: version_id, success (bool), job_id, timestamp
  - parent_relationships: version_id, parent_version_id
"""

import json
import logging
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger("prompt_versioning")


DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "os.environ.get("OPENCLAW_DATA_DIR", "./data")")
PROMPT_VERSIONS_DB = os.path.join(DATA_DIR, "prompt_versions.db")


@dataclass
class PromptVersion:
    """Represents a single version of an agent's system prompt.

    Attributes:
        version_id: UUID identifier for this version
        agent_key: Agent identifier (e.g., "codegen_pro", "pentest_ai")
        system_prompt: The actual system prompt text
        created_at: ISO timestamp when this version was created
        success_rate: Current success rate (0.0-1.0)
        total_jobs: Number of jobs executed with this version
        successful_jobs: Number of successful jobs
        parent_version: version_id of the parent version (if mutated from existing)
        is_active: Whether this is the currently active version for the agent
    """
    version_id: str
    agent_key: str
    system_prompt: str
    created_at: str
    success_rate: float = 0.0
    total_jobs: int = 0
    successful_jobs: int = 0
    parent_version: Optional[str] = None
    is_active: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class PromptVersionStore:
    """SQLite-backed store for prompt versions with auto-promotion/rollback logic."""

    def __init__(self, db_path: str = PROMPT_VERSIONS_DB):
        self.db_path = db_path
        self._ensure_db()

    def _ensure_db(self):
        """Create tables if they don't exist."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Main versions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prompt_versions (
                version_id TEXT PRIMARY KEY,
                agent_key TEXT NOT NULL,
                system_prompt TEXT NOT NULL,
                created_at TEXT NOT NULL,
                total_jobs INTEGER DEFAULT 0,
                successful_jobs INTEGER DEFAULT 0,
                parent_version TEXT,
                is_active INTEGER DEFAULT 0,
                created_by TEXT DEFAULT 'system',
                notes TEXT
            )
        """)

        # Outcomes tracking (one row per job outcome)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS version_outcomes (
                outcome_id TEXT PRIMARY KEY,
                version_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                success INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                phase TEXT,
                error_message TEXT,
                FOREIGN KEY (version_id) REFERENCES prompt_versions (version_id)
            )
        """)

        # Index for quick lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent_active
            ON prompt_versions(agent_key, is_active)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_version_outcomes
            ON version_outcomes(version_id, timestamp)
        """)

        conn.commit()
        conn.close()

    def save_version(
        self,
        agent_key: str,
        system_prompt: str,
        parent_version: Optional[str] = None,
        notes: str = "",
        created_by: str = "system",
    ) -> str:
        """Save a new prompt version. Returns the version_id.

        Args:
            agent_key: Agent identifier
            system_prompt: The system prompt text
            parent_version: If this is a mutation, the parent's version_id
            notes: Optional notes about why this version was created
            created_by: Who created this version (for audit trail)

        Returns:
            The new version_id
        """
        version_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO prompt_versions
            (version_id, agent_key, system_prompt, created_at, parent_version, created_by, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (version_id, agent_key, system_prompt, created_at, parent_version, created_by, notes),
        )

        conn.commit()
        conn.close()

        logger.info(
            f"Saved prompt version {version_id} for agent {agent_key} "
            f"(parent={parent_version})"
        )
        return version_id

    def get_active_version(self, agent_key: str) -> Optional[PromptVersion]:
        """Get the currently active prompt version for an agent.

        Returns None if no version has been activated yet.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT version_id, agent_key, system_prompt, created_at,
                   total_jobs, successful_jobs, parent_version, is_active
            FROM prompt_versions
            WHERE agent_key = ? AND is_active = 1
            LIMIT 1
            """,
            (agent_key,),
        )

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        version_id, agent_key_val, prompt, created_at, total, successful, parent, is_active = row
        return PromptVersion(
            version_id=version_id,
            agent_key=agent_key_val,
            system_prompt=prompt,
            created_at=created_at,
            success_rate=successful / total if total > 0 else 0.0,
            total_jobs=total,
            successful_jobs=successful,
            parent_version=parent,
            is_active=bool(is_active),
        )

    def record_outcome(
        self,
        version_id: str,
        success: bool,
        job_id: str,
        phase: str = "",
        error_message: str = "",
    ) -> None:
        """Record an outcome (success/failure) for a version.

        Auto-updates total_jobs and successful_jobs in prompt_versions.
        """
        outcome_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Insert outcome record
        cursor.execute(
            """
            INSERT INTO version_outcomes
            (outcome_id, version_id, job_id, success, timestamp, phase, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (outcome_id, version_id, job_id, 1 if success else 0, timestamp, phase, error_message),
        )

        # Update aggregates in prompt_versions
        cursor.execute(
            """
            UPDATE prompt_versions
            SET total_jobs = total_jobs + 1,
                successful_jobs = successful_jobs + ?
            WHERE version_id = ?
            """,
            (1 if success else 0, version_id),
        )

        conn.commit()
        conn.close()

        logger.info(
            f"Recorded outcome for version {version_id}: {'success' if success else 'failure'} "
            f"(job={job_id})"
        )

    def promote_version(self, version_id: str) -> bool:
        """Promote a version to active status, demoting the previous active version.

        Returns True if successful, False if version not found.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get the agent_key for this version
        cursor.execute("SELECT agent_key FROM prompt_versions WHERE version_id = ?", (version_id,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            logger.warning(f"Version {version_id} not found")
            return False

        agent_key = row[0]

        # Deactivate all other versions for this agent
        cursor.execute(
            "UPDATE prompt_versions SET is_active = 0 WHERE agent_key = ?",
            (agent_key,),
        )

        # Activate this version
        cursor.execute(
            "UPDATE prompt_versions SET is_active = 1 WHERE version_id = ?",
            (version_id,),
        )

        conn.commit()
        conn.close()

        logger.info(f"Promoted version {version_id} to active for agent {agent_key}")
        return True

    def rollback(self, agent_key: str) -> Optional[PromptVersion]:
        """Rollback to the previous version for an agent.

        Returns the new active version, or None if no previous version exists.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get current active version
        cursor.execute(
            """
            SELECT version_id FROM prompt_versions
            WHERE agent_key = ? AND is_active = 1
            LIMIT 1
            """,
            (agent_key,),
        )
        current = cursor.fetchone()

        if not current:
            conn.close()
            logger.warning(f"No active version to rollback from for agent {agent_key}")
            return None

        current_version_id = current[0]

        # Get the parent of current version
        cursor.execute(
            "SELECT parent_version FROM prompt_versions WHERE version_id = ?",
            (current_version_id,),
        )
        parent_row = cursor.fetchone()

        if not parent_row or not parent_row[0]:
            conn.close()
            logger.warning(f"No parent version for {current_version_id} — cannot rollback")
            return None

        parent_version_id = parent_row[0]

        # Deactivate current
        cursor.execute(
            "UPDATE prompt_versions SET is_active = 0 WHERE version_id = ?",
            (current_version_id,),
        )

        # Activate parent
        cursor.execute(
            "UPDATE prompt_versions SET is_active = 1 WHERE version_id = ?",
            (parent_version_id,),
        )

        conn.commit()

        # Fetch and return the new active version
        cursor.execute(
            """
            SELECT version_id, agent_key, system_prompt, created_at,
                   total_jobs, successful_jobs, parent_version, is_active
            FROM prompt_versions
            WHERE version_id = ?
            """,
            (parent_version_id,),
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            version_id, agent_key_val, prompt, created_at, total, successful, parent, is_active = row
            version = PromptVersion(
                version_id=version_id,
                agent_key=agent_key_val,
                system_prompt=prompt,
                created_at=created_at,
                success_rate=successful / total if total > 0 else 0.0,
                total_jobs=total,
                successful_jobs=successful,
                parent_version=parent,
                is_active=bool(is_active),
            )
            logger.info(f"Rolled back agent {agent_key} from {current_version_id} to {parent_version_id}")
            return version

        return None

    def get_history(self, agent_key: str) -> List[PromptVersion]:
        """Get all versions for an agent, ordered by creation time (newest first)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT version_id, agent_key, system_prompt, created_at,
                   total_jobs, successful_jobs, parent_version, is_active
            FROM prompt_versions
            WHERE agent_key = ?
            ORDER BY created_at DESC
            """,
            (agent_key,),
        )

        rows = cursor.fetchall()
        conn.close()

        versions = []
        for row in rows:
            version_id, agent_key_val, prompt, created_at, total, successful, parent, is_active = row
            versions.append(
                PromptVersion(
                    version_id=version_id,
                    agent_key=agent_key_val,
                    system_prompt=prompt,
                    created_at=created_at,
                    success_rate=successful / total if total > 0 else 0.0,
                    total_jobs=total,
                    successful_jobs=successful,
                    parent_version=parent,
                    is_active=bool(is_active),
                )
            )

        return versions

    def get_version(self, version_id: str) -> Optional[PromptVersion]:
        """Get a specific version by ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT version_id, agent_key, system_prompt, created_at,
                   total_jobs, successful_jobs, parent_version, is_active
            FROM prompt_versions
            WHERE version_id = ?
            """,
            (version_id,),
        )

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        version_id_val, agent_key, prompt, created_at, total, successful, parent, is_active = row
        return PromptVersion(
            version_id=version_id_val,
            agent_key=agent_key,
            system_prompt=prompt,
            created_at=created_at,
            success_rate=successful / total if total > 0 else 0.0,
            total_jobs=total,
            successful_jobs=successful,
            parent_version=parent,
            is_active=bool(is_active),
        )

    def maybe_auto_promote(
        self,
        version_id: str,
        min_jobs: int = 10,
        improvement_threshold: float = 0.05,
    ) -> bool:
        """Auto-promote a version if it meets performance criteria.

        Promotes if:
        1. version has >= min_jobs outcomes
        2. success_rate > parent's success_rate by >= improvement_threshold

        Returns True if promoted, False otherwise.
        """
        version = self.get_version(version_id)
        if not version or version.total_jobs < min_jobs:
            return False

        if not version.parent_version:
            # No parent to compare against — don't auto-promote
            return False

        parent = self.get_version(version.parent_version)
        if not parent:
            return False

        improvement = version.success_rate - parent.success_rate
        if improvement >= improvement_threshold:
            logger.info(
                f"Auto-promoting version {version_id} for {version.agent_key}: "
                f"success_rate {version.success_rate:.2%} vs parent {parent.success_rate:.2%} "
                f"(+{improvement:.2%})"
            )
            return self.promote_version(version_id)

        return False

    def maybe_auto_rollback(
        self,
        agent_key: str,
        min_jobs_before_rollback: int = 5,
        degradation_threshold: float = 0.15,
    ) -> bool:
        """Auto-rollback if active version degrades significantly.

        Rolls back if:
        1. active version has >= min_jobs_before_rollback outcomes
        2. success_rate < parent's success_rate by >= degradation_threshold

        Returns True if rolled back, False otherwise.
        """
        active = self.get_active_version(agent_key)
        if not active or active.total_jobs < min_jobs_before_rollback:
            return False

        if not active.parent_version:
            return False

        parent = self.get_version(active.parent_version)
        if not parent:
            return False

        degradation = parent.success_rate - active.success_rate
        if degradation >= degradation_threshold:
            logger.warning(
                f"Auto-rolling back agent {agent_key}: "
                f"active version {active.success_rate:.2%} vs parent {parent.success_rate:.2%} "
                f"(-{degradation:.2%})"
            )
            self.rollback(agent_key)
            return True

        return False

    def get_stats(self, agent_key: str) -> Dict[str, Any]:
        """Get summary statistics for an agent's prompt versions.

        Returns:
            {
                "agent_key": str,
                "active_version_id": str | None,
                "active_success_rate": float,
                "total_versions": int,
                "total_outcomes": int,
                "timeline": [{"version_id": str, "created_at": str, "success_rate": float, ...}]
            }
        """
        versions = self.get_history(agent_key)
        active = self.get_active_version(agent_key)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM version_outcomes WHERE version_id IN "
            "(SELECT version_id FROM prompt_versions WHERE agent_key = ?)",
            (agent_key,),
        )
        total_outcomes = cursor.fetchone()[0]
        conn.close()

        return {
            "agent_key": agent_key,
            "active_version_id": active.version_id if active else None,
            "active_success_rate": active.success_rate if active else 0.0,
            "total_versions": len(versions),
            "total_outcomes": total_outcomes,
            "timeline": [v.to_dict() for v in versions],
        }


# Singleton instance
_store: Optional[PromptVersionStore] = None


def get_store() -> PromptVersionStore:
    """Get the global PromptVersionStore instance."""
    global _store
    if _store is None:
        _store = PromptVersionStore()
    return _store
