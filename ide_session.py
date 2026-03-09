"""
IDE Session — Persistent context management for multi-phase job pipelines.
=========================================================================
Tracks what each agent "knows" during a job: files read, edits made, errors
encountered, conversation history, and estimated token counts. Enables:

1. Context persistence across phases (research findings feed into planning)
2. Token-aware compaction (prune low-relevance items before agent calls)
3. Conversation summaries for phase handoffs
4. Resume support via checkpoint integration

Storage: data/sessions/{job_id}/session.json

Pattern: LangGraph (typed state + checkpoints), Aider (repo-map for context)
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ide_session")

# Session storage directory
SESSIONS_DIR = os.path.join(
    os.environ.get("OPENCLAW_DATA_DIR", "os.environ.get("OPENCLAW_DATA_DIR", "./data")"),
    "sessions",
)


@dataclass
class ContextItem:
    """A single piece of context the agent has seen or produced."""
    type: str              # "file_read", "file_edit", "error", "research", "plan_step", "tool_result"
    content: str           # The actual content (file contents, error message, etc.)
    source: str            # Where this came from (file path, tool name, phase name)
    relevance: float       # 0.0-1.0 — how relevant this item is to the current task
    tokens_est: int        # Estimated token count (~4 chars per token)
    created_at: float      # Unix timestamp
    phase: str             # Which phase produced this item

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "content": self.content[:5000],  # Cap stored content
            "source": self.source,
            "relevance": self.relevance,
            "tokens_est": self.tokens_est,
            "created_at": self.created_at,
            "phase": self.phase,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ContextItem":
        return cls(
            type=d.get("type", "unknown"),
            content=d.get("content", ""),
            source=d.get("source", ""),
            relevance=d.get("relevance", 0.5),
            tokens_est=d.get("tokens_est", 0),
            created_at=d.get("created_at", time.time()),
            phase=d.get("phase", ""),
        )


@dataclass
class IDESession:
    """
    Session state for a job running through the pipeline.

    Tracks context items, conversation history, and token estimates
    for intelligent context management across phases.
    """
    job_id: str
    project: str
    workspace: str
    current_phase: str = ""
    context_items: list = field(default_factory=list)  # list[ContextItem]
    conversation_history: list = field(default_factory=list)  # list[dict] — role/content pairs
    phase_summaries: dict = field(default_factory=dict)  # phase_name -> summary string
    total_tokens_est: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def add_context(
        self,
        type: str,
        content: str,
        source: str = "",
        relevance: float = 0.5,
        phase: str = "",
    ) -> "ContextItem":
        """Add a context item to the session."""
        tokens_est = len(content) // 4  # ~4 chars per token
        item = ContextItem(
            type=type,
            content=content,
            source=source,
            relevance=relevance,
            tokens_est=tokens_est,
            created_at=time.time(),
            phase=phase or self.current_phase,
        )
        self.context_items.append(item)
        self.total_tokens_est += tokens_est
        self.updated_at = time.time()
        return item

    def add_message(self, role: str, content: str):
        """Add a conversation message to history."""
        self.conversation_history.append({
            "role": role,
            "content": content[:5000],  # Cap message size
            "timestamp": time.time(),
            "phase": self.current_phase,
        })
        self.updated_at = time.time()

    def set_phase(self, phase: str):
        """Transition to a new phase, saving summary of the previous one."""
        if self.current_phase and self.current_phase != phase:
            # Auto-generate summary for the phase we're leaving
            summary = self._summarize_phase(self.current_phase)
            self.phase_summaries[self.current_phase] = summary
            logger.debug(
                f"Session {self.job_id}: phase {self.current_phase} -> {phase}, "
                f"summary={len(summary)} chars"
            )
        self.current_phase = phase
        self.updated_at = time.time()

    def compact(self, target_tokens: int = 3000) -> int:
        """
        Prune low-relevance context items to fit within target token budget.

        Strategy:
        1. Keep all items from current phase (they're actively being used)
        2. Sort older items by relevance
        3. Remove lowest-relevance items until under target

        Returns: Number of items removed.
        """
        if self.total_tokens_est <= target_tokens:
            return 0

        # Partition: current phase items (keep) vs older items (candidates for removal)
        current_items = []
        older_items = []
        for item in self.context_items:
            if item.phase == self.current_phase:
                current_items.append(item)
            else:
                older_items.append(item)

        # Sort older items by relevance (ascending — lowest first for removal)
        older_items.sort(key=lambda x: x.relevance)

        # Remove lowest-relevance items until we're under target
        removed = 0
        tokens_to_remove = self.total_tokens_est - target_tokens
        tokens_removed = 0

        items_to_keep = []
        for item in older_items:
            if tokens_removed < tokens_to_remove:
                tokens_removed += item.tokens_est
                removed += 1
            else:
                items_to_keep.append(item)

        self.context_items = current_items + items_to_keep
        self.total_tokens_est = sum(i.tokens_est for i in self.context_items)
        self.updated_at = time.time()

        logger.info(
            f"Session {self.job_id}: compacted {removed} items, "
            f"tokens {self.total_tokens_est + tokens_removed} -> {self.total_tokens_est}"
        )
        return removed

    def get_context_summary(self, max_tokens: int = 2000) -> str:
        """
        Generate a condensed context briefing for the current agent.

        Includes:
        - Phase summaries from earlier phases
        - High-relevance context items
        - Recent conversation highlights
        """
        parts = []

        # Include summaries from previous phases
        for phase_name in ["research", "plan", "execute", "verify", "deliver"]:
            if phase_name in self.phase_summaries and phase_name != self.current_phase:
                parts.append(f"[{phase_name.upper()} SUMMARY]\n{self.phase_summaries[phase_name]}")

        # Include high-relevance context items from current phase
        current_items = [
            item for item in self.context_items
            if item.phase == self.current_phase and item.relevance >= 0.5
        ]
        current_items.sort(key=lambda x: x.relevance, reverse=True)

        for item in current_items[:10]:  # Top 10 most relevant
            parts.append(f"[{item.type.upper()}: {item.source}]\n{item.content[:500]}")

        # Combine and truncate to target
        combined = "\n\n".join(parts)
        max_chars = max_tokens * 4  # ~4 chars per token
        if len(combined) > max_chars:
            combined = combined[:max_chars] + "\n... (truncated)"

        return combined

    def get_phase_briefing(self, phase: str) -> str:
        """
        Generate a briefing for an agent about to start a specific phase.

        This is injected into the system prompt to give the new phase's agent
        context about what happened in previous phases.
        """
        parts = [f"You are continuing work on job {self.job_id} (project: {self.project})."]
        parts.append(f"Current phase: {phase}")

        # Add summaries from completed phases
        completed_summaries = []
        for prev_phase in ["research", "plan", "execute", "verify"]:
            if prev_phase == phase:
                break
            if prev_phase in self.phase_summaries:
                completed_summaries.append(
                    f"- {prev_phase.upper()}: {self.phase_summaries[prev_phase][:300]}"
                )

        if completed_summaries:
            parts.append("\nCompleted phases:")
            parts.extend(completed_summaries)

        # Add key context items (high relevance only)
        key_items = [
            item for item in self.context_items
            if item.relevance >= 0.7
        ]
        if key_items:
            key_items.sort(key=lambda x: x.created_at, reverse=True)
            parts.append(f"\nKey context ({len(key_items)} items):")
            for item in key_items[:5]:
                parts.append(f"- [{item.type}] {item.source}: {item.content[:200]}")

        return "\n".join(parts)

    def _summarize_phase(self, phase: str) -> str:
        """Generate a brief summary of what happened in a phase."""
        phase_items = [i for i in self.context_items if i.phase == phase]
        if not phase_items:
            return "(no activity recorded)"

        # Count by type
        type_counts = {}
        for item in phase_items:
            type_counts[item.type] = type_counts.get(item.type, 0) + 1

        parts = []
        for t, count in sorted(type_counts.items()):
            parts.append(f"{count} {t}(s)")

        # Include last conversation message from this phase
        phase_messages = [
            m for m in self.conversation_history
            if m.get("phase") == phase and m.get("role") == "assistant"
        ]
        if phase_messages:
            last_msg = phase_messages[-1]["content"][:300]
            parts.append(f"Last output: {last_msg}")

        return "; ".join(parts)

    def to_dict(self) -> dict:
        """Serialize session to dict for storage."""
        return {
            "job_id": self.job_id,
            "project": self.project,
            "workspace": self.workspace,
            "current_phase": self.current_phase,
            "context_items": [
                item.to_dict() if isinstance(item, ContextItem) else item
                for item in self.context_items
            ],
            "conversation_history": self.conversation_history[-20:],  # Keep last 20 messages
            "phase_summaries": self.phase_summaries,
            "total_tokens_est": self.total_tokens_est,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "IDESession":
        """Deserialize session from dict."""
        session = cls(
            job_id=d.get("job_id", ""),
            project=d.get("project", ""),
            workspace=d.get("workspace", ""),
            current_phase=d.get("current_phase", ""),
            total_tokens_est=d.get("total_tokens_est", 0),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
        )
        session.phase_summaries = d.get("phase_summaries", {})
        session.conversation_history = d.get("conversation_history", [])

        # Deserialize context items
        raw_items = d.get("context_items", [])
        for item_dict in raw_items:
            if isinstance(item_dict, dict):
                session.context_items.append(ContextItem.from_dict(item_dict))

        return session


# ---------------------------------------------------------------------------
# Session persistence — file-based storage
# ---------------------------------------------------------------------------

def _session_path(job_id: str) -> str:
    """Get the file path for a session."""
    return os.path.join(SESSIONS_DIR, job_id, "session.json")


def create_session(job_id: str, project: str, workspace: str) -> IDESession:
    """Create a new IDE session for a job."""
    session = IDESession(
        job_id=job_id,
        project=project,
        workspace=workspace,
    )
    save_session(session)
    logger.info(f"Session created: job={job_id} project={project}")
    return session


def save_session(session: IDESession):
    """Save session state to disk."""
    path = _session_path(session.job_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(session.to_dict(), f, indent=2, default=str)
    except Exception as e:
        logger.warning(f"Failed to save session {session.job_id}: {e}")


def load_session(job_id: str) -> Optional[IDESession]:
    """Load a session from disk."""
    path = _session_path(job_id)
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return IDESession.from_dict(data)
    except FileNotFoundError:
        return None
    except Exception as e:
        logger.warning(f"Failed to load session {job_id}: {e}")
        return None


def delete_session(job_id: str):
    """Delete a session and its directory."""
    session_dir = os.path.join(SESSIONS_DIR, job_id)
    try:
        import shutil
        shutil.rmtree(session_dir, ignore_errors=True)
        logger.debug(f"Session deleted: {job_id}")
    except Exception as e:
        logger.warning(f"Failed to delete session {job_id}: {e}")
