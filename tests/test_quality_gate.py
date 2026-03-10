"""Tests for quality_gate module."""

from quality_gate import (
    QualityConfig,
    QualityGate,
    QualityResult,
    QualityVerdict,
    get_quality_gate,
    init_quality_gate,
)


def test_pass_verdict():
    gate = QualityGate()
    result = gate.evaluate("job-1", "coder_agent", score=0.92)
    assert result.verdict == QualityVerdict.PASS
    assert result.should_retry is False


def test_hard_fail_below_fail_threshold():
    gate = QualityGate()
    result = gate.evaluate("job-2", "coder_agent", score=0.10)
    assert result.verdict == QualityVerdict.FAIL
    assert "failed hard" in result.message.lower()
    assert result.retries_remaining == 0


def test_retry_verdict_when_retries_available():
    gate = QualityGate()
    result = gate.evaluate("job-3", "coder_agent", score=0.50)
    assert result.verdict == QualityVerdict.RETRY
    assert result.should_retry is True
    assert result.retries_used == 1


def test_warn_after_retry_exhausted():
    gate = QualityGate()
    # first call consumes retry
    gate.evaluate("job-4", "coder_agent", score=0.50)
    # second call should warn (still above warn threshold)
    result = gate.evaluate("job-4", "coder_agent", score=0.50)
    assert result.verdict == QualityVerdict.WARN
    assert result.should_retry is False


def test_fail_after_retry_exhausted_below_warn():
    gate = QualityGate()
    gate.evaluate("job-5", "coder_agent", score=0.39)  # retry
    result = gate.evaluate("job-5", "coder_agent", score=0.39)
    assert result.verdict == QualityVerdict.FAIL
    assert "retries exhausted" in result.message.lower()


def test_retry_feedback_contains_judge_feedback():
    gate = QualityGate()
    result = gate.evaluate(
        "job-6",
        "coder_agent",
        score=0.45,
        judge_feedback="Missing edge-case handling",
    )
    assert result.verdict == QualityVerdict.RETRY
    assert "Missing edge-case handling" in result.retry_feedback


def test_per_agent_default_thresholds():
    gate = QualityGate()
    security_cfg = gate.get_config("security_agent")
    research_cfg = gate.get_config("researcher_agent")
    assert security_cfg.pass_threshold > research_cfg.pass_threshold


def test_set_config_override():
    gate = QualityGate()
    gate.set_config("coder_agent", QualityConfig(pass_threshold=0.95, warn_threshold=0.80))
    cfg = gate.get_config("coder_agent")
    assert cfg.pass_threshold == 0.95
    assert cfg.warn_threshold == 0.80


def test_job_config_override_precedence():
    gate = QualityGate()
    gate.set_config("coder_agent", QualityConfig(pass_threshold=0.80, warn_threshold=0.60))
    gate.set_job_config("job-7", QualityConfig(pass_threshold=0.50, warn_threshold=0.40))
    cfg = gate.get_config("coder_agent", job_id="job-7")
    assert cfg.pass_threshold == 0.50
    assert cfg.warn_threshold == 0.40


def test_clear_resets_retry_and_job_override():
    gate = QualityGate()
    gate.set_job_config("job-8", QualityConfig(pass_threshold=0.95))
    gate.evaluate("job-8", "coder_agent", score=0.50)  # consumes one retry
    gate.clear("job-8")
    cfg = gate.get_config("coder_agent", job_id="job-8")
    assert cfg.pass_threshold != 0.95
    result = gate.evaluate("job-8", "coder_agent", score=0.50)
    assert result.verdict == QualityVerdict.RETRY


def test_default_config_fallback_for_unknown_agent():
    gate = QualityGate(default_config=QualityConfig(pass_threshold=0.77, warn_threshold=0.55))
    cfg = gate.get_config("unknown-agent")
    assert cfg.pass_threshold == 0.77
    assert cfg.warn_threshold == 0.55


def test_retry_disabled_skips_retry():
    gate = QualityGate(default_config=QualityConfig(max_quality_retries=2, retry_with_feedback=False))
    result = gate.evaluate("job-9", "unknown-agent", score=0.60)
    assert result.verdict == QualityVerdict.WARN
    assert result.should_retry is False


def test_stats_tracking():
    gate = QualityGate()
    gate.evaluate("s1", "coder_agent", score=0.99)  # pass
    gate.evaluate("s2", "coder_agent", score=0.50)  # retry
    gate.evaluate("s2", "coder_agent", score=0.50)  # warn
    gate.evaluate("s3", "coder_agent", score=0.10)  # fail
    stats = gate.get_stats()
    assert stats["total"] == 4
    assert stats["passed"] == 1
    assert stats["retried"] == 1
    assert stats["warned"] == 1
    assert stats["failed"] == 1


def test_score_is_clamped_between_zero_and_one():
    gate = QualityGate()
    high = gate.evaluate("job-10", "coder_agent", score=2.0)
    low = gate.evaluate("job-11", "coder_agent", score=-1.0)
    assert high.score == 1.0
    assert low.score == 0.0


def test_singleton_init_and_get():
    g1 = init_quality_gate(default_config=QualityConfig(pass_threshold=0.66))
    g2 = get_quality_gate()
    assert g1 is g2
    assert g2.get_config("unknown").pass_threshold == 0.66
