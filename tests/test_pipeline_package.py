"""Tests for the pipeline package — ensures extracted modules match original behavior."""

import pytest
from pipeline import (
    Phase, PlanStep, ExecutionPlan, JobProgress,
    classify_error, get_error_config, make_call_signature, check_loop,
    ERROR_CATEGORIES, TRANSIENT_ERROR_PATTERNS, PERMANENT_ERROR_PATTERNS,
    JobGuardrails, GuardrailViolation, BudgetExceededError,
    CreditExhaustedError, CancelledError,
)
from pipeline.errors import LOOP_DETECT_THRESHOLD


class TestPipelineModels:
    """Verify pipeline.models matches autonomous_runner originals."""

    def test_phase_values(self):
        assert Phase.RESEARCH.value == "research"
        assert Phase.DELIVER.value == "deliver"
        assert len(Phase) == 6

    def test_plan_step_defaults(self):
        step = PlanStep(index=0, description="test")
        assert step.status == "pending"
        assert step.tool_hints == []

    def test_execution_plan_to_dict(self):
        plan = ExecutionPlan(job_id="j1", agent="a1", steps=[PlanStep(0, "step")])
        d = plan.to_dict()
        assert d["job_id"] == "j1"
        assert len(d["steps"]) == 1

    def test_job_progress_to_dict(self):
        p = JobProgress(job_id="j1", cost_usd=1.999999999)
        d = p.to_dict()
        assert d["cost_usd"] == 2.0  # rounded to 6 decimal places


class TestPipelineErrors:
    """Verify pipeline.errors matches autonomous_runner originals."""

    def test_classify_network(self):
        assert classify_error("rate limit exceeded") == "network"

    def test_classify_auth(self):
        assert classify_error("401 unauthorized") == "auth"

    def test_classify_unknown(self):
        assert classify_error("something weird") == "unknown"

    def test_get_config(self):
        c = get_error_config("network")
        assert c["max_retries"] == 3

    def test_call_signature_deterministic(self):
        s1 = make_call_signature("tool", {"a": 1})
        s2 = make_call_signature("tool", {"a": 1})
        assert s1 == s2

    def test_check_loop(self):
        counts = {}
        sig = make_call_signature("tool", {"a": 1})
        for _ in range(LOOP_DETECT_THRESHOLD - 1):
            check_loop(sig, counts, "job", "phase")
        assert check_loop(sig, counts, "job", "phase") is True

    def test_backward_compat_patterns(self):
        assert TRANSIENT_ERROR_PATTERNS == ERROR_CATEGORIES["network"]["patterns"]


class TestPipelineGuardrails:
    """Verify pipeline.guardrails matches autonomous_runner originals."""

    def test_guardrail_init(self):
        g = JobGuardrails("test")
        assert g.iterations == 0
        assert g.cost_usd == 0.0

    def test_exceptions(self):
        with pytest.raises(BudgetExceededError):
            raise BudgetExceededError("over")
        with pytest.raises(CreditExhaustedError):
            raise CreditExhaustedError("gone")
        with pytest.raises(CancelledError):
            raise CancelledError("job-1")

    def test_guardrail_violation_attrs(self):
        e = GuardrailViolation("j1", "reason", "status")
        assert e.job_id == "j1"
        assert e.reason == "reason"
        assert e.kill_status == "status"


class TestBackwardCompatibility:
    """Ensure autonomous_runner still exports everything correctly."""

    def test_old_imports_still_work(self):
        from autonomous_runner import Phase as OldPhase
        from autonomous_runner import JobGuardrails as OldGuardrails
        from autonomous_runner import _classify_error
        from autonomous_runner import _make_call_signature
        # These should still work
        assert OldPhase.RESEARCH.value == "research"
        assert _classify_error("rate limit") == "network"
