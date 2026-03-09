"""
OpenClaw Knowledge Graph Engine
=================================
Tracks which tools work best together, which agents perform best on which tasks,
and learns optimal tool chains from job execution history.

Usage:
    kg = get_kg_engine()
    kg.record_execution(job_id="abc", agent="coder_agent", tools=["file_read", "file_edit"], success=True)
    recommendations = kg.recommend_tools(agent="coder_agent", task_type="bug_fix")
    # [{"tool_chain": ["file_read", "grep_search", "file_edit"], "success_rate": 0.92}]

Architecture:
    - SQLite-backed persistent storage
    - Three tables: tool_nodes, tool_edges, job_executions
    - Edge weights represent co-occurrence success rates
    - Query engine for tool chain recommendations
    - Auto-learns from EventEngine job completions
"""

import json
import logging
import os
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger("openclaw.kg")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "os.environ.get("OPENCLAW_DATA_DIR", "./data")")
KG_DB_PATH = os.path.join(DATA_DIR, "kg", "knowledge_graph.db")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass
class ToolChainRecommendation:
    """A recommended sequence of tools for a task type."""
    tools: List[str]
    success_rate: float
    usage_count: int
    avg_duration_ms: float = 0.0
    agent_key: str = ""

    def to_dict(self) -> dict:
        return {
            "tools": self.tools,
            "success_rate": round(self.success_rate, 3),
            "usage_count": self.usage_count,
            "avg_duration_ms": round(self.avg_duration_ms, 1),
            "agent_key": self.agent_key,
        }


@dataclass
class AgentPerformance:
    """Performance stats for an agent on a task type."""
    agent_key: str
    task_type: str
    total_jobs: int
    success_rate: float
    avg_cost_usd: float
    avg_duration_ms: float
    favorite_tools: List[str]

    def to_dict(self) -> dict:
        return {
            "agent_key": self.agent_key,
            "task_type": self.task_type,
            "total_jobs": self.total_jobs,
            "success_rate": round(self.success_rate, 3),
            "avg_cost_usd": round(self.avg_cost_usd, 5),
            "avg_duration_ms": round(self.avg_duration_ms, 1),
            "favorite_tools": self.favorite_tools[:10],
        }


# ---------------------------------------------------------------------------
# Knowledge Graph Engine
# ---------------------------------------------------------------------------

