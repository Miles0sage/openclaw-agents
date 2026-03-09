"""Tests for JobGuardrails: cost caps, iteration limits, circuit breaker, kill flags."""

import time
import pytest
from unittest.mock import patch
from autonomous_runner import (
    JobGuardrails,
    GuardrailViolation,
    BudgetExceededError,
    CreditExhaustedError,
)


class TestGuardrailBasics:
    def test_init_defaults(self):
        g = JobGuardrails("test-job")
        assert g.job_id == "test-job"
        assert g.iterations == 0
        assert g.cost_usd == 0.0
        assert g.current_phase == "research"

    def test_record_iteration(self):
        g = JobGuardrails("test-job")
        g.record_iteration(cost_increment=0.01)
        assert g.iterations == 1
        assert g.cost_usd == pytest.approx(0.01)

    def test_phase_iteration_tracking(self):
        g = JobGuardrails("test-job")
        g.set_phase("execute")
        g.record_iteration()
        g.record_iteration()
        assert g.phase_iterations["execute"] == 2
        assert g.phase_iterations["research"] == 0

    def test_summary(self):
        g = JobGuardrails("test-job", max_cost_usd=5.0, max_iterations=100)
        g.record_iteration(cost_increment=0.5)
        s = g.summary()
        assert s["iterations"] == 1
        assert s["max_iterations"] == 100
        assert s["cost_usd"] == pytest.approx(0.5)
        assert s["max_cost_usd"] == 5.0
        assert "elapsed_seconds" in s


class TestGuardrailCostLimit:
    @patch("autonomous_runner._load_kill_flags", return_value={})
    def test_under_limit_passes(self, mock_flags):
        g = JobGuardrails("test-job", max_cost_usd=1.0)
        g.record_iteration(cost_increment=0.5)
        g.check()  # should not raise

    @patch("autonomous_runner._load_kill_flags", return_value={})
    def test_over_limit_with_grace_raises(self, mock_flags):
        g = JobGuardrails("test-job", max_cost_usd=1.0)
        # 1.0 * 1.10 = 1.10 hard limit
        g.record_iteration(cost_increment=1.15)
        with pytest.raises(GuardrailViolation) as exc_info:
            g.check()
        assert "killed_cost_limit" in str(exc_info.value)

    @patch("autonomous_runner._load_kill_flags", return_value={})
    def test_within_grace_period_passes(self, mock_flags):
        g = JobGuardrails("test-job", max_cost_usd=1.0)
        g.record_iteration(cost_increment=1.05)  # within 10% grace
        g.check()  # should not raise


class TestGuardrailIterationLimit:
    @patch("autonomous_runner._load_kill_flags", return_value={})
    def test_under_limit_passes(self, mock_flags):
        g = JobGuardrails("test-job", max_iterations=10)
        for _ in range(10):
            g.record_iteration()
        g.check()  # exactly at limit, should pass

    @patch("autonomous_runner._load_kill_flags", return_value={})
    def test_over_limit_raises(self, mock_flags):
        g = JobGuardrails("test-job", max_iterations=5)
        for _ in range(6):
            g.record_iteration()
        with pytest.raises(GuardrailViolation) as exc_info:
            g.check()
        assert "killed_iteration_limit" in str(exc_info.value)

    @patch("autonomous_runner._load_kill_flags", return_value={})
    def test_phase_iteration_limit(self, mock_flags):
        g = JobGuardrails("test-job", max_iterations=9999)
        g.set_phase("plan")
        plan_limit = JobGuardrails.PHASE_ITERATION_LIMITS["plan"]
        for _ in range(plan_limit + 1):
            g.record_iteration()
        with pytest.raises(GuardrailViolation) as exc_info:
            g.check()
        assert "killed_phase_iteration_limit" in str(exc_info.value)


class TestGuardrailCircuitBreaker:
    @patch("autonomous_runner._load_kill_flags", return_value={})
    def test_different_errors_no_break(self, mock_flags):
        g = JobGuardrails("test-job", circuit_breaker_n=3)
        g.record_error("Error A")
        g.record_error("Error B")
        g.record_error("Error C")
        g.record_iteration()
        g.check()  # different errors, should not raise

    @patch("autonomous_runner._load_kill_flags", return_value={})
    def test_same_error_triggers_break(self, mock_flags):
        g = JobGuardrails("test-job", circuit_breaker_n=3)
        g.record_error("Same error")
        g.record_error("Same error")
        g.record_error("Same error")
        g.record_iteration()
        with pytest.raises(GuardrailViolation) as exc_info:
            g.check()
        assert "killed_circuit_breaker" in str(exc_info.value)

    @patch("autonomous_runner._load_kill_flags", return_value={})
    def test_clear_errors_resets(self, mock_flags):
        g = JobGuardrails("test-job", circuit_breaker_n=3)
        g.record_error("Same error")
        g.record_error("Same error")
        g.clear_errors()
        g.record_error("Same error")
        g.record_iteration()
        g.check()  # cleared in the middle, should not trigger


class TestGuardrailKillSwitch:
    @patch("autonomous_runner._load_kill_flags", return_value={"test-job": {"reason": "manual kill"}})
    def test_kill_flag_raises(self, mock_flags):
        g = JobGuardrails("test-job")
        g.record_iteration()
        with pytest.raises(GuardrailViolation) as exc_info:
            g.check()
        assert "killed_manual" in str(exc_info.value)

    @patch("autonomous_runner._load_kill_flags", return_value={})
    def test_no_kill_flag_passes(self, mock_flags):
        g = JobGuardrails("test-job")
        g.record_iteration()
        g.check()  # no kill flag, should pass


class TestExceptions:
    def test_budget_exceeded_error(self):
        with pytest.raises(BudgetExceededError):
            raise BudgetExceededError("Over budget")

    def test_credit_exhausted_error(self):
        with pytest.raises(CreditExhaustedError):
            raise CreditExhaustedError("No credits")

    def test_guardrail_violation_attributes(self):
        e = GuardrailViolation("job-123", "cost exceeded", "killed_cost_limit")
        assert e.job_id == "job-123"
        assert e.reason == "cost exceeded"
        assert e.kill_status == "killed_cost_limit"
        assert "job-123" in str(e)
