"""
Stuck Detection for OpenClaw autonomous runner.

Detects three stuck patterns:
- Looper: Same tool+args called N times
- Wanderer: No phase/step progress for M minutes
- Repeater: Same LLM response text pattern repeated K times

On first detection: injects corrective prompt.
After max_corrections: raises StuckError (job fails, no retry).
"""

import hashlib
import json
import time
import logging
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

logger = logging.getLogger("openclaw.stuck_detector")


class StuckPattern(str, Enum):
    LOOPER = "looper"
    WANDERER = "wanderer"
    REPEATER = "repeater"


@dataclass
class StuckState:
    job_id: str
    action_hashes: list = field(default_factory=list)
    response_hashes: list = field(default_factory=list)
    last_progress_time: float = field(default_factory=time.time)
    last_phase: str = ""
    last_step_index: int = 0
    corrective_injections: int = 0
    max_corrections: int = 2


@dataclass
class StuckResult:
    is_stuck: bool
    pattern: Optional[StuckPattern] = None
    message: str = ""
    should_fail: bool = False
    corrective_prompt: str = ""
    correction_count: int = 0


class StuckError(Exception):
    """Raised when a job is irrecoverably stuck."""
    def __init__(self, pattern: StuckPattern, message: str):
        self.pattern = pattern
        super().__init__(f"Job stuck ({pattern.value}): {message}")


class StuckDetector:
    def __init__(
        self,
        loop_threshold: int = 3,
        wander_timeout_minutes: float = 10.0,
        repeat_threshold: int = 3,
        max_history: int = 20,
        max_corrections: int = 2,
    ):
        self.loop_threshold = loop_threshold
        self.wander_timeout_sec = wander_timeout_minutes * 60
        self.repeat_threshold = repeat_threshold
        self.max_history = max_history
        self.max_corrections = max_corrections
        self._states: dict[str, StuckState] = {}

    def _get_state(self, job_id: str) -> StuckState:
        if job_id not in self._states:
            self._states[job_id] = StuckState(
                job_id=job_id,
                max_corrections=self.max_corrections,
            )
        return self._states[job_id]

    def _hash(self, data: str) -> str:
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def record_action(self, job_id: str, tool_name: str, tool_args: dict) -> StuckResult:
        state = self._get_state(job_id)
        action_sig = f"{tool_name}:{json.dumps(tool_args, sort_keys=True, default=str)}"
        action_hash = self._hash(action_sig)

        state.action_hashes.append(action_hash)
        if len(state.action_hashes) > self.max_history:
            state.action_hashes = state.action_hashes[-self.max_history:]

        recent = state.action_hashes[-self.loop_threshold:]
        if len(recent) == self.loop_threshold and len(set(recent)) == 1:
            return self._handle_stuck(state, StuckPattern.LOOPER,
                f"Tool '{tool_name}' called {self.loop_threshold}x with identical args")

        return StuckResult(is_stuck=False)

    def record_response(self, job_id: str, response_text: str) -> StuckResult:
        state = self._get_state(job_id)
        resp_hash = self._hash(response_text[:500] if response_text else "")

        state.response_hashes.append(resp_hash)
        if len(state.response_hashes) > self.max_history:
            state.response_hashes = state.response_hashes[-self.max_history:]

        recent = state.response_hashes[-self.repeat_threshold:]
        if len(recent) == self.repeat_threshold and len(set(recent)) == 1:
            return self._handle_stuck(state, StuckPattern.REPEATER,
                "LLM producing identical responses")

        return StuckResult(is_stuck=False)

    def record_progress(self, job_id: str, phase: str, step_index: int):
        state = self._get_state(job_id)
        if phase != state.last_phase or step_index != state.last_step_index:
            state.last_progress_time = time.time()
            state.last_phase = phase
            state.last_step_index = step_index

    def check_wanderer(self, job_id: str) -> StuckResult:
        state = self._get_state(job_id)
        elapsed = time.time() - state.last_progress_time
        if elapsed > self.wander_timeout_sec:
            return self._handle_stuck(state, StuckPattern.WANDERER,
                f"No progress for {elapsed/60:.1f} minutes")
        return StuckResult(is_stuck=False)

    def _handle_stuck(self, state: StuckState, pattern: StuckPattern, message: str) -> StuckResult:
        state.corrective_injections += 1
        logger.warning(f"[{state.job_id}] {message} (correction #{state.corrective_injections})")

        should_fail = state.corrective_injections > state.max_corrections

        corrective_prompt = (
            "SYSTEM NOTICE: You appear to be stuck. "
            f"Pattern: {pattern.value}. {message}. "
            "Reassess your approach and try a fundamentally different strategy. "
            "Do NOT repeat the same action. If you cannot make progress, "
            "state what's blocking you and stop."
        )

        return StuckResult(
            is_stuck=True,
            pattern=pattern,
            message=message,
            should_fail=should_fail,
            corrective_prompt=corrective_prompt,
            correction_count=state.corrective_injections,
        )

    def clear(self, job_id: str):
        self._states.pop(job_id, None)

    def get_status(self, job_id: str) -> dict:
        state = self._get_state(job_id)
        elapsed = time.time() - state.last_progress_time
        return {
            "job_id": job_id,
            "corrections": state.corrective_injections,
            "max_corrections": state.max_corrections,
            "seconds_since_progress": round(elapsed, 1),
            "wander_timeout_sec": self.wander_timeout_sec,
            "action_history": len(state.action_hashes),
            "response_history": len(state.response_hashes),
            "last_phase": state.last_phase,
            "last_step_index": state.last_step_index,
        }

    def get_all_statuses(self) -> list[dict]:
        return [self.get_status(jid) for jid in self._states]


# Module singleton
_detector: Optional[StuckDetector] = None

def init_stuck_detector(**kwargs) -> StuckDetector:
    global _detector
    _detector = StuckDetector(**kwargs)
    return _detector

def get_stuck_detector() -> Optional[StuckDetector]:
    return _detector
