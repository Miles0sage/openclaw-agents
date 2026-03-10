"""Tests for benchmark Markdown report generation."""

from benchmarks.reporter import generate_markdown
from benchmarks.runner import ProblemResult, SuiteResult



def test_generate_markdown():
    result = ProblemResult(
        problem_id="test-1",
        category="bug_fix",
        difficulty="easy",
        passed=True,
        overall_score=0.85,
        file_checks_passed=1,
        file_checks_total=1,
        command_checks_passed=0,
        command_checks_total=0,
        cost_usd=0.01,
        duration_sec=5.0,
        agent_key="coder_agent",
    )

    suite = SuiteResult(
        suite_name="test",
        timestamp="2026-03-08T00:00:00Z",
        total=1,
        passed=1,
        failed=0,
        pass_rate=1.0,
        avg_score=0.85,
        total_cost_usd=0.01,
        total_duration_sec=5.0,
        by_difficulty={"easy": {"total": 1, "passed": 1, "pass_rate": 1.0}},
        by_category={"bug_fix": {"total": 1, "passed": 1, "pass_rate": 1.0}},
        results=[result],
    )

    md = generate_markdown(suite)
    assert "# OpenClaw Benchmark Report" in md
    assert "100%" in md
    assert "test-1" in md
    assert "PASS" in md
