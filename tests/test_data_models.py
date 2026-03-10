"""Tests for core data models: Phase, PlanStep, ExecutionPlan, JobProgress."""

import pytest
from autonomous_runner import Phase, PlanStep, ExecutionPlan, JobProgress, _now_iso


class TestPhase:
    def test_enum_values(self):
        assert Phase.RESEARCH.value == "research"
        assert Phase.PLAN.value == "plan"
        assert Phase.EXECUTE.value == "execute"
        assert Phase.CODE_REVIEW.value == "code_review"
        assert Phase.VERIFY.value == "verify"
        assert Phase.DELIVER.value == "deliver"

    def test_phase_count(self):
        assert len(Phase) == 6

    def test_string_comparison(self):
        assert Phase.RESEARCH == "research"
        assert Phase.EXECUTE == "execute"


class TestPlanStep:
    def test_defaults(self):
        step = PlanStep(index=0, description="Write code")
        assert step.index == 0
        assert step.description == "Write code"
        assert step.tool_hints == []
        assert step.status == "pending"
        assert step.result == ""
        assert step.attempts == 0
        assert step.error == ""
        assert step.delegate_to == ""

    def test_with_tools(self):
        step = PlanStep(index=1, description="Run tests", tool_hints=["shell_execute"])
        assert step.tool_hints == ["shell_execute"]


class TestExecutionPlan:
    def test_to_dict(self):
        plan = ExecutionPlan(
            job_id="test-001",
            agent="coder_agent",
            steps=[
                PlanStep(index=0, description="Step 1", tool_hints=["file_write"]),
                PlanStep(index=1, description="Step 2"),
            ],
            created_at="2026-03-04T00:00:00Z",
        )
        d = plan.to_dict()
        assert d["job_id"] == "test-001"
        assert d["agent"] == "coder_agent"
        assert len(d["steps"]) == 2
        assert d["steps"][0]["description"] == "Step 1"
        assert d["steps"][0]["tool_hints"] == ["file_write"]
        assert d["steps"][1]["status"] == "pending"

    def test_empty_plan(self):
        plan = ExecutionPlan(job_id="empty", agent="coder_agent")
        d = plan.to_dict()
        assert d["steps"] == []


class TestJobProgress:
    def test_defaults(self):
        p = JobProgress(job_id="test-001")
        assert p.phase == Phase.RESEARCH
        assert p.phase_status == "pending"
        assert p.cost_usd == 0.0
        assert p.cancelled is False

    def test_to_dict(self):
        p = JobProgress(
            job_id="test-001",
            phase=Phase.EXECUTE,
            phase_status="running",
            step_index=2,
            total_steps=5,
            cost_usd=0.123456789,
            started_at="2026-03-04T00:00:00Z",
        )
        d = p.to_dict()
        assert d["phase"] == "execute"
        assert d["cost_usd"] == 0.123457  # rounded to 6 decimal places
        assert d["step_index"] == 2
        assert d["total_steps"] == 5

    def test_cost_rounding(self):
        p = JobProgress(job_id="test", cost_usd=1.123456789)
        assert p.to_dict()["cost_usd"] == 1.123457


class TestNowIso:
    def test_returns_iso_format(self):
        result = _now_iso()
        assert "T" in result
        assert "+" in result or "Z" in result  # timezone-aware

    def test_returns_utc(self):
        result = _now_iso()
        assert "+00:00" in result or "Z" in result
