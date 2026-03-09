"""
Confidence gate for self-repair loops.

After a response is produced, the gate evaluates confidence and can request
an additional repair pass when confidence is too low.
"""

from dataclasses import dataclass, field
from typing import Optional
import json
import logging
import re

logger = logging.getLogger("openclaw.confidence_gate")


class ConfidenceVerdict:
    PASS = "pass"
    REPAIR = "repair"
    EXHAUSTED = "exhausted"
    SKIP = "skip"


@dataclass
class ConfidenceConfig:
    threshold: float = 0.75
    max_repairs: int = 2
    enabled: bool = True
    ask_agent: bool = True


@dataclass
class ConfidenceResult:
    verdict: str = ConfidenceVerdict.PASS
    score: float = 1.0
    threshold: float = 0.75
    repairs_used: int = 0
    repairs_remaining: int = 2
    weak_points: list[str] = field(default_factory=list)
    repair_prompt: str = ""
    message: str = ""


class ConfidenceGate:
    """Self-scoring confidence gate with bounded repair attempts."""

    DEFAULT_CONFIGS = {
        # OpenClaw keys
        "coder_agent": ConfidenceConfig(threshold=0.70),
        "elite_coder_agent": ConfidenceConfig(threshold=0.75),
        "security_agent": ConfidenceConfig(threshold=0.80),
        "database_agent": ConfidenceConfig(threshold=0.80),
        "researcher_agent": ConfidenceConfig(threshold=0.60),
        "project_manager": ConfidenceConfig(threshold=0.65),
        # Task-spec aliases
        "codegen_pro": ConfidenceConfig(threshold=0.70),
        "codegen_elite": ConfidenceConfig(threshold=0.75),
        "pentest_ai": ConfidenceConfig(threshold=0.80),
        "supabase_connector": ConfidenceConfig(threshold=0.80),
        "researcher": ConfidenceConfig(threshold=0.60),
        "overseer": ConfidenceConfig(threshold=0.65),
    }

    SELF_SCORE_PROMPT = (
        "[CONFIDENCE CHECK] Before this response is accepted, score your confidence "
        "in the quality and correctness of your output on a scale of 0.0 to 1.0. "
        'Reply with ONLY a JSON object: {"confidence": 0.85, "weak_points": ["concern"]}'
    )

    REPAIR_PROMPT_TEMPLATE = (
        "[SELF-REPAIR] Your confidence score was {score:.2f} (threshold: {threshold:.2f}). "
        "You identified these weak points: {weak_points}. "
        "Please revise your previous response to address these issues. "
        "Focus specifically on: {focus}. "
        "Produce an improved, complete response."
    )

    def __init__(self, default_config: Optional[ConfidenceConfig] = None):
        self.default_config = default_config or ConfidenceConfig()
        self._configs: dict[str, ConfidenceConfig] = dict(self.DEFAULT_CONFIGS)
        self._turn_repairs: dict[str, int] = {}
        self._stats = {
            "evaluated": 0,
            "passed": 0,
            "repaired": 0,
            "exhausted": 0,
            "skipped": 0,
        }

    def set_config(self, agent_key: str, config: ConfidenceConfig):
        self._configs[agent_key] = config

    def get_config(self, agent_key: str) -> ConfidenceConfig:
        return self._configs.get(agent_key, self.default_config)

    def get_self_score_prompt(self) -> str:
        return self.SELF_SCORE_PROMPT

    def evaluate(
        self,
        job_id: str,
        agent_key: str,
        score: float,
        turn_index: int = 0,
        weak_points: Optional[list[str]] = None,
    ) -> ConfidenceResult:
        config = self.get_config(agent_key)
        self._stats["evaluated"] += 1

        score = max(0.0, min(1.0, float(score)))
        weak = [str(w) for w in (weak_points or [])]

        if not config.enabled:
            self._stats["skipped"] += 1
            return ConfidenceResult(
                verdict=ConfidenceVerdict.SKIP,
                score=score,
                threshold=config.threshold,
                repairs_used=0,
                repairs_remaining=config.max_repairs,
                weak_points=weak,
                message="Confidence gate disabled for this agent.",
            )

        turn_key = f"{job_id}:{turn_index}"
        repairs_used = self._turn_repairs.get(turn_key, 0)
        repairs_remaining = max(0, config.max_repairs - repairs_used)

        if score >= config.threshold:
            self._stats["passed"] += 1
            return ConfidenceResult(
                verdict=ConfidenceVerdict.PASS,
                score=score,
                threshold=config.threshold,
                repairs_used=repairs_used,
                repairs_remaining=repairs_remaining,
                weak_points=weak,
                message=f"Confidence {score:.2f} >= {config.threshold:.2f}",
            )

        if repairs_remaining <= 0:
            self._stats["exhausted"] += 1
            return ConfidenceResult(
                verdict=ConfidenceVerdict.EXHAUSTED,
                score=score,
                threshold=config.threshold,
                repairs_used=repairs_used,
                repairs_remaining=0,
                weak_points=weak,
                message=f"Confidence {score:.2f} below threshold, repairs exhausted",
            )

        self._turn_repairs[turn_key] = repairs_used + 1
        self._stats["repaired"] += 1
        focus = ", ".join(weak) if weak else "completeness and correctness"
        repair_prompt = self.REPAIR_PROMPT_TEMPLATE.format(
            score=score,
            threshold=config.threshold,
            weak_points=weak or ["unspecified"],
            focus=focus,
        )
        return ConfidenceResult(
            verdict=ConfidenceVerdict.REPAIR,
            score=score,
            threshold=config.threshold,
            repairs_used=repairs_used + 1,
            repairs_remaining=repairs_remaining - 1,
            weak_points=weak,
            repair_prompt=repair_prompt,
            message=(
                f"Confidence {score:.2f} below {config.threshold:.2f}, "
                f"repair #{repairs_used + 1} triggered"
            ),
        )

    def parse_self_score(self, agent_response: str) -> tuple[float, list[str]]:
        """
        Parse confidence score JSON.

        Returns (1.0, []) on parse failure to avoid blocking execution.
        """
        try:
            match = re.search(r"\{[^}]+\}", agent_response or "", re.DOTALL)
            if not match:
                return 1.0, []
            data = json.loads(match.group())
            score = float(data.get("confidence", 1.0))
            score = max(0.0, min(1.0, score))
            weak = data.get("weak_points", [])
            if isinstance(weak, list):
                return score, [str(w) for w in weak]
            return score, []
        except Exception:
            return 1.0, []

    def clear(self, job_id: str):
        keys = [k for k in self._turn_repairs if k.startswith(f"{job_id}:")]
        for key in keys:
            del self._turn_repairs[key]

    def get_stats(self) -> dict:
        return dict(self._stats)


_gate: Optional[ConfidenceGate] = None


def init_confidence_gate(**kwargs) -> ConfidenceGate:
    global _gate
    _gate = ConfidenceGate(**kwargs)
    return _gate


def get_confidence_gate() -> ConfidenceGate:
    global _gate
    if _gate is None:
        _gate = ConfidenceGate()
    return _gate
