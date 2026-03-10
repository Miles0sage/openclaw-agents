"""Benchmark scoring wrapper around LLM judge with safe fallback."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("openclaw.benchmarks.scorer")


@dataclass
class ScoreBundle:
    overall_score: float = 0.0
    dimension_scores: dict[str, float] = field(default_factory=dict)
    reasoning: str = ""


class BenchmarkScorer:
    """Scores benchmark outputs using llm_judge when available."""

    async def score(self, *, problem_id: str, agent_key: str, task_description: str, job_result: dict[str, Any]) -> ScoreBundle:
        try:
            from llm_judge import get_judge

            judge = get_judge()
            if not judge:
                return self._heuristic(job_result)

            jr = await judge.score_output(
                job_id=f"bench_{problem_id}",
                agent_key=agent_key,
                task_description=task_description,
                agent_output=json.dumps(job_result, default=str)[:4000],
            )
            dims: dict[str, float] = {}
            for dim in getattr(jr, "dimensions", []) or []:
                name = str(getattr(dim, "dimension", ""))
                score = float(getattr(dim, "score", 0.0) or 0.0)
                if name:
                    dims[name] = score
            return ScoreBundle(
                overall_score=float(getattr(jr, "overall_score", 0.0) or 0.0),
                dimension_scores=dims,
                reasoning=str(getattr(jr, "reasoning", "") or ""),
            )
        except Exception as exc:
            logger.debug("Judge scoring skipped for %s: %s", problem_id, exc)
            return self._heuristic(job_result)

    def _heuristic(self, job_result: dict[str, Any]) -> ScoreBundle:
        status = str(job_result.get("status", "")).lower()
        if status in {"done", "completed", "success"}:
            return ScoreBundle(overall_score=0.7, reasoning="Heuristic pass: successful status")
        if status in {"failed", "error", "timeout", "cancelled"}:
            return ScoreBundle(overall_score=0.2, reasoning="Heuristic fail: terminal non-success status")
        return ScoreBundle(overall_score=0.5, reasoning="Heuristic neutral: unknown status")
