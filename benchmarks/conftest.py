"""Shared benchmark test fixtures."""

from benchmarks.runner import ProblemResult, SuiteResult



def make_problem_result(problem_id: str = "p1", passed: bool = True) -> ProblemResult:
    return ProblemResult(
        problem_id=problem_id,
        category="bug_fix",
        difficulty="easy",
        passed=passed,
        overall_score=0.9 if passed else 0.2,
        file_checks_passed=1 if passed else 0,
        file_checks_total=1,
        command_checks_passed=0,
        command_checks_total=0,
        cost_usd=0.01,
        duration_sec=2.0,
        agent_key="coder_agent",
    )



def make_suite_result() -> SuiteResult:
    result = make_problem_result()
    return SuiteResult(
        suite_name="test",
        timestamp="2026-03-09T00:00:00+00:00",
        total=1,
        passed=1,
        failed=0,
        pass_rate=1.0,
        avg_score=0.9,
        total_cost_usd=0.01,
        total_duration_sec=2.0,
        by_difficulty={"easy": {"total": 1, "passed": 1, "pass_rate": 1.0}},
        by_category={"bug_fix": {"total": 1, "passed": 1, "pass_rate": 1.0}},
        results=[result],
    )
