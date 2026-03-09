"""
Agent Sessions — Persistent per-agent memory that carries across jobs.
======================================================================
Unlike ide_session.py (per-job), this gives each agent TYPE a persistent
knowledge base that accumulates across all jobs it handles. Like Claude Code's
conversation persistence, but using our cheap models.

Each agent (codegen_pro, pentest_ai, etc.) has:
- Working memory: recent task summaries, patterns learned, codebase knowledge
- Skill memory: techniques that worked/failed, tool preferences, error patterns
- Project memory: per-project context (file structures, conventions, gotchas)

Storage: data/agent_sessions/{agent_key}.json

Pattern: Claude Code's auto-memory + Devin's knowledge base + Cursor's codebase awareness
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("agent_sessions")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "os.environ.get("OPENCLAW_DATA_DIR", "./data")")
AGENT_SESSIONS_DIR = os.path.join(DATA_DIR, "agent_sessions")

# Limits
MAX_WORKING_MEMORY = 50      # recent task summaries
MAX_SKILL_ENTRIES = 100       # techniques learned
MAX_PROJECT_ENTRIES = 30      # per-project context items
MAX_CONTEXT_TOKENS = 2000     # injected into prompts (~8000 chars)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class SkillEntry:
    """A technique the agent learned from experience."""
    skill: str            # "Use git diff --stat before full diff for large repos"
    category: str         # "git", "debugging", "testing", "api", "security"
    success_count: int    # How many times this worked
    fail_count: int       # How many times this failed
    last_used: str        # ISO timestamp
    source_job: str       # Job ID where this was learned

    def effectiveness(self) -> float:
        total = self.success_count + self.fail_count
        if total == 0:
            return 0.5
        return self.success_count / total


@dataclass
class TaskSummary:
    """Summary of a completed task for working memory."""
    job_id: str
    task: str             # Original task description (truncated)
    outcome: str          # "success", "partial", "failed"
    key_actions: list     # What the agent actually did
    duration_seconds: float
    cost_usd: float
    timestamp: str        # ISO timestamp
    project: str


@dataclass
class ProjectContext:
    """Per-project knowledge the agent has accumulated."""
    project: str
    file_patterns: list       # Common file paths/patterns for this project
    conventions: list         # Coding conventions observed
    known_issues: list        # Issues encountered before
    last_worked: str          # ISO timestamp
    task_count: int           # How many tasks on this project


@dataclass
class AgentSession:
    """Persistent session for one agent type."""
    agent_key: str                                          # "codegen_pro", "pentest_ai", etc.
    created_at: str = ""                                    # ISO timestamp
    last_active: str = ""                                   # ISO timestamp
    total_jobs: int = 0
    total_successes: int = 0
    total_failures: int = 0
    total_cost_usd: float = 0.0
    working_memory: list = field(default_factory=list)      # list[TaskSummary as dict]
    skills: list = field(default_factory=list)               # list[SkillEntry as dict]
    project_contexts: dict = field(default_factory=dict)    # project -> ProjectContext as dict
    personality_notes: list = field(default_factory=list)    # Self-observations

    def success_rate(self) -> float:
        if self.total_jobs == 0:
            return 0.0
        return self.total_successes / self.total_jobs

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def get_session(agent_key: str) -> AgentSession:
    """Load or create a persistent session for an agent."""
    filepath = os.path.join(AGENT_SESSIONS_DIR, f"{agent_key}.json")

    if os.path.exists(filepath):
        try:
            with open(filepath) as f:
                data = json.load(f)
            session = AgentSession(
                agent_key=data.get("agent_key", agent_key),
                created_at=data.get("created_at", ""),
                last_active=data.get("last_active", ""),
                total_jobs=data.get("total_jobs", 0),
                total_successes=data.get("total_successes", 0),
                total_failures=data.get("total_failures", 0),
                total_cost_usd=data.get("total_cost_usd", 0.0),
                working_memory=data.get("working_memory", []),
                skills=data.get("skills", []),
                project_contexts=data.get("project_contexts", {}),
                personality_notes=data.get("personality_notes", []),
            )
            return session
        except Exception as e:
            logger.warning(f"Failed to load agent session {agent_key}: {e}")

    # Create new session
    now = datetime.now(timezone.utc).isoformat()
    session = AgentSession(
        agent_key=agent_key,
        created_at=now,
        last_active=now,
    )
    save_session(session)
    return session


def save_session(session: AgentSession):
    """Persist agent session to disk."""
    os.makedirs(AGENT_SESSIONS_DIR, exist_ok=True)
    filepath = os.path.join(AGENT_SESSIONS_DIR, f"{session.agent_key}.json")
    session.last_active = datetime.now(timezone.utc).isoformat()

    with open(filepath, "w") as f:
        json.dump(session.to_dict(), f, indent=2)


# ---------------------------------------------------------------------------
# Recording job outcomes
# ---------------------------------------------------------------------------

def record_job(session: AgentSession, job_result: dict, job_metadata: dict):
    """Record a completed job into the agent's persistent memory.

    Called after every job completes. Updates working memory, stats, and
    project context.
    """
    job_id = job_metadata.get("job_id", "unknown")
    task = job_metadata.get("task", "")[:200]
    project = job_metadata.get("project", "unknown")
    success = job_result.get("success", False)
    cost = job_result.get("cost_usd", 0.0)
    duration = job_result.get("duration_seconds", 0.0)
    now = datetime.now(timezone.utc).isoformat()

    # Update stats
    session.total_jobs += 1
    session.total_cost_usd += cost
    if success:
        session.total_successes += 1
    else:
        session.total_failures += 1

    # Extract key actions from result
    key_actions = _extract_key_actions(job_result)

    # Add to working memory
    summary = {
        "job_id": job_id,
        "task": task,
        "outcome": "success" if success else "failed",
        "key_actions": key_actions[:5],
        "duration_seconds": round(duration, 1),
        "cost_usd": round(cost, 6),
        "timestamp": now,
        "project": project,
    }
    session.working_memory.append(summary)

    # Trim working memory to limit
    if len(session.working_memory) > MAX_WORKING_MEMORY:
        session.working_memory = session.working_memory[-MAX_WORKING_MEMORY:]

    # Update project context
    _update_project_context(session, project, job_result, job_metadata)

    # Extract skills from successful jobs
    if success:
        _extract_skills(session, job_result, job_metadata)

    save_session(session)


def _extract_key_actions(job_result: dict) -> list[str]:
    """Pull key actions from job result phases."""
    actions = []
    text = job_result.get("text", "")

    # Look for action markers in output
    for line in text.split("\n"):
        stripped = line.strip()
        if any(stripped.startswith(prefix) for prefix in
               ["Created ", "Modified ", "Fixed ", "Added ", "Removed ",
                "Updated ", "Deployed ", "Tested ", "Refactored "]):
            actions.append(stripped[:100])

    # Fallback: use phase info
    if not actions:
        phases = job_result.get("phases", {})
        for phase_name, phase_data in phases.items():
            if isinstance(phase_data, dict):
                steps = phase_data.get("steps_done", 0)
                if steps > 0:
                    actions.append(f"{phase_name}: {steps} steps completed")

    return actions[:5]


def _update_project_context(session: AgentSession, project: str,
                            job_result: dict, job_metadata: dict):
    """Update per-project knowledge from job results."""
    now = datetime.now(timezone.utc).isoformat()

    ctx = session.project_contexts.get(project, {
        "project": project,
        "file_patterns": [],
        "conventions": [],
        "known_issues": [],
        "last_worked": now,
        "task_count": 0,
    })

    ctx["last_worked"] = now
    ctx["task_count"] = ctx.get("task_count", 0) + 1

    # Extract file patterns from result
    text = job_result.get("text", "")
    for line in text.split("\n"):
        stripped = line.strip()
        # Look for file paths mentioned
        if "/" in stripped and any(stripped.endswith(ext) for ext in
                                   [".py", ".ts", ".js", ".tsx", ".jsx", ".json", ".yaml", ".yml"]):
            # Extract just the path-like part
            parts = stripped.split()
            for part in parts:
                if "/" in part and any(part.endswith(ext) for ext in
                                       [".py", ".ts", ".js", ".tsx", ".jsx"]):
                    path = part.strip("'\"`,;:()")
                    if path not in ctx["file_patterns"]:
                        ctx["file_patterns"].append(path)

    # Cap file patterns
    ctx["file_patterns"] = ctx["file_patterns"][-MAX_PROJECT_ENTRIES:]

    # Record issues from failed jobs
    if not job_result.get("success", False):
        error = job_result.get("error", "")[:200]
        if error and error not in ctx["known_issues"]:
            ctx["known_issues"].append(error)
            ctx["known_issues"] = ctx["known_issues"][-10:]

    session.project_contexts[project] = ctx


def _extract_skills(session: AgentSession, job_result: dict, job_metadata: dict):
    """Extract reusable skills from successful jobs."""
    text = job_result.get("text", "")
    task = job_metadata.get("task", "")
    job_id = job_metadata.get("job_id", "")
    now = datetime.now(timezone.utc).isoformat()

    # Look for DISCOVERY/LEARNING markers
    new_skills = []
    for line in text.split("\n"):
        stripped = line.strip()
        for prefix in ["DISCOVERY:", "LEARNING:", "TIP:", "PATTERN:"]:
            if stripped.upper().startswith(prefix):
                skill_text = stripped[len(prefix):].strip()
                if skill_text and len(skill_text) > 10:
                    new_skills.append(skill_text)

    # Categorize and add skills
    for skill_text in new_skills:
        category = _categorize_skill(skill_text)

        # Check for existing similar skill
        existing = None
        for s in session.skills:
            if _skills_similar(s.get("skill", ""), skill_text):
                existing = s
                break

        if existing:
            existing["success_count"] = existing.get("success_count", 0) + 1
            existing["last_used"] = now
        else:
            entry = {
                "skill": skill_text[:200],
                "category": category,
                "success_count": 1,
                "fail_count": 0,
                "last_used": now,
                "source_job": job_id,
            }
            session.skills.append(entry)

    # Cap skills
    if len(session.skills) > MAX_SKILL_ENTRIES:
        # Keep skills with highest effectiveness
        session.skills.sort(
            key=lambda s: s.get("success_count", 0) / max(1, s.get("success_count", 0) + s.get("fail_count", 0)),
            reverse=True
        )
        session.skills = session.skills[:MAX_SKILL_ENTRIES]


def _categorize_skill(skill_text: str) -> str:
    """Simple keyword-based skill categorization."""
    text = skill_text.lower()
    categories = {
        "git": ["git", "commit", "branch", "merge", "rebase", "push", "pull"],
        "debugging": ["debug", "error", "traceback", "exception", "stack", "breakpoint"],
        "testing": ["test", "assert", "mock", "fixture", "coverage", "pytest"],
        "api": ["api", "endpoint", "request", "response", "http", "rest", "graphql"],
        "security": ["auth", "token", "rls", "permission", "vulnerability", "xss", "injection"],
        "database": ["sql", "query", "table", "migration", "schema", "supabase"],
        "deployment": ["deploy", "vercel", "docker", "ci", "cd", "build"],
        "performance": ["cache", "optimize", "slow", "memory", "profile", "latency"],
    }
    for cat, keywords in categories.items():
        if any(kw in text for kw in keywords):
            return cat
    return "general"


def _skills_similar(skill_a: str, skill_b: str) -> bool:
    """Check if two skills are similar enough to merge."""
    a = set(skill_a.lower().split())
    b = set(skill_b.lower().split())
    if not a or not b:
        return False
    overlap = len(a & b) / max(len(a), len(b))
    return overlap > 0.6


# ---------------------------------------------------------------------------
# Context injection for prompts
# ---------------------------------------------------------------------------

def build_agent_context(agent_key: str, task: str, project: str) -> str:
    """Build context block from agent's persistent memory for injection into prompts.

    Returns a concise text block (~MAX_CONTEXT_TOKENS tokens) with:
    1. Agent's track record on this project
    2. Relevant skills from past jobs
    3. Known issues for this project
    4. Recent similar tasks
    """
    session = get_session(agent_key)
    parts = []

    # 1. Agent identity + stats
    parts.append(
        f"## Agent Context ({agent_key})\n"
        f"Jobs completed: {session.total_jobs} "
        f"(success rate: {session.success_rate():.0%})"
    )

    # 2. Project-specific context
    proj_ctx = session.project_contexts.get(project)
    if proj_ctx:
        proj_lines = [f"\n### Project: {project} ({proj_ctx.get('task_count', 0)} past tasks)"]
        known_issues = proj_ctx.get("known_issues", [])
        if known_issues:
            proj_lines.append("Known issues:")
            for issue in known_issues[-3:]:
                proj_lines.append(f"  - {issue[:100]}")
        conventions = proj_ctx.get("conventions", [])
        if conventions:
            proj_lines.append("Conventions:")
            for conv in conventions[-3:]:
                proj_lines.append(f"  - {conv[:100]}")
        parts.append("\n".join(proj_lines))

    # 3. Relevant skills
    relevant_skills = _find_relevant_skills(session.skills, task)
    if relevant_skills:
        skill_lines = ["\n### Relevant skills from past experience"]
        for s in relevant_skills[:5]:
            effectiveness = s.get("success_count", 0) / max(1, s.get("success_count", 0) + s.get("fail_count", 0))
            skill_lines.append(f"  - [{s.get('category', 'general')}] {s['skill'][:120]} (works {effectiveness:.0%})")
        parts.append("\n".join(skill_lines))

    # 4. Recent similar tasks on this project
    similar = _find_similar_tasks(session.working_memory, task, project)
    if similar:
        task_lines = ["\n### Recent similar tasks"]
        for t in similar[:3]:
            task_lines.append(
                f"  - [{t['outcome']}] {t['task'][:80]} "
                f"(${t.get('cost_usd', 0):.4f}, {t.get('duration_seconds', 0):.0f}s)"
            )
            for action in t.get("key_actions", [])[:2]:
                task_lines.append(f"    → {action[:80]}")
        parts.append("\n".join(task_lines))

    context = "\n".join(parts)

    # Token cap (~4 chars per token)
    max_chars = MAX_CONTEXT_TOKENS * 4
    if len(context) > max_chars:
        context = context[:max_chars] + "\n[...context truncated]"

    return context


def _find_relevant_skills(skills: list, task: str) -> list:
    """Find skills relevant to the current task."""
    if not skills:
        return []

    task_words = set(task.lower().split())
    scored = []
    for s in skills:
        skill_words = set(s.get("skill", "").lower().split())
        category = s.get("category", "")

        # Word overlap score
        overlap = len(task_words & skill_words) / max(len(task_words), 1)

        # Category relevance bonus
        if category in task.lower():
            overlap += 0.3

        # Effectiveness weight
        effectiveness = s.get("success_count", 0) / max(1, s.get("success_count", 0) + s.get("fail_count", 0))
        score = overlap * 0.6 + effectiveness * 0.4

        if score > 0.1:
            scored.append((score, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:5]]


def _find_similar_tasks(working_memory: list, task: str, project: str) -> list:
    """Find past tasks similar to the current one."""
    if not working_memory:
        return []

    task_words = set(task.lower().split())
    scored = []
    for entry in working_memory:
        entry_words = set(entry.get("task", "").lower().split())
        overlap = len(task_words & entry_words) / max(len(task_words), 1)

        # Boost same-project tasks
        if entry.get("project") == project:
            overlap += 0.2

        if overlap > 0.15:
            scored.append((overlap, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [entry for _, entry in scored[:3]]


# ---------------------------------------------------------------------------
# Record failure for skill tracking
# ---------------------------------------------------------------------------

def record_skill_failure(agent_key: str, skill_text: str):
    """Record that a technique failed, to update effectiveness scores."""
    session = get_session(agent_key)
    for s in session.skills:
        if _skills_similar(s.get("skill", ""), skill_text):
            s["fail_count"] = s.get("fail_count", 0) + 1
            s["last_used"] = datetime.now(timezone.utc).isoformat()
            save_session(session)
            return
    # Skill not found — record as new failed skill
    session.skills.append({
        "skill": skill_text[:200],
        "category": _categorize_skill(skill_text),
        "success_count": 0,
        "fail_count": 1,
        "last_used": datetime.now(timezone.utc).isoformat(),
        "source_job": "",
    })
    save_session(session)


# ---------------------------------------------------------------------------
# Agent self-reflection
# ---------------------------------------------------------------------------

def add_personality_note(agent_key: str, note: str):
    """Let an agent record a self-observation about its behavior."""
    session = get_session(agent_key)
    timestamped = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d')}] {note}"
    if timestamped not in session.personality_notes:
        session.personality_notes.append(timestamped)
        # Keep last 20 notes
        session.personality_notes = session.personality_notes[-20:]
        save_session(session)


# ---------------------------------------------------------------------------
# Multi-agent coordination
# ---------------------------------------------------------------------------

def get_all_agent_stats() -> list[dict]:
    """Get summary stats for all agents with sessions."""
    stats = []
    if not os.path.isdir(AGENT_SESSIONS_DIR):
        return stats

    for fname in sorted(os.listdir(AGENT_SESSIONS_DIR)):
        if fname.endswith(".json"):
            agent_key = fname[:-5]
            session = get_session(agent_key)
            stats.append({
                "agent_key": agent_key,
                "total_jobs": session.total_jobs,
                "success_rate": f"{session.success_rate():.0%}",
                "total_cost": f"${session.total_cost_usd:.4f}",
                "last_active": session.last_active,
                "skills_count": len(session.skills),
                "projects": list(session.project_contexts.keys()),
            })
    return stats


def get_best_agent_for_task(task: str, project: str, candidates: list[str]) -> str:
    """Pick the best agent from candidates based on past performance.

    Considers:
    - Success rate on similar tasks
    - Project experience
    - Skill relevance
    """
    if not candidates:
        return "codegen_pro"

    scored = []
    for agent_key in candidates:
        session = get_session(agent_key)
        score = 0.0

        # Base success rate
        score += session.success_rate() * 0.3

        # Project experience
        proj_ctx = session.project_contexts.get(project)
        if proj_ctx:
            score += min(proj_ctx.get("task_count", 0) / 20, 1.0) * 0.3

        # Relevant skills
        relevant = _find_relevant_skills(session.skills, task)
        if relevant:
            score += min(len(relevant) / 5, 1.0) * 0.2

        # Similar task history
        similar = _find_similar_tasks(session.working_memory, task, project)
        successful_similar = [t for t in similar if t.get("outcome") == "success"]
        if successful_similar:
            score += min(len(successful_similar) / 3, 1.0) * 0.2

        scored.append((score, agent_key))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]
