"""Tests for reflexion.py — self-improving agent memory."""

import json
import os
import tempfile

import pytest

os.environ.setdefault("GATEWAY_AUTH_TOKEN", "test")

from reflexion import (
    StructuredReflection,
    _extract_structured_insights,
    _extract_tags,
    format_reflections_for_prompt,
)


class TestStructuredReflection:
    def test_defaults(self):
        sr = StructuredReflection(job_id="j1", task="test", outcome="success")
        assert sr.confidence == 0.5
        assert sr.what_worked == []
        assert sr.what_failed == []
        assert sr.cost_usd == 0.0


class TestExtractStructuredInsights:
    def test_success_full_pipeline(self):
        run_result = {
            "job_id": "j1",
            "cost_usd": 0.005,
            "phases": {
                "research": {"status": "done", "length": 600},
                "plan": {"status": "done", "steps": 3},
                "execute": {"status": "done", "steps_done": 3, "steps_failed": 0},
                "verify": {"status": "done"},
                "deliver": {"delivered": True},
            },
            "guardrails": {
                "iterations": 15,
                "max_iterations": 50,
                "max_cost_usd": 2.0,
            },
        }
        job_data = {"task": "Fix the login button"}
        sr = _extract_structured_insights(run_result, job_data, "success")

        assert sr.outcome == "success"
        assert sr.phases_completed >= 4
        assert sr.confidence >= 0.8
        assert len(sr.what_worked) > 0

    def test_failed_budget(self):
        run_result = {
            "job_id": "j2",
            "cost_usd": 2.5,
            "error": "Budget exceeded: $2.50 > $2.00",
            "phases": {"research": {"status": "done", "length": 100}},
            "guardrails": {"iterations": 40, "max_iterations": 50, "max_cost_usd": 2.0},
        }
        sr = _extract_structured_insights(run_result, {"task": "big task"}, "failed")

        assert sr.error_type == "budget"
        assert sr.confidence < 0.5
        assert any("budget" in f.lower() for f in sr.what_failed)

    def test_failed_timeout(self):
        run_result = {
            "job_id": "j3",
            "cost_usd": 0.5,
            "error": "Timed out after 3600s",
            "phases": {},
            "guardrails": {},
        }
        sr = _extract_structured_insights(run_result, {"task": "slow task"}, "failed")
        assert sr.error_type == "timeout"

    def test_partial_execute(self):
        run_result = {
            "job_id": "j4",
            "cost_usd": 0.1,
            "phases": {
                "research": {"status": "done", "length": 200},
                "plan": {"status": "done", "steps": 2},
                "execute": {"status": "partial", "steps_done": 1, "steps_failed": 1},
            },
            "guardrails": {},
        }
        sr = _extract_structured_insights(run_result, {"task": "partial task"}, "partial")
        assert sr.confidence == 0.4
        assert sr.phases_completed >= 2

    def test_high_iteration_warning(self):
        run_result = {
            "job_id": "j5",
            "cost_usd": 0.3,
            "phases": {"execute": {"status": "done", "steps_done": 1}},
            "guardrails": {"iterations": 45, "max_iterations": 50, "max_cost_usd": 2.0},
        }
        sr = _extract_structured_insights(run_result, {"task": "iterative task"}, "success")
        assert any("iteration" in w.lower() for w in sr.time_wasted_on)


class TestExtractTags:
    def test_known_tags(self):
        tags = _extract_tags("Deploy the frontend to vercel with react")
        assert "deploy" in tags
        assert "frontend" in tags
        assert "vercel" in tags
        assert "react" in tags

    def test_unknown_words(self):
        tags = _extract_tags("something random here")
        assert len(tags) == 0

    def test_project_tags(self):
        tags = _extract_tags("Fix the openclaw pipeline bug")
        assert "openclaw" in tags
        assert "bug" in tags
        assert "fix" in tags


class TestFormatReflectionsForPrompt:
    def test_empty(self):
        assert format_reflections_for_prompt([]) == ""

    def test_simple_reflection(self):
        refs = [{
            "task": "Fix button color",
            "outcome": "success",
            "project": "barber",
            "learnings": ["Fixed CSS color property"],
        }]
        result = format_reflections_for_prompt(refs)
        assert "Past Experience" in result
        assert "SUCCESS" in result
        assert "Fix button color" in result

    def test_structured_reflection(self):
        refs = [{
            "task": "Deploy API endpoint",
            "outcome": "failed",
            "project": "openclaw",
            "duration_seconds": 120,
            "cost_usd": 0.05,
            "structured": {
                "what_worked": ["Research found correct API docs"],
                "what_failed": ["Deploy failed due to missing env var"],
                "suggested_improvements": ["Set env vars before deploy"],
                "missing_tools": ["env_check"],
                "time_wasted_on": ["Debugging missing config"],
            },
        }]
        result = format_reflections_for_prompt(refs)
        assert "FAILED" in result
        assert "What worked" in result
        assert "What failed" in result
        assert "Advice" in result
        assert "Missing tools" in result

    def test_avoid_repeating(self):
        result = format_reflections_for_prompt([{
            "task": "test",
            "outcome": "failed",
            "learnings": ["it broke"],
        }])
        assert "Avoid repeating past failures" in result
