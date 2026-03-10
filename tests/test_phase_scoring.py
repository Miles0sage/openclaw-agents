"""Tests for phase_scoring.py — per-phase quality scoring (Process Reward Model lite)."""

import os
import pytest

os.environ.setdefault("GATEWAY_AUTH_TOKEN", "test")

from phase_scoring import (
    score_research, score_plan, score_execute, score_code_review,
    score_verify, score_deliver, score_all_phases, validate_phase_output,
    _check_read_before_edit,
)
from pipeline.models import PlanStep, ExecutionPlan


class TestScoreResearch:
    def test_skipped(self):
        result = score_research({"status": "skipped"}, "")
        assert result["score"] == 0.0

    def test_empty_text(self):
        result = score_research({"status": "done"}, "")
        assert result["score"] == 0.0

    def test_short_text(self):
        result = score_research({"status": "done"}, "Some brief research findings")
        assert result["score"] >= 0.3

    def test_rich_text(self):
        text = """## Research Findings
- Found relevant docs at https://example.com
- The module uses `def process_data()` pattern
```python
import os
```
""" + "x" * 200
        result = score_research({"status": "done"}, text)
        assert result["score"] >= 0.8

    def test_long_text_bonus(self):
        text = "Research finding. " * 20  # >200 chars
        result = score_research({"status": "done"}, text)
        assert result["score"] >= 0.5


class TestScorePlan:
    def test_skipped(self):
        result = score_plan({"status": "skipped"}, None)
        assert result["score"] == 0.0

    def test_no_steps(self):
        result = score_plan({"status": "done"}, None)
        assert result["score"] == 0.0

    def test_with_plan_object(self):
        plan = ExecutionPlan(
            job_id="test",
            agent="coder",
            steps=[
                PlanStep(0, "Read the file", tool_hints=["file_read"]),
                PlanStep(1, "Edit the file", tool_hints=["file_edit"]),
                PlanStep(2, "Run tests", tool_hints=["shell_execute"]),
            ]
        )
        result = score_plan({"status": "done"}, plan)
        assert result["score"] >= 0.7

    def test_phase_result_only(self):
        result = score_plan({"status": "done", "steps": 4}, None)
        assert result["score"] >= 0.5


class TestScoreExecute:
    def test_skipped(self):
        result = score_execute({"status": "skipped"}, [])
        assert result["score"] == 0.0

    def test_all_done(self):
        result = score_execute(
            {"status": "done", "steps_done": 3, "steps_failed": 0},
            [{"output": "ok"}, {"output": "ok"}, {"output": "ok"}]
        )
        assert result["score"] >= 0.8

    def test_partial_failure(self):
        result = score_execute(
            {"status": "partial", "steps_done": 2, "steps_failed": 1},
            [{"output": "ok"}, {"output": "ok"}, {"error": "fail"}]
        )
        assert 0.3 < result["score"] < 0.8


class TestScoreCodeReview:
    def test_passed(self):
        result = score_code_review({
            "passed": True,
            "summary": "Code looks good, all patterns followed.",
            "reviews": [{"agent": "reviewer1"}, {"agent": "reviewer2"}],
            "issues_found": 0,
        })
        assert result["score"] >= 0.8

    def test_failed(self):
        result = score_code_review(None)
        assert result["score"] == 0.0


class TestScoreVerify:
    def test_passed(self):
        result = score_verify({
            "status": "done",
            "verified": True,
            "checks": ["lint", "test", "build"],
            "test_output": "3 passed",
        })
        assert result["score"] >= 0.8

    def test_skipped(self):
        result = score_verify({"status": "skipped"})
        assert result["score"] == 0.0


class TestScoreDeliver:
    def test_delivered(self):
        result = score_deliver({
            "delivered": True,
            "summary": "Changes committed and pushed to main branch.",
            "commit_hash": "abc123",
            "next_steps": "Monitor production for errors",
        })
        assert result["score"] >= 0.8

    def test_missing(self):
        result = score_deliver(None)
        assert result["score"] == 0.0


class TestValidatePhaseOutput:
    def test_research_valid(self):
        result = validate_phase_output("research", "Here are my findings about the codebase")
        assert result["valid"] is True

    def test_research_none(self):
        result = validate_phase_output("research", None)
        assert result["valid"] is False

    def test_plan_valid(self):
        plan = ExecutionPlan(job_id="t", agent="a", steps=[PlanStep(0, "do thing")])
        result = validate_phase_output("plan", plan)
        assert result["valid"] is True

    def test_plan_no_steps(self):
        plan = ExecutionPlan(job_id="t", agent="a", steps=[])
        result = validate_phase_output("plan", plan)
        assert len(result["errors"]) > 0

    def test_unknown_phase(self):
        result = validate_phase_output("unknown_phase", "anything")
        assert result["valid"] is True


class TestScoreAllPhases:
    def test_aggregate(self):
        result = {
            "phases": {
                "research": {"status": "done", "length": 300},
                "execute": {"status": "done", "steps_done": 2, "steps_failed": 0},
                "deliver": {"delivered": True, "summary": "Done and shipped."},
            }
        }
        scores = score_all_phases(
            result,
            research_text="x" * 300,
            exec_results=[{"output": "ok"}, {"output": "ok"}],
        )
        assert scores["aggregate"] > 0
        assert scores["scored_phases"] == 3


class TestCheckReadBeforeEdit:
    def test_read_then_edit(self):
        steps = [
            PlanStep(0, "Read file", tool_hints=["file_read"]),
            PlanStep(1, "Edit file", tool_hints=["file_edit"]),
        ]
        assert _check_read_before_edit(steps) is True

    def test_edit_then_read(self):
        steps = [
            PlanStep(0, "Edit file", tool_hints=["file_edit"]),
            PlanStep(1, "Read file", tool_hints=["file_read"]),
        ]
        assert _check_read_before_edit(steps) is False

    def test_no_edit(self):
        steps = [PlanStep(0, "Run tests", tool_hints=["shell_execute"])]
        assert _check_read_before_edit(steps) is None
