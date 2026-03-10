"""
Quality gate for post-judge job evaluation.

Verdicts:
- pass: score >= pass_threshold
- warn: score >= warn_threshold and < pass_threshold (no retries left)
- retry: score < pass_threshold and retries remain
- fail: score < fail_threshold, or below warn threshold after retries
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class QualityConfig:
    """Quality gate thresholds and retry behavior."""

    pass_threshold: float = 0.70
    warn_threshold: float = 0.50
    fail_threshold: float = 0.30
    max_quality_retries: int = 1
    retry_with_feedback: bool = True


class QualityVerdict:
    PASS = "pass"
    WARN = "warn"
    RETRY = "retry"
    FAIL = "fail"


@dataclass
class QualityResult:
    verdict: str = QualityVerdict.PASS
    score: float = 0.0
    threshold: float = 0.70
    message: str = ""
    should_retry: bool = False
    retry_feedback: str = ""
    retries_used: int = 0
    retries_remaining: int = 0


class QualityGate:
    """Evaluates judge scores and returns a quality verdict."""

    DEFAULT_CONFIGS = {
        # Primary keys used by OpenClaw
        "coder_agent": QualityConfig(pass_threshold=0.60, warn_threshold=0.40),
        "elite_coder_agent": QualityConfig(pass_threshold=0.70, warn_threshold=0.50),
        "security_agent": QualityConfig(pass_threshold=0.80, warn_threshold=0.60),
        "database_agent": QualityConfig(pass_threshold=0.70, warn_threshold=0.50),
        "researcher_agent": QualityConfig(pass_threshold=0.50, warn_threshold=0.30),
        # Aliases used in architecture docs/tasks
        "codegen_pro": QualityConfig(pass_threshold=0.60, warn_threshold=0.40),
        "codegen_elite": QualityConfig(pass_threshold=0.70, warn_threshold=0.50),
        "pentest_ai": QualityConfig(pass_threshold=0.80, warn_threshold=0.60),
        "supabase_connector": QualityConfig(pass_threshold=0.70, warn_threshold=0.50),
        "researcher": QualityConfig(pass_threshold=0.50, warn_threshold=0.30),
    }

    def __init__(self, default_config: Optional[QualityConfig] = None):
        self.default_config = default_config or QualityConfig()
        self._agent_configs: dict[str, QualityConfig] = dict(self.DEFAULT_CONFIGS)
        self._job_configs: dict[str, QualityConfig] = {}
        self._job_retries: dict[str, int] = {}
        self._stats = {
            "total": 0,
            "passed": 0,
            "warned": 0,
            "retried": 0,
            "failed": 0,
        }

    def set_config(self, agent_key: str, config: QualityConfig):
        """Set config for a specific agent key."""
        self._agent_configs[agent_key] = config

    def set_job_config(self, job_id: str, config: QualityConfig):
        """Set config override for a specific job."""
        self._job_configs[job_id] = config

    def clear_job_config(self, job_id: str):
        self._job_configs.pop(job_id, None)

    def get_config(self, agent_key: str, job_id: str = "") -> QualityConfig:
        """Resolve config with precedence: job override > agent config > default."""
        if job_id and job_id in self._job_configs:
            return self._job_configs[job_id]
        return self._agent_configs.get(agent_key, self.default_config)

    def evaluate(
        self,
        job_id: str,
        agent_key: str,
        score: float,
        judge_feedback: str = "",
    ) -> QualityResult:
        """Evaluate a score and return a quality verdict."""
        config = self.get_config(agent_key, job_id=job_id)
        score = max(0.0, min(1.0, float(score)))

        retries_used = self._job_retries.get(job_id, 0)
        retries_remaining = max(0, config.max_quality_retries - retries_used)

        self._stats["total"] += 1

        if score >= config.pass_threshold:
            self._stats["passed"] += 1
            return QualityResult(
                verdict=QualityVerdict.PASS,
                score=score,
                threshold=config.pass_threshold,
                message=f"Quality passed: {score:.2f} >= {config.pass_threshold:.2f}",
                retries_used=retries_used,
                retries_remaining=retries_remaining,
            )

        if score < config.fail_threshold:
            self._stats["failed"] += 1
            return QualityResult(
                verdict=QualityVerdict.FAIL,
                score=score,
                threshold=config.pass_threshold,
                message=(
                    f"Quality failed hard: {score:.2f} < {config.fail_threshold:.2f} "
                    "(fail threshold)"
                ),
                retries_used=retries_used,
                retries_remaining=0,
            )

        if retries_remaining > 0 and config.retry_with_feedback:
            self._job_retries[job_id] = retries_used + 1
            self._stats["retried"] += 1
            feedback = self._build_retry_feedback(score, config, judge_feedback)
            return QualityResult(
                verdict=QualityVerdict.RETRY,
                score=score,
                threshold=config.pass_threshold,
                message=(
                    f"Quality below threshold: {score:.2f} < {config.pass_threshold:.2f}. "
                    "Retrying with feedback."
                ),
                should_retry=True,
                retry_feedback=feedback,
                retries_used=retries_used + 1,
                retries_remaining=retries_remaining - 1,
            )

        if score >= config.warn_threshold:
            self._stats["warned"] += 1
            return QualityResult(
                verdict=QualityVerdict.WARN,
                score=score,
                threshold=config.pass_threshold,
                message=(
                    f"Quality marginal: {score:.2f} "
                    f"(warn threshold: {config.warn_threshold:.2f})"
                ),
                retries_used=retries_used,
                retries_remaining=0,
            )

        self._stats["failed"] += 1
        return QualityResult(
            verdict=QualityVerdict.FAIL,
            score=score,
            threshold=config.pass_threshold,
            message=(
                f"Quality failed: {score:.2f} < {config.warn_threshold:.2f} "
                "(retries exhausted)"
            ),
            retries_used=retries_used,
            retries_remaining=0,
        )

    def _build_retry_feedback(
        self,
        score: float,
        config: QualityConfig,
        judge_feedback: str,
    ) -> str:
        parts = [
            (
                f"[QUALITY GATE] Previous output scored {score:.2f}. "
                f"Required threshold: {config.pass_threshold:.2f}."
            ),
            "The output did not meet quality standards. Improve the result.",
        ]
        if judge_feedback:
            parts.append(f"Judge feedback: {judge_feedback}")
        parts.append("Revise your output to directly address these issues.")
        return "\n".join(parts)

    def clear(self, job_id: str):
        """Clear retry state for one job."""
        self._job_retries.pop(job_id, None)
        self._job_configs.pop(job_id, None)

    def get_stats(self) -> dict:
        return dict(self._stats)


_gate: Optional[QualityGate] = None


def init_quality_gate(**kwargs) -> QualityGate:
    global _gate
    _gate = QualityGate(**kwargs)
    return _gate


def get_quality_gate() -> QualityGate:
    global _gate
    if _gate is None:
        _gate = QualityGate()
    return _gate
