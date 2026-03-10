"""Tests for tool_router.py — phase-gated tool dispatch and audit logging."""

import json
import os
import tempfile

import pytest

# Must set env before import
os.environ.setdefault("GATEWAY_AUTH_TOKEN", "test")

from tool_router import (
    ToolRegistry, PhaseViolationError, ToolExecutionError,
    PHASE_TOOLS, TOOL_RISK_LEVELS,
    _summarize_input, get_registry,
)


class TestPhaseTools:
    """Verify phase tool whitelists are consistent."""

    def test_research_is_read_only(self):
        write_tools = {"file_write", "file_edit", "shell_execute", "git_operations"}
        research_tools = set(PHASE_TOOLS["research"])
        assert not (research_tools & write_tools), "Research phase should not have write tools"

    def test_plan_is_read_only(self):
        write_tools = {"file_write", "file_edit", "shell_execute", "git_operations"}
        plan_tools = set(PHASE_TOOLS["plan"])
        assert not (plan_tools & write_tools), "Plan phase should not have write tools"

    def test_execute_has_write_tools(self):
        assert "file_write" in PHASE_TOOLS["execute"]
        assert "file_edit" in PHASE_TOOLS["execute"]
        assert "shell_execute" in PHASE_TOOLS["execute"]

    def test_all_phases_present(self):
        expected = {"research", "plan", "execute", "verify", "deliver"}
        assert set(PHASE_TOOLS.keys()) == expected

    def test_file_read_everywhere(self):
        for phase in ["research", "plan", "execute", "verify"]:
            assert "file_read" in PHASE_TOOLS[phase], f"file_read missing from {phase}"


class TestToolRiskLevels:
    """Verify tool risk classification."""

    def test_shell_is_high(self):
        assert TOOL_RISK_LEVELS["shell_execute"] == "high"

    def test_file_read_is_safe(self):
        assert TOOL_RISK_LEVELS["file_read"] == "safe"

    def test_file_write_is_medium(self):
        assert TOOL_RISK_LEVELS["file_write"] == "medium"

    def test_git_is_high(self):
        assert TOOL_RISK_LEVELS["git_operations"] == "high"


class TestToolRegistry:
    """Test ToolRegistry singleton and methods."""

    def test_singleton(self):
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_has_tools(self):
        r = get_registry()
        tools = r.list_tools()
        assert len(tools) > 0

    def test_get_tools_for_phase(self):
        r = get_registry()
        research_tools = r.get_tools_for_phase("research")
        tool_names = {t["name"] for t in research_tools}
        assert "file_read" in tool_names
        assert "file_write" not in tool_names

    def test_is_tool_allowed(self):
        r = get_registry()
        assert r.is_tool_allowed("file_read", "research") is True
        assert r.is_tool_allowed("file_write", "research") is False
        assert r.is_tool_allowed("file_write", "execute") is True

    def test_get_risk_level(self):
        r = get_registry()
        assert r.get_risk_level("shell_execute") == "high"
        assert r.get_risk_level("file_read") == "safe"
        assert r.get_risk_level("nonexistent_tool") == "medium"

    def test_get_tool_names_for_phase(self):
        r = get_registry()
        names = r.get_tool_names_for_phase("plan")
        assert isinstance(names, list)
        assert "file_read" in names


class TestSummarizeInput:
    """Test input summarization for audit logs."""

    def test_short_values(self):
        result = _summarize_input({"key": "value"})
        assert result == {"key": "value"}

    def test_truncates_long_values(self):
        long_val = "x" * 500
        result = _summarize_input({"key": long_val})
        assert len(result["key"]) == 200

    def test_empty_input(self):
        result = _summarize_input({})
        assert result == {}
