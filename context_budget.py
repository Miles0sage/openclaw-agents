"""
Context Budget Manager for OpenClaw.

Tracks token/message usage per job and enforces thresholds:
- 70%: Warning log
- 85%: Force compact (summarize oldest messages)
- 95%: Checkpoint + restart with compacted context

Prevents context overflow — the "OOM of agents."
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("openclaw.context_budget")


@dataclass
class BudgetState:
    job_id: str
    max_messages: int = 100
    max_tokens_estimate: int = 120_000
    current_messages: int = 0
    current_tokens_estimate: int = 0
    compactions: int = 0
    warnings_issued: int = 0
    last_check_time: float = field(default_factory=time.time)

    @property
    def message_pct(self) -> float:
        if self.max_messages <= 0:
            return 0.0
        return (self.current_messages / self.max_messages) * 100

    @property
    def token_pct(self) -> float:
        if self.max_tokens_estimate <= 0:
            return 0.0
        return (self.current_tokens_estimate / self.max_tokens_estimate) * 100

    @property
    def usage_pct(self) -> float:
        return max(self.message_pct, self.token_pct)


class ContextAction:
    NONE = "none"
    WARN = "warn"
    COMPACT = "compact"
    CHECKPOINT_RESTART = "checkpoint_restart"


@dataclass
class BudgetCheck:
    action: str = ContextAction.NONE
    usage_pct: float = 0.0
    message: str = ""
    should_compact: bool = False
    should_checkpoint_restart: bool = False


class ContextBudgetManager:
    """
    Manages context budgets per job.

    Usage:
        mgr = ContextBudgetManager()
        mgr.init_job("job-123", max_messages=100, max_tokens=120000)

        # After each message exchange:
        mgr.record_messages("job-123", count=2, tokens=1500)
        check = mgr.check("job-123")
        if check.should_compact:
            # Compact messages
            compacted = compact_messages(messages)
            mgr.record_compaction("job-123", old_count, new_count, old_tokens, new_tokens)
        elif check.should_checkpoint_restart:
            # Save checkpoint, build summary, restart
            ...
    """

    WARN_THRESHOLD = 70.0
    COMPACT_THRESHOLD = 85.0
    RESTART_THRESHOLD = 95.0

    def __init__(self, default_max_messages: int = 100,
                 default_max_tokens: int = 120_000):
        self.default_max_messages = default_max_messages
        self.default_max_tokens = default_max_tokens
        self._states: dict[str, BudgetState] = {}

    def init_job(self, job_id: str, max_messages: int = None,
                 max_tokens: int = None) -> BudgetState:
        state = BudgetState(
            job_id=job_id,
            max_messages=max_messages or self.default_max_messages,
            max_tokens_estimate=max_tokens or self.default_max_tokens,
        )
        self._states[job_id] = state
        return state

    def record_messages(self, job_id: str, count: int = 1, tokens: int = 0):
        state = self._get_state(job_id)
        state.current_messages += count
        state.current_tokens_estimate += tokens
        state.last_check_time = time.time()

    def record_compaction(self, job_id: str, old_msg_count: int, new_msg_count: int,
                          old_tokens: int = 0, new_tokens: int = 0):
        state = self._get_state(job_id)
        state.current_messages = new_msg_count
        if new_tokens > 0:
            state.current_tokens_estimate = new_tokens
        else:
            ratio = new_msg_count / max(old_msg_count, 1)
            state.current_tokens_estimate = int(state.current_tokens_estimate * ratio)
        state.compactions += 1
        logger.info(f"[{job_id}] Context compacted: {old_msg_count} -> {new_msg_count} messages "
                     f"(compaction #{state.compactions})")

    def check(self, job_id: str) -> BudgetCheck:
        state = self._get_state(job_id)
        pct = state.usage_pct

        if pct >= self.RESTART_THRESHOLD:
            logger.warning(f"[{job_id}] Context at {pct:.0f}% — checkpoint+restart needed")
            return BudgetCheck(
                action=ContextAction.CHECKPOINT_RESTART,
                usage_pct=pct,
                message=f"Context budget at {pct:.0f}% (>={self.RESTART_THRESHOLD}%). "
                        f"Checkpoint and restart with compacted context.",
                should_compact=False,
                should_checkpoint_restart=True,
            )

        if pct >= self.COMPACT_THRESHOLD:
            logger.warning(f"[{job_id}] Context at {pct:.0f}% — compaction needed")
            return BudgetCheck(
                action=ContextAction.COMPACT,
                usage_pct=pct,
                message=f"Context budget at {pct:.0f}% (>={self.COMPACT_THRESHOLD}%). "
                        f"Compacting messages.",
                should_compact=True,
                should_checkpoint_restart=False,
            )

        if pct >= self.WARN_THRESHOLD:
            state.warnings_issued += 1
            if state.warnings_issued <= 3:
                logger.info(f"[{job_id}] Context at {pct:.0f}% — approaching limit")
            return BudgetCheck(
                action=ContextAction.WARN,
                usage_pct=pct,
                message=f"Context budget at {pct:.0f}% (>={self.WARN_THRESHOLD}%).",
            )

        return BudgetCheck(action=ContextAction.NONE, usage_pct=pct)

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimate: ~4 chars per token."""
        return len(text) // 4

    def clear(self, job_id: str):
        self._states.pop(job_id, None)

    def get_status(self, job_id: str) -> dict:
        state = self._get_state(job_id)
        return {
            "job_id": job_id,
            "messages": state.current_messages,
            "max_messages": state.max_messages,
            "tokens_estimate": state.current_tokens_estimate,
            "max_tokens": state.max_tokens_estimate,
            "usage_pct": round(state.usage_pct, 1),
            "compactions": state.compactions,
            "warnings": state.warnings_issued,
        }

    def get_all_statuses(self) -> list[dict]:
        return [self.get_status(jid) for jid in self._states]

    def _get_state(self, job_id: str) -> BudgetState:
        if job_id not in self._states:
            self._states[job_id] = self.init_job(job_id)
        return self._states[job_id]


_manager: Optional[ContextBudgetManager] = None

def init_context_budget(**kwargs) -> ContextBudgetManager:
    global _manager
    _manager = ContextBudgetManager(**kwargs)
    return _manager

def get_context_budget() -> ContextBudgetManager:
    global _manager
    if _manager is None:
        _manager = ContextBudgetManager()
    return _manager
