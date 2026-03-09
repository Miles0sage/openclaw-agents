"""Tests for llm_judge.py — LLM-as-Judge evaluation."""
import pytest
from llm_judge import (
    ScoreDimension, DimensionScore, JudgeResult, LLMJudge,
    RUBRICS, AGENT_TO_RUBRIC, get_judge, init_judge,
)


class TestScoreDimension:
    def test_enum_values(self):
        assert ScoreDimension.CORRECTNESS.value == "correctness"
        assert ScoreDimension.COMPLETENESS.value == "completeness"


class TestDimensionScore:
    def test_creation(self):
        ds = DimensionScore(dimension="correctness", score=0.85, weight=0.3, reasoning="Good")
        assert ds.score == 0.85
        assert ds.weight == 0.3
        assert ds.reasoning == "Good"


class TestJudgeResult:
    def test_to_dict(self):
        ds = DimensionScore(dimension="correctness", score=0.9, weight=1.0, reasoning="Great")
        jr = JudgeResult(
            job_id="j1", agent_key="coder", overall_score=0.9,
            confidence=0.8, dimensions=[ds],
        )
        d = jr.to_dict()
        assert d["overall_score"] == 0.9
        assert len(d["dimensions"]) == 1
        assert d["dimensions"][0]["dimension"] == "correctness"

    def test_passed_threshold(self):
        jr = JudgeResult(
            job_id="j1", agent_key="coder", overall_score=0.9,
            confidence=0.8, dimensions=[],
        )
        assert jr.passed is True

    def test_failed_threshold(self):
        jr = JudgeResult(
            job_id="j1", agent_key="coder", overall_score=0.3,
            confidence=0.8, dimensions=[],
        )
        assert jr.passed is False


class TestRubrics:
    def test_rubrics_exist(self):
        assert "coder_agent" in RUBRICS
        assert "default" in RUBRICS

    def test_rubric_structure(self):
        for rubric_name, rubric in RUBRICS.items():
            total_weight = sum(dim["weight"] for dim in rubric)
            # Weights are relative (typically sum to ~7-11), not normalized to 1.0
            assert total_weight > 1.0, f"Rubric {rubric_name} weights should be relative (got {total_weight})"
            # Each dimension has required fields
            for dim in rubric:
                assert "dimension" in dim
                assert "weight" in dim
                assert "criteria" in dim

    def test_agent_mapping(self):
        assert "coder_agent" in AGENT_TO_RUBRIC
        assert AGENT_TO_RUBRIC["coder_agent"] == "coder_agent"


class TestLLMJudge:
    def test_init_without_model_fn(self):
        judge = LLMJudge()
        assert judge is not None

    @pytest.mark.asyncio
    async def test_score_output_heuristic_fallback(self):
        """When no call_model_fn is provided, should fall back to heuristic scoring."""
        judge = LLMJudge()
        result = await judge.score_output(
            job_id="test_j1",
            agent_key="coder_agent",
            task_description="Fix the login button color",
            agent_output='{"delivered": true, "summary": "Changed button color from blue to red", "commit_hash": "abc123"}',
        )
        assert isinstance(result, JudgeResult)
        assert 0.0 <= result.overall_score <= 1.0
        assert len(result.dimensions) > 0

    @pytest.mark.asyncio
    async def test_score_output_unknown_agent(self):
        """Unknown agents should use default rubric."""
        judge = LLMJudge()
        result = await judge.score_output(
            job_id="test_j2",
            agent_key="unknown_agent_xyz",
            task_description="Do something",
            agent_output="Done",
        )
        assert isinstance(result, JudgeResult)
        assert 0.0 <= result.overall_score <= 1.0

    def test_singleton(self):
        judge = init_judge()
        assert get_judge() is judge
