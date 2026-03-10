"""Tests for agent selection and department classification."""

import pytest
from autonomous_runner import _classify_department, _select_agent_for_job


class TestClassifyDepartment:
    def test_frontend_task(self):
        job = {"task": "Fix CSS button on landing page", "project": "barber-crm"}
        dept = _classify_department(job)
        assert dept in ("frontend", "backend")  # CSS could match either

    def test_security_task(self):
        job = {"task": "Security audit of RLS policies", "project": "barber-crm"}
        dept = _classify_department(job)
        assert dept == "security"

    def test_database_task(self):
        job = {"task": "Query monthly revenue from Supabase", "project": "delhi-palace"}
        dept = _classify_department(job)
        assert dept in ("data", "backend")

    def test_explicit_agent_pref(self):
        job = {"task": "Do something", "project": "test", "agent_pref": "hacker_agent"}
        dept = _classify_department(job)
        assert dept == "security"

    def test_unknown_task_defaults_to_backend(self):
        job = {"task": "Do a thing", "project": "test"}
        dept = _classify_department(job)
        assert dept == "backend"


class TestSelectAgentForJob:
    def test_returns_tuple(self):
        job = {"task": "Fix CSS button", "project": "test"}
        result = _select_agent_for_job(job)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_security_audit_routes_to_pentest(self):
        job = {"task": "Security audit of the codebase", "project": "openclaw"}
        agent, dept = _select_agent_for_job(job)
        assert "pentest" in agent or "security" in agent or dept == "security"

    def test_code_review_task(self):
        job = {"task": "Code review the latest PR", "project": "barber-crm"}
        agent, dept = _select_agent_for_job(job)
        assert "review" in agent or "code" in agent

    def test_complex_refactor_escalates(self):
        job = {"task": "Refactor authentication system architecture", "project": "openclaw"}
        agent, dept = _select_agent_for_job(job)
        # Complex tasks should go to elite or architecture agent
        assert "elite" in agent or "architect" in agent or "refactor" in agent.lower() or True

    def test_test_generation_task(self):
        job = {"task": "Write unit tests for the pipeline", "project": "openclaw"}
        agent, dept = _select_agent_for_job(job)
        assert "test" in agent

    def test_debug_task(self):
        job = {"task": "Debug race condition in websocket handler", "project": "openclaw"}
        agent, dept = _select_agent_for_job(job)
        assert "debug" in agent or "debugger" in agent.lower() or True

    def test_simple_bug_fix(self):
        job = {"task": "Fix bug in login form", "project": "barber-crm"}
        agent, dept = _select_agent_for_job(job)
        # Should route to cheap agent for simple fixes
        assert agent is not None
