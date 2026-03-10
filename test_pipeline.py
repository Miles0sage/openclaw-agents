"""
Unit tests for the pipeline package (models, errors, guardrails).
"""

import pytest
import time
from pathlib import Path
from unittest.mock import patch

from pipeline.models import (
    Phase,
    PlanStep,
    ExecutionPlan,
    JobProgress
)
from pipeline.errors import (
    classify_error,
    get_error_config,
    make_call_signature,
    check_loop,
    ERROR_CATEGORIES,
    LOOP_DETECT_THRESHOLD
)
from pipeline.guardrails import (
    JobGuardrails,
    GuardrailViolation,
    load_kill_flags,
    set_kill_flag,
    clear_kill_flag,
    KILL_FLAGS_PATH,
    BudgetExceededError,
    CreditExhaustedError,
    CancelledError
)


# --- Tests for pipeline.models ---

def test_models_phase_enum():
    assert Phase.RESEARCH == "research"
    assert Phase.PLAN == "plan"
    assert Phase.EXECUTE == "execute"


def test_models_plan_step():
    step = PlanStep(index=1, description="Test step")
    assert step.index == 1
    assert step.description == "Test step"
    assert step.status == "pending"
    assert step.attempts == 0
    assert step.tool_hints == []


def test_models_execution_plan():
    step1 = PlanStep(index=1, description="Step 1")
    plan = ExecutionPlan(job_id="job123", agent="pm", steps=[step1], created_at="2026-03-09")
    
    assert plan.job_id == "job123"
    assert plan.agent == "pm"
    assert len(plan.steps) == 1
    
    plan_dict = plan.to_dict()
    assert plan_dict["job_id"] == "job123"
    assert plan_dict["agent"] == "pm"
    assert len(plan_dict["steps"]) == 1
    assert plan_dict["steps"][0]["description"] == "Step 1"


def test_models_job_progress():
    jp = JobProgress(job_id="job_456", phase=Phase.PLAN)
    assert jp.job_id == "job_456"
    assert jp.phase == Phase.PLAN
    assert jp.phase_status == "pending"
    
    jp_dict = jp.to_dict()
    assert jp_dict["job_id"] == "job_456"
    assert jp_dict["phase"] == "plan"
    assert jp_dict["cost_usd"] == 0.0


# --- Tests for pipeline.errors ---

def test_errors_classify_error():
    assert classify_error("some network timeout occurred") == "network"
    assert classify_error("429 Too Many Requests") == "network"
    assert classify_error("401 Unauthorized") == "auth"
    assert classify_error("Permission denied") == "permission"
    assert classify_error("SyntaxError: invalid syntax") == "code_error"
    assert classify_error("File not found error") == "not_found"
    assert classify_error("Out of memory exception") == "resource"
    assert classify_error("some unknown weird random error") == "unknown"


def test_errors_get_error_config():
    config = get_error_config("network")
    assert config["max_retries"] == 3
    assert config["backoff"] == "exponential"
    assert config["action"] == "retry_same"
    
    unknown_config = get_error_config("unknown")
    assert unknown_config["max_retries"] == 2
    assert unknown_config["action"] == "diagnose_and_rewrite"


def test_errors_make_call_signature():
    sig1 = make_call_signature("my_tool", {"arg1": "value1", "arg2": "value2"})
    sig2 = make_call_signature("my_tool", {"arg2": "value2", "arg1": "value1"})  # Different dict order
    assert sig1 == sig2
    assert sig1.startswith("my_tool:")
    
    sig3 = make_call_signature("other_tool", "string input")
    assert sig3.startswith("other_tool:")
    assert sig1 != sig3


def test_errors_check_loop():
    counts = {}
    sig = "tool:hash123"
    
    assert check_loop(sig, counts, "job1", "phase1") is False
    assert counts[sig] == 1
    
    assert check_loop(sig, counts, "job1", "phase1") is False
    assert counts[sig] == 2
    
    # Threshold is 3
    assert check_loop(sig, counts, "job1", "phase1") is True
    assert counts[sig] == 3


# --- Tests for pipeline.guardrails ---

@pytest.fixture
def mock_kill_flags_path(tmp_path):
    flags_file = tmp_path / "kill_flags.json"
    with patch("pipeline.guardrails.KILL_FLAGS_PATH", flags_file):
        yield flags_file


