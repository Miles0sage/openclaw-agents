"""Tests for benchmark scorer wrapper."""

from types import SimpleNamespace

import pytest

from benchmarks.scorer import BenchmarkScorer


class _Dim:
    def __init__(self, dimension: str, score: float):
        self.dimension = dimension
        self.score = score


class _FakeJudge:
    async def score_output(self, **_kwargs):
        return SimpleNamespace(
            overall_score=0.81,
            dimensions=[_Dim("correctness", 0.9), _Dim("completeness", 0.7)],
            reasoning="good",
        )


@pytest.mark.asyncio
async def test_score_uses_judge_when_available(monkeypatch):
    monkeypatch.setattr("llm_judge.get_judge", lambda: _FakeJudge())
    scorer = BenchmarkScorer()
    bundle = await scorer.score(
        problem_id="p1",
        agent_key="coder_agent",
        task_description="task",
        job_result={"status": "done"},
    )
    assert bundle.overall_score == 0.81
    assert bundle.dimension_scores["correctness"] == 0.9


@pytest.mark.asyncio
async def test_score_falls_back_to_heuristic(monkeypatch):
    monkeypatch.setattr("llm_judge.get_judge", lambda: None)
    scorer = BenchmarkScorer()
    bundle = await scorer.score(
        problem_id="p2",
        agent_key="coder_agent",
        task_description="task",
        job_result={"status": "failed"},
    )
    assert bundle.overall_score <= 0.5
