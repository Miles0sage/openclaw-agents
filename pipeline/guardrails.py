"""
Job safety guardrails: cost caps, iteration limits, circuit breaker, kill flags.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("autonomous_runner")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")
KILL_FLAGS_PATH = Path(os.path.join(DATA_DIR, "jobs", "kill_flags.json"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class BudgetExceededError(Exception):
    """Raised when a job exceeds its cost budget."""
    pass


class CreditExhaustedError(Exception):
    """Raised when the API provider reports insufficient credits."""
    pass


class GuardrailViolation(Exception):
    """Raised when any guardrail limit is breached."""
    def __init__(self, job_id: str, reason: str, kill_status: str):
        self.job_id = job_id
        self.reason = reason
        self.kill_status = kill_status
        super().__init__(f"Job {job_id} killed ({kill_status}): {reason}")


class CancelledError(Exception):
    """Raised when a job is cancelled."""
    def __init__(self, job_id: str):
        self.job_id = job_id
        super().__init__(f"Job {job_id} cancelled")


# ---------------------------------------------------------------------------
# Kill Flags — file-based kill switch
# ---------------------------------------------------------------------------

def load_kill_flags() -> dict:
    """Load kill flags from disk. Returns {job_id: {"reason": ..., "timestamp": ...}}."""
    try:
        if KILL_FLAGS_PATH.exists():
            with open(KILL_FLAGS_PATH) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def set_kill_flag(job_id: str, reason: str = "manual"):
    """Set a kill flag for a job (called from the API)."""
    flags = load_kill_flags()
    flags[job_id] = {"reason": reason, "timestamp": _now_iso()}
    KILL_FLAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(KILL_FLAGS_PATH, "w") as f:
        json.dump(flags, f, indent=2)


def clear_kill_flag(job_id: str):
    """Remove a kill flag after a job finishes."""
    flags = load_kill_flags()
    if job_id in flags:
        del flags[job_id]
        with open(KILL_FLAGS_PATH, "w") as f:
            json.dump(flags, f, indent=2)


# ---------------------------------------------------------------------------
# JobGuardrails — per-job safety limits
# ---------------------------------------------------------------------------

class JobGuardrails:
    """
    Tracks cost, iterations, wall-clock time, error patterns, and kill flags
    for a single job. Call check() at every iteration boundary.

    Phase iteration limits prevent any single phase from hogging all iterations.
    Progressive warnings are logged at 50%, 75%, 90%.
    """

    WARNING_THRESHOLDS = (0.50, 0.75, 0.90)

    PHASE_ITERATION_LIMITS = {
        "research": 60,
        "plan":     30,
        "execute":  250,
        "verify":   30,
        "deliver":  30,
    }

    def __init__(
        self,
        job_id: str,
        max_cost_usd: float = 2.0,
        max_iterations: int = 400,
        max_duration_secs: int = 3600,
        circuit_breaker_n: int = 3,
    ):
        self.job_id = job_id
        self.max_cost_usd = max_cost_usd
        self.max_iterations = max_iterations
        self.max_duration_secs = max_duration_secs
        self.circuit_breaker_n = circuit_breaker_n

        self.iterations = 0
        self.cost_usd = 0.0
        self.start_time = time.monotonic()

        self.current_phase: str = "research"
        self.phase_iterations: dict[str, int] = {
            "research": 0, "plan": 0, "execute": 0, "verify": 0, "deliver": 0,
        }

        self._recent_errors: list[str] = []
        self._cost_warnings_fired: set[float] = set()
        self._iter_warnings_fired: set[float] = set()

        logger.info(
            f"[Guardrails] Job {job_id}: max_cost=${max_cost_usd}, "
            f"max_iter={max_iterations}, max_duration={max_duration_secs}s, "
            f"circuit_breaker={circuit_breaker_n}"
        )

    def set_phase(self, phase: str):
        self.current_phase = phase

    def record_iteration(self, cost_increment: float = 0.0):
        self.iterations += 1
        self.cost_usd += cost_increment
        if self.current_phase in self.phase_iterations:
            self.phase_iterations[self.current_phase] += 1

    def record_error(self, error_msg: str):
        normalized = error_msg.strip()[:200]
        self._recent_errors.append(normalized)
        if len(self._recent_errors) > self.circuit_breaker_n + 2:
            self._recent_errors = self._recent_errors[-(self.circuit_breaker_n + 2):]

    def clear_errors(self):
        self._recent_errors.clear()

    def check(self):
        """Check all guardrails. Raises GuardrailViolation if any limit breached."""
        # 1. Kill switch
        flags = load_kill_flags()
        if self.job_id in flags:
            reason = flags[self.job_id].get("reason", "manual kill")
            raise GuardrailViolation(self.job_id, f"Kill switch activated: {reason}", "killed_manual")

        # 2. Cost cap (with 10% grace)
        self._check_progressive_warnings("cost", self.cost_usd, self.max_cost_usd, self._cost_warnings_fired)
        hard_limit = self.max_cost_usd * 1.10
        if self.cost_usd > hard_limit:
            raise GuardrailViolation(
                self.job_id,
                f"Cost ${self.cost_usd:.4f} exceeds cap ${self.max_cost_usd:.2f} (+10% grace = ${hard_limit:.2f})",
                "killed_cost_limit",
            )

        # 3. Iteration cap (global)
        self._check_progressive_warnings("iterations", self.iterations, self.max_iterations, self._iter_warnings_fired)
        if self.iterations > self.max_iterations:
            raise GuardrailViolation(
                self.job_id,
                f"Iterations {self.iterations} exceeds cap {self.max_iterations}",
                "killed_iteration_limit",
            )

        # 3b. Per-phase iteration cap
        if self.current_phase in self.PHASE_ITERATION_LIMITS:
            phase_count = self.phase_iterations.get(self.current_phase, 0)
            phase_limit = self.PHASE_ITERATION_LIMITS[self.current_phase]
            if phase_count > phase_limit:
                raise GuardrailViolation(
                    self.job_id,
                    f"Phase '{self.current_phase}' iterations {phase_count} exceeds phase cap {phase_limit}",
                    "killed_phase_iteration_limit",
                )

        # 4. Wall-clock timeout
        elapsed = time.monotonic() - self.start_time
        if elapsed > self.max_duration_secs:
            raise GuardrailViolation(
                self.job_id,
                f"Wall-clock {elapsed:.0f}s exceeds cap {self.max_duration_secs}s",
                "killed_timeout",
            )

        # 5. Circuit breaker
        if len(self._recent_errors) >= self.circuit_breaker_n:
            tail = self._recent_errors[-self.circuit_breaker_n:]
            if len(set(tail)) == 1:
                raise GuardrailViolation(
                    self.job_id,
                    f"Same error repeated {self.circuit_breaker_n}x: {tail[0][:100]}",
                    "killed_circuit_breaker",
                )

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.start_time

    def summary(self) -> dict:
        return {
            "iterations": self.iterations,
            "max_iterations": self.max_iterations,
            "cost_usd": round(self.cost_usd, 6),
            "max_cost_usd": self.max_cost_usd,
            "elapsed_seconds": round(self.elapsed_seconds(), 1),
            "max_duration_seconds": self.max_duration_secs,
            "recent_errors": len(self._recent_errors),
            "current_phase": self.current_phase,
            "phase_iterations": dict(self.phase_iterations),
        }

    def _check_progressive_warnings(self, metric_name: str, current: float, limit: float, fired: set):
        if limit <= 0:
            return
        ratio = current / limit
        for threshold in self.WARNING_THRESHOLDS:
            if ratio >= threshold and threshold not in fired:
                fired.add(threshold)
                pct = int(threshold * 100)
                logger.warning(
                    f"[Guardrails] Job {self.job_id}: {metric_name} at {pct}% ({current:.4f} / {limit:.4f})"
                )
