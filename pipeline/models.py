"""
Core data models for the OpenClaw job pipeline.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum


class Phase(str, Enum):
    RESEARCH    = "research"
    PLAN        = "plan"
    EXECUTE     = "execute"
    CODE_REVIEW = "code_review"
    VERIFY      = "verify"
    DELIVER     = "deliver"


@dataclass
class PlanStep:
    index: int
    description: str
    tool_hints: list = field(default_factory=list)
    status: str = "pending"         # pending | running | done | failed | skipped
    result: str = ""
    attempts: int = 0
    error: str = ""
    delegate_to: str = ""           # agent key for delegation (empty = use default agent)


@dataclass
class ExecutionPlan:
    job_id: str
    agent: str
    steps: list = field(default_factory=list)   # list[PlanStep]
    created_at: str = ""

    def to_dict(self):
        return {
            "job_id": self.job_id,
            "agent": self.agent,
            "steps": [asdict(s) for s in self.steps],
            "created_at": self.created_at,
        }


@dataclass
class JobProgress:
    job_id: str
    phase: Phase = Phase.RESEARCH
    phase_status: str = "pending"       # pending | running | done | failed
    step_index: int = 0
    total_steps: int = 0
    cost_usd: float = 0.0
    started_at: str = ""
    updated_at: str = ""
    error: str = ""
    retries: int = 0
    cancelled: bool = False
    workspace: str = ""                 # isolated per-job workspace directory

    def to_dict(self):
        return {
            "job_id": self.job_id,
            "phase": self.phase.value,
            "phase_status": self.phase_status,
            "step_index": self.step_index,
            "total_steps": self.total_steps,
            "cost_usd": round(self.cost_usd, 6),
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "retries": self.retries,
            "cancelled": self.cancelled,
            "workspace": self.workspace,
        }