class KGEngine:
    """SQLite-backed knowledge graph for tool and agent performance tracking."""

    def __init__(self, db_path: str = KG_DB_PATH):
        self._db_path = db_path
        self._lock = threading.Lock()

        # Ensure directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_db()
        logger.info(f"KGEngine initialized (db: {db_path})")

    def _init_db(self):
        """Create tables if they don't exist."""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tool_nodes (
                    tool_name TEXT PRIMARY KEY,
                    total_uses INTEGER DEFAULT 0,
                    success_uses INTEGER DEFAULT 0,
                    avg_duration_ms REAL DEFAULT 0,
                    last_used TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tool_edges (
                    from_tool TEXT NOT NULL,
                    to_tool TEXT NOT NULL,
                    agent_key TEXT DEFAULT '',
                    co_occurrence INTEGER DEFAULT 0,
                    co_success INTEGER DEFAULT 0,
                    success_rate REAL DEFAULT 0,
                    last_updated TEXT,
                    PRIMARY KEY (from_tool, to_tool, agent_key)
                );

                CREATE TABLE IF NOT EXISTS job_executions (
                    job_id TEXT PRIMARY KEY,
                    agent_key TEXT NOT NULL,
                    task_type TEXT DEFAULT '',
                    tools_used TEXT DEFAULT '[]',
                    success INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0,
                    duration_ms REAL DEFAULT 0,
                    quality_score REAL DEFAULT 0,
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_job_agent ON job_executions(agent_key);
                CREATE INDEX IF NOT EXISTS idx_job_task ON job_executions(task_type);
                CREATE INDEX IF NOT EXISTS idx_edges_agent ON tool_edges(agent_key);
            """)

    def _get_conn(self) -> sqlite3.Connection:
        """Get a SQLite connection (thread-safe via check_same_thread=False)."""
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_execution(self, job_id: str, agent_key: str, tools_used: List[str],
                         success: bool, task_type: str = "", cost_usd: float = 0.0,
                         duration_ms: float = 0.0, quality_score: float = 0.0):
        """Record a job execution and update tool/edge statistics.

        This is the primary learning function — called after every job completes.
        """
        with self._lock:
            try:
                conn = self._get_conn()
                now = datetime.now(timezone.utc).isoformat()

                # Record job execution
                conn.execute("""
                    INSERT OR REPLACE INTO job_executions
                    (job_id, agent_key, task_type, tools_used, success, cost_usd, duration_ms, quality_score, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (job_id, agent_key, task_type, json.dumps(tools_used),
                      1 if success else 0, cost_usd, duration_ms, quality_score, now))

                # Update tool nodes
                for tool in tools_used:
                    conn.execute("""
                        INSERT INTO tool_nodes (tool_name, total_uses, success_uses, last_used)
                        VALUES (?, 1, ?, ?)
                        ON CONFLICT(tool_name) DO UPDATE SET
                            total_uses = total_uses + 1,
                            success_uses = success_uses + ?,
                            last_used = ?
                    """, (tool, 1 if success else 0, now, 1 if success else 0, now))

                # Update tool edges (co-occurrence within same job)
                unique_tools = list(dict.fromkeys(tools_used))  # Preserve order, remove dupes
                for i in range(len(unique_tools)):
                    for j in range(i + 1, len(unique_tools)):
                        t1, t2 = unique_tools[i], unique_tools[j]
                        # Ensure consistent ordering
                        if t1 > t2:
                            t1, t2 = t2, t1

                        conn.execute("""
                            INSERT INTO tool_edges (from_tool, to_tool, agent_key, co_occurrence, co_success, last_updated)
                            VALUES (?, ?, ?, 1, ?, ?)
                            ON CONFLICT(from_tool, to_tool, agent_key) DO UPDATE SET
                                co_occurrence = co_occurrence + 1,
                                co_success = co_success + ?,
                                success_rate = CAST((co_success + ?) AS REAL) / (co_occurrence + 1),
                                last_updated = ?
                        """, (t1, t2, agent_key, 1 if success else 0, now,
                              1 if success else 0, 1 if success else 0, now))

                conn.commit()
                conn.close()
                logger.debug(f"Recorded execution: job={job_id}, agent={agent_key}, tools={len(tools_used)}, success={success}")

            except Exception as e:
                logger.error(f"Failed to record execution: {e}")

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def recommend_tools(self, agent_key: str = "", task_type: str = "",
                        limit: int = 5) -> List[ToolChainRecommendation]:
        """Recommend tool chains based on historical success patterns.

        Returns the most successful tool combinations for the given agent/task type.
        """
        try:
            conn = self._get_conn()

            # Find successful job executions matching criteria
            query = "SELECT tools_used, success, duration_ms FROM job_executions WHERE success = 1"
            params = []

            if agent_key:
                query += " AND agent_key = ?"
                params.append(agent_key)
            if task_type:
                query += " AND task_type = ?"
                params.append(task_type)

            query += " ORDER BY timestamp DESC LIMIT 100"

            rows = conn.execute(query, params).fetchall()
            conn.close()

            if not rows:
                return []

            # Count tool chain frequencies
            chain_stats: Dict[str, Dict] = {}
            for row in rows:
                tools = json.loads(row["tools_used"])
                # Use sorted tuple as key for consistent hashing
                chain_key = ",".join(tools[:10])  # Cap at 10 tools
                if chain_key not in chain_stats:
                    chain_stats[chain_key] = {
                        "tools": tools[:10],
                        "count": 0,
                        "total_duration": 0.0,
                    }
                chain_stats[chain_key]["count"] += 1
                chain_stats[chain_key]["total_duration"] += row["duration_ms"] or 0

            # Sort by frequency and return top recommendations
            sorted_chains = sorted(chain_stats.values(), key=lambda x: x["count"], reverse=True)

            recommendations = []
            for chain in sorted_chains[:limit]:
                recommendations.append(ToolChainRecommendation(
                    tools=chain["tools"],
                    success_rate=1.0,  # All rows are success=1
                    usage_count=chain["count"],
                    avg_duration_ms=chain["total_duration"] / chain["count"] if chain["count"] > 0 else 0,
                    agent_key=agent_key,
                ))

            return recommendations

        except Exception as e:
            logger.error(f"Failed to get recommendations: {e}")
            return []

    def get_agent_performance(self, agent_key: str, task_type: str = "") -> Optional[AgentPerformance]:
        """Get performance statistics for an agent."""
        try:
            conn = self._get_conn()

            query = "SELECT * FROM job_executions WHERE agent_key = ?"
            params = [agent_key]
            if task_type:
                query += " AND task_type = ?"
                params.append(task_type)

            rows = conn.execute(query, params).fetchall()
            conn.close()

            if not rows:
                return None

            total = len(rows)
            successes = sum(1 for r in rows if r["success"])
            total_cost = sum(r["cost_usd"] for r in rows)
            total_duration = sum(r["duration_ms"] or 0 for r in rows)

            # Count tool frequency
            tool_counter: Counter = Counter()
            for row in rows:
                tools = json.loads(row["tools_used"])
                tool_counter.update(tools)

            return AgentPerformance(
                agent_key=agent_key,
                task_type=task_type or "all",
                total_jobs=total,
                success_rate=successes / total if total > 0 else 0,
                avg_cost_usd=total_cost / total if total > 0 else 0,
                avg_duration_ms=total_duration / total if total > 0 else 0,
                favorite_tools=[t for t, _ in tool_counter.most_common(10)],
            )

        except Exception as e:
            logger.error(f"Failed to get agent performance: {e}")
            return None

    def get_tool_stats(self, limit: int = 20) -> List[dict]:
        """Get tool usage statistics."""
        try:
            conn = self._get_conn()
            rows = conn.execute("""
                SELECT tool_name, total_uses, success_uses,
                       CAST(success_uses AS REAL) / NULLIF(total_uses, 0) as success_rate,
                       last_used
                FROM tool_nodes
                ORDER BY total_uses DESC
                LIMIT ?
            """, (limit,)).fetchall()
            conn.close()

            return [dict(r) for r in rows]

        except Exception as e:
            logger.error(f"Failed to get tool stats: {e}")
            return []

    def get_tool_pairs(self, agent_key: str = "", min_count: int = 2,
                       limit: int = 20) -> List[dict]:
        """Get the most successful tool pairs."""
        try:
            conn = self._get_conn()
            query = """
                SELECT from_tool, to_tool, agent_key, co_occurrence, co_success, success_rate
                FROM tool_edges
                WHERE co_occurrence >= ?
            """
            params: list = [min_count]

            if agent_key:
                query += " AND agent_key = ?"
                params.append(agent_key)

            query += " ORDER BY success_rate DESC, co_occurrence DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            conn.close()

            return [dict(r) for r in rows]

        except Exception as e:
            logger.error(f"Failed to get tool pairs: {e}")
            return []

    def get_graph_summary(self) -> dict:
        """Get a summary of the knowledge graph."""
        try:
            conn = self._get_conn()

            node_count = conn.execute("SELECT COUNT(*) FROM tool_nodes").fetchone()[0]
            edge_count = conn.execute("SELECT COUNT(*) FROM tool_edges").fetchone()[0]
            job_count = conn.execute("SELECT COUNT(*) FROM job_executions").fetchone()[0]
            success_count = conn.execute("SELECT COUNT(*) FROM job_executions WHERE success = 1").fetchone()[0]

            # Agent breakdown
            agent_stats = conn.execute("""
                SELECT agent_key, COUNT(*) as jobs, SUM(success) as successes
                FROM job_executions GROUP BY agent_key
            """).fetchall()

            conn.close()

            return {
                "total_tools": node_count,
                "total_edges": edge_count,
                "total_jobs": job_count,
                "overall_success_rate": round(success_count / job_count, 3) if job_count > 0 else 0,
                "agents": [
                    {
                        "agent": r["agent_key"],
                        "jobs": r["jobs"],
                        "success_rate": round(r["successes"] / r["jobs"], 3) if r["jobs"] > 0 else 0,
                    }
                    for r in agent_stats
                ],
            }

        except Exception as e:
            logger.error(f"Failed to get graph summary: {e}")
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # EventEngine Integration
    # ------------------------------------------------------------------

    def register_with_event_engine(self, event_engine):
        """Subscribe to job events to auto-record executions."""

        def _on_job_completed(record):
            data = record.get("data", {})
            job_id = data.get("job_id", data.get("id", ""))
            if not job_id:
                return

            self.record_execution(
                job_id=job_id,
                agent_key=data.get("agent", data.get("agent_key", "unknown")),
                tools_used=data.get("tools_used", []),
                success=True,
                task_type=data.get("task_type", ""),
                cost_usd=data.get("total_cost_usd", data.get("cost_usd", 0.0)),
                duration_ms=data.get("duration_ms", 0.0),
                quality_score=data.get("quality_score", 0.0),
            )

        def _on_job_failed(record):
            data = record.get("data", {})
            job_id = data.get("job_id", data.get("id", ""))
            if not job_id:
                return

            self.record_execution(
                job_id=job_id,
                agent_key=data.get("agent", data.get("agent_key", "unknown")),
                tools_used=data.get("tools_used", []),
                success=False,
                task_type=data.get("task_type", ""),
                cost_usd=data.get("total_cost_usd", data.get("cost_usd", 0.0)),
                duration_ms=data.get("duration_ms", 0.0),
            )

        event_engine.subscribe("job.completed", _on_job_completed)
        event_engine.subscribe("job.failed", _on_job_failed)
        logger.info("KGEngine registered with EventEngine")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_kg_engine: Optional[KGEngine] = None


def get_kg_engine() -> KGEngine:
    """Get the global KGEngine instance."""
    global _kg_engine
    if _kg_engine is None:
        _kg_engine = KGEngine()
    return _kg_engine


def init_kg_engine(db_path: Optional[str] = None, event_engine=None) -> KGEngine:
    """Initialize and optionally wire to EventEngine."""
    global _kg_engine
    _kg_engine = KGEngine(db_path=db_path or KG_DB_PATH)
    if event_engine:
        _kg_engine.register_with_event_engine(event_engine)
    return _kg_engine