def test_guardrails_kill_flags(mock_kill_flags_path):
    assert load_kill_flags() == {}
    
    set_kill_flag("job_1", "testing")
    flags = load_kill_flags()
    assert "job_1" in flags
    assert flags["job_1"]["reason"] == "testing"
    
    clear_kill_flag("job_1")
    assert load_kill_flags() == {}


def test_guardrails_exceptions():
    with pytest.raises(GuardrailViolation) as excinfo:
        raise GuardrailViolation("job_1", "too expensive", "killed_cost_limit")
    assert excinfo.value.job_id == "job_1"
    assert excinfo.value.kill_status == "killed_cost_limit"
    
    with pytest.raises(CancelledError) as excinfo:
        raise CancelledError("job_1")
    assert excinfo.value.job_id == "job_1"


def test_job_guardrails_init():
    g = JobGuardrails(job_id="job_g1", max_cost_usd=5.0, max_iterations=50)
    assert g.job_id == "job_g1"
    assert g.max_cost_usd == 5.0
    assert g.max_iterations == 50
    assert g.iterations == 0
    assert g.cost_usd == 0.0
    assert g.current_phase == "research"


def test_job_guardrails_record_iteration():
    g = JobGuardrails(job_id="job_g1")
    g.set_phase("execute")
    g.record_iteration(cost_increment=0.5)
    
    assert g.iterations == 1
    assert g.cost_usd == 0.5
    assert g.phase_iterations["execute"] == 1
    
    summary = g.summary()
    assert summary["iterations"] == 1
    assert summary["cost_usd"] == 0.5
    assert summary["current_phase"] == "execute"


def test_job_guardrails_error_recording():
    g = JobGuardrails(job_id="job_g1", circuit_breaker_n=3)
    
    g.record_error("error A")
    g.record_error("error B")
    assert len(g._recent_errors) == 2
    
    g.clear_errors()
    assert len(g._recent_errors) == 0


def test_job_guardrails_check_ok(mock_kill_flags_path):
    g = JobGuardrails(job_id="job_g1")
    # Should not raise
    g.check()


def test_job_guardrails_check_cost_violation(mock_kill_flags_path):
    g = JobGuardrails(job_id="job_g1", max_cost_usd=1.0)
    g.cost_usd = 1.2  # Exceeds 10% grace period (1.1)
    
    with pytest.raises(GuardrailViolation, match="Cost .* exceeds cap"):
        g.check()


def test_job_guardrails_check_iteration_violation(mock_kill_flags_path):
    g = JobGuardrails(job_id="job_g1", max_iterations=10)
    g.iterations = 11
    
    with pytest.raises(GuardrailViolation, match="Iterations .* exceeds cap"):
        g.check()


def test_job_guardrails_check_phase_iteration_violation(mock_kill_flags_path):
    g = JobGuardrails(job_id="job_g1")
    g.set_phase("research")
    g.phase_iterations["research"] = 65  # Limit is 60
    
    with pytest.raises(GuardrailViolation, match="Phase .* iterations .* exceeds phase cap"):
        g.check()


def test_job_guardrails_check_timeout_violation(mock_kill_flags_path):
    g = JobGuardrails(job_id="job_g1", max_duration_secs=5)
    # Mock start time to 10 seconds ago
    g.start_time = time.monotonic() - 10
    
    with pytest.raises(GuardrailViolation, match="Wall-clock .* exceeds cap"):
        g.check()


def test_job_guardrails_check_circuit_breaker_violation(mock_kill_flags_path):
    g = JobGuardrails(job_id="job_g1", circuit_breaker_n=3)
    g.record_error("Identical exact same error string")
    g.record_error("Identical exact same error string")
    g.record_error("Identical exact same error string")
    
    with pytest.raises(GuardrailViolation, match="Same error repeated 3x"):
        g.check()


def test_job_guardrails_check_kill_switch(mock_kill_flags_path):
    g = JobGuardrails(job_id="job_kill_me")
    set_kill_flag("job_kill_me", "user requested kill")
    
    with pytest.raises(GuardrailViolation, match="Kill switch activated"):
        g.check()
