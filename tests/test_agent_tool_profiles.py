"""Tests for agent_tool_profiles.py — per-agent tool allowlists."""

import os
import pytest

os.environ.setdefault("GATEWAY_AUTH_TOKEN", "test")

from agent_tool_profiles import (
    AGENT_TOOL_PROFILES,
    get_tools_for_agent,
    is_tool_allowed,
    get_available_agents,
)


class TestAgentProfiles:
    def test_all_agents_have_file_read(self):
        for agent, tools in AGENT_TOOL_PROFILES.items():
            assert "file_read" in tools, f"{agent} missing file_read"

    def test_research_agent_no_write(self):
        tools = AGENT_TOOL_PROFILES["research_agent"]
        assert "file_write" not in tools
        assert "file_edit" not in tools
        assert "shell_execute" not in tools

    def test_coder_has_write_tools(self):
        tools = AGENT_TOOL_PROFILES["coder_agent"]
        assert "file_write" in tools
        assert "file_edit" in tools
        assert "shell_execute" in tools

    def test_code_reviewer_read_only(self):
        tools = AGENT_TOOL_PROFILES["code_reviewer"]
        assert "file_read" in tools
        assert "file_write" not in tools
        assert "file_edit" not in tools

    def test_hacker_limited_tools(self):
        tools = AGENT_TOOL_PROFILES["hacker_agent"]
        assert "file_write" not in tools
        assert "vercel_deploy" not in tools


class TestGetToolsForAgent:
    def test_known_agent(self):
        tools = get_tools_for_agent("coder_agent")
        assert isinstance(tools, set)
        assert len(tools) > 0

    def test_unknown_agent(self):
        result = get_tools_for_agent("nonexistent_agent")
        assert result is None  # unrestricted


class TestIsToolAllowed:
    def test_allowed(self):
        assert is_tool_allowed("coder_agent", "file_write") is True

    def test_blocked(self):
        assert is_tool_allowed("research_agent", "file_write") is False

    def test_unknown_agent_unrestricted(self):
        assert is_tool_allowed("unknown_agent", "anything") is True


class TestGetAvailableAgents:
    def test_returns_list(self):
        agents = get_available_agents()
        assert isinstance(agents, list)
        assert len(agents) >= 9
        assert "coder_agent" in agents
        assert "hacker_agent" in agents
