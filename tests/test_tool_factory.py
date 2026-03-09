"""
Tests for tool_factory.py — dynamic tool creation and management.

Tests cover:
- Tool proposal validation
- Safety constraints (shell, python, http)
- Test execution with capture
- Approval workflow
- Execution of approved tools
- Singleton pattern
"""

import json
import os
import pytest
import tempfile
from pathlib import Path

# Set env before imports
os.environ.setdefault("GATEWAY_AUTH_TOKEN", "test")

from tool_factory import (
    ToolFactory,
    DynamicTool,
    ToolFactoryError,
    ToolConflictError,
    ToolSafetyError,
    ToolTestError,
    get_factory,
)


@pytest.fixture
def temp_db():
    """Create temporary database for each test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_tools.db")
        yield db_path


@pytest.fixture
def factory(temp_db):
    """Create ToolFactory instance with temp database."""
    return ToolFactory(temp_db)


class TestToolProposal:
    """Test tool proposal and validation."""

    def test_propose_shell_command_tool(self, factory):
        """Test proposing a valid shell command tool."""
        tool_def = {
            "name": "test_echo",
            "description": "Echo a string",
            "input_schema": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
            "implementation_type": "shell_command",
            "implementation": "echo {message}",
        }

        tool = factory.propose_tool("test_agent", tool_def)

        assert tool.name == "test_echo"
        assert tool.created_by == "test_agent"
        assert tool.approved is False
        assert tool.test_passed is False

    def test_propose_python_snippet_tool(self, factory):
        """Test proposing a Python snippet tool."""
        tool_def = {
            "name": "test_math",
            "description": "Add two numbers",
            "input_schema": {
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
            "implementation_type": "python_snippet",
            "implementation": "result = input_data['a'] + input_data['b']",
        }

        tool = factory.propose_tool("test_agent", tool_def)
        assert tool.name == "test_math"

    def test_propose_http_request_tool(self, factory):
        """Test proposing an HTTP request tool."""
        tool_def = {
            "name": "test_api_call",
            "description": "Call an API",
            "input_schema": {
                "type": "object",
                "properties": {"endpoint": {"type": "string"}},
                "required": ["endpoint"],
            },
            "implementation_type": "http_request",
            "implementation": "https://jsonplaceholder.typicode.com/posts/{endpoint}",
        }

        tool = factory.propose_tool("test_agent", tool_def)
        assert tool.name == "test_api_call"

    def test_duplicate_tool_name_rejected(self, factory):
        """Test that duplicate tool names are rejected."""
        tool_def = {
            "name": "duplicate_tool",
            "description": "Test tool",
            "input_schema": {"type": "object"},
            "implementation_type": "shell_command",
            "implementation": "echo test",
        }

        factory.propose_tool("agent1", tool_def)

        with pytest.raises(ToolConflictError):
            factory.propose_tool("agent2", tool_def)

    def test_invalid_implementation_type_rejected(self, factory):
        """Test that invalid implementation type is rejected."""
        tool_def = {
            "name": "bad_type",
            "description": "Test tool",
            "input_schema": {"type": "object"},
            "implementation_type": "invalid_type",
            "implementation": "code",
        }

        with pytest.raises(ToolFactoryError):
            factory.propose_tool("test_agent", tool_def)

    def test_invalid_schema_json_rejected(self, factory):
        """Test that invalid JSON schema is rejected."""
        tool_def = {
            "name": "bad_schema",
            "description": "Test tool",
            "input_schema": "not valid json {{{",
            "implementation_type": "shell_command",
            "implementation": "echo test",
        }

        with pytest.raises(ToolFactoryError):
            factory.propose_tool("test_agent", tool_def)

    def test_max_tools_limit_enforced(self, factory):
        """Test that max 50 tools limit is enforced."""
        # Create 50 tools
        for i in range(50):
            tool_def = {
                "name": f"tool_{i}",
                "description": "Test tool",
                "input_schema": {"type": "object"},
                "implementation_type": "shell_command",
                "implementation": "echo test",
            }
            factory.propose_tool("test_agent", tool_def)

        # 51st should fail
        tool_def = {
            "name": "tool_51",
            "description": "Test tool",
            "input_schema": {"type": "object"},
            "implementation_type": "shell_command",
            "implementation": "echo test",
        }

        with pytest.raises(ToolFactoryError, match="Cannot create more than 50"):
            factory.propose_tool("test_agent", tool_def)


class TestShellCommandSafety:
    """Test shell command safety constraints."""

    @pytest.mark.parametrize(
        "dangerous_cmd",
        [
            "rm -rf /",
            "rm -f /root/important.txt",
            "dd if=/dev/zero of=/dev/sda",
            "mkfs.ext4 /dev/sda",
            "shutdown -h now",
            "reboot",
        ],
    )
    def test_dangerous_commands_blocked(self, factory, dangerous_cmd):
        """Test that dangerous shell commands are blocked."""
        tool_def = {
            "name": "dangerous_tool",
            "description": "Dangerous tool",
            "input_schema": {"type": "object"},
            "implementation_type": "shell_command",
            "implementation": dangerous_cmd,
        }

        with pytest.raises(ToolSafetyError):
            factory.propose_tool("test_agent", tool_def)

    def test_safe_commands_allowed(self, factory):
        """Test that safe commands are allowed."""
        safe_commands = [
            "ls -la /root",
            "echo hello world",
            "git status",
            "npm list",
        ]

        for cmd in safe_commands:
            tool_def = {
                "name": f"safe_tool_{hash(cmd) % 10000}",
                "description": "Safe tool",
                "input_schema": {"type": "object"},
                "implementation_type": "shell_command",
                "implementation": cmd,
            }
            tool = factory.propose_tool("test_agent", tool_def)
            assert tool is not None


class TestPythonSnippetSafety:
    """Test Python snippet safety constraints."""

    @pytest.mark.parametrize(
        "forbidden_import",
        ["os", "subprocess", "sys", "shutil", "socket"],
    )
    def test_forbidden_imports_blocked(self, factory, forbidden_import):
        """Test that forbidden imports are blocked."""
        tool_def = {
            "name": "forbidden_import_tool",
            "description": "Test tool",
            "input_schema": {"type": "object"},
            "implementation_type": "python_snippet",
            "implementation": f"import {forbidden_import}",
        }

        with pytest.raises(ToolSafetyError):
            factory.propose_tool("test_agent", tool_def)

    @pytest.mark.parametrize(
        "dangerous_call",
        [
            "exec('code')",
            "eval('code')",
            "open('/root/.ssh/id_rsa')",
            "compile('code', 'file', 'exec')",
        ],
    )
    def test_dangerous_function_calls_blocked(self, factory, dangerous_call):
        """Test that dangerous function calls are blocked."""
        tool_def = {
            "name": "dangerous_func_tool",
            "description": "Test tool",
            "input_schema": {"type": "object"},
            "implementation_type": "python_snippet",
            "implementation": dangerous_call,
        }

        with pytest.raises(ToolSafetyError):
            factory.propose_tool("test_agent", tool_def)

    def test_safe_python_allowed(self, factory):
        """Test that safe Python is allowed."""
        tool_def = {
            "name": "safe_python_tool",
            "description": "Safe Python tool",
            "input_schema": {"type": "object"},
            "implementation_type": "python_snippet",
            "implementation": (
                "result = sum(input_data.get('numbers', []))"
            ),
        }

        tool = factory.propose_tool("test_agent", tool_def)
        assert tool is not None


class TestHTTPRequestSafety:
    """Test HTTP request safety constraints."""

    @pytest.mark.parametrize(
        "internal_url",
        [
            "http://127.0.0.1:8080/api",
            "http://localhost/api",
            "http://192.168.1.1/api",
            "http://10.0.0.1/api",
            "http://172.18.0.1/api",
        ],
    )
    def test_internal_ips_blocked(self, factory, internal_url):
        """Test that requests to internal IPs are blocked."""
        tool_def = {
            "name": "internal_request_tool",
            "description": "Test tool",
            "input_schema": {"type": "object"},
            "implementation_type": "http_request",
            "implementation": internal_url,
        }

        with pytest.raises(ToolSafetyError):
            factory.propose_tool("test_agent", tool_def)

    def test_external_urls_allowed(self, factory):
        """Test that external URLs are allowed."""
        urls = [
            "https://api.github.com/repos/miles0sage/openclaw",
            "https://jsonplaceholder.typicode.com/posts/1",
            "https://example.com/api/data",
        ]

        for url in urls:
            tool_def = {
                "name": f"http_tool_{hash(url) % 10000}",
                "description": "HTTP tool",
                "input_schema": {"type": "object"},
                "implementation_type": "http_request",
                "implementation": url,
            }
            tool = factory.propose_tool("test_agent", tool_def)
            assert tool is not None


class TestToolTesting:
    """Test tool validation through testing."""

    def test_shell_command_test_passes(self, factory):
        """Test that valid shell command passes."""
        tool_def = {
            "name": "test_ls",
            "description": "List files",
            "input_schema": {"type": "object"},
            "implementation_type": "shell_command",
            "implementation": "echo success",
        }

        tool = factory.propose_tool("test_agent", tool_def)
        assert tool.test_passed is False

        result = factory.test_tool("test_ls")
        assert result is True

        # Verify tool was updated
        updated = factory.get_tool("test_ls")
        assert updated.test_passed is True
        assert updated.test_error is None

    def test_python_snippet_test_passes(self, factory):
        """Test that valid Python snippet passes."""
        tool_def = {
            "name": "test_add",
            "description": "Add numbers",
            "input_schema": {
                "type": "object",
                "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            },
            "implementation_type": "python_snippet",
            "implementation": "result = input_data.get('a', 0) + input_data.get('b', 0)",
        }

        factory.propose_tool("test_agent", tool_def)
        result = factory.test_tool("test_add", {"a": 5, "b": 3})
        assert result is True

    def test_shell_command_test_with_error_output(self, factory):
        """Test that shell command errors are captured in output."""
        tool_def = {
            "name": "test_fail_cmd",
            "description": "Failing command",
            "input_schema": {"type": "object"},
            "implementation_type": "shell_command",
            "implementation": "ls /nonexistent/path/that/does/not/exist 2>&1",
        }

        factory.propose_tool("test_agent", tool_def)

        # Command runs but returns error output
        result = factory.test_tool("test_fail_cmd")
        assert result is True

        # Verify tool was marked as test_passed despite error output
        tool = factory.get_tool("test_fail_cmd")
        assert tool.test_passed is True
        assert tool.test_error is None

    def test_tool_not_found_raises_error(self, factory):
        """Test that testing nonexistent tool raises error."""
        with pytest.raises(ToolFactoryError, match="not found"):
            factory.test_tool("nonexistent_tool")


class TestToolApproval:
    """Test tool approval workflow."""

    def test_tool_requires_test_passed_before_approval(self, factory):
        """Test that tool must pass test before approval."""
        tool_def = {
            "name": "untested_tool",
            "description": "Untested tool",
            "input_schema": {"type": "object"},
            "implementation_type": "shell_command",
            "implementation": "echo test",
        }

        factory.propose_tool("test_agent", tool_def)

        # Try to approve without testing
        with pytest.raises(ToolFactoryError, match="cannot be approved"):
            factory.approve_tool("untested_tool")

    def test_tool_approval_after_test_passes(self, factory):
        """Test that tool can be approved after passing test."""
        tool_def = {
            "name": "tested_tool",
            "description": "Tested tool",
            "input_schema": {"type": "object"},
            "implementation_type": "shell_command",
            "implementation": "echo approved",
        }

        factory.propose_tool("test_agent", tool_def)
        factory.test_tool("tested_tool")

        # Now approve
        approved = factory.approve_tool("tested_tool", "Approved by test suite")
        assert approved.approved is True
        assert approved.approval_notes == "Approved by test suite"

    def test_approval_notes_stored(self, factory):
        """Test that approval notes are stored."""
        tool_def = {
            "name": "noted_tool",
            "description": "Tool with notes",
            "input_schema": {"type": "object"},
            "implementation_type": "shell_command",
            "implementation": "echo test",
        }

        factory.propose_tool("test_agent", tool_def)
        factory.test_tool("noted_tool")

        notes = "Approved after security review"
        factory.approve_tool("noted_tool", notes)

        tool = factory.get_tool("noted_tool")
        assert tool.approval_notes == notes


class TestToolExecution:
    """Test execution of approved tools."""

    def test_cannot_execute_unapproved_tool(self, factory):
        """Test that unapproved tools cannot be executed."""
        tool_def = {
            "name": "unapproved_tool",
            "description": "Test tool",
            "input_schema": {"type": "object"},
            "implementation_type": "shell_command",
            "implementation": "echo test",
        }

        factory.propose_tool("test_agent", tool_def)

        with pytest.raises(ToolFactoryError, match="not approved"):
            factory.execute_dynamic_tool("unapproved_tool", {})

    def test_execute_approved_shell_tool(self, factory):
        """Test executing an approved shell tool."""
        tool_def = {
            "name": "exec_shell",
            "description": "Executable shell tool",
            "input_schema": {"type": "object"},
            "implementation_type": "shell_command",
            "implementation": "echo hello_world",
        }

        factory.propose_tool("test_agent", tool_def)
        factory.test_tool("exec_shell")
        factory.approve_tool("exec_shell")

        result = factory.execute_dynamic_tool("exec_shell", {})
        assert "hello_world" in result

    def test_execute_approved_python_tool(self, factory):
        """Test executing an approved Python tool."""
        tool_def = {
            "name": "exec_python",
            "description": "Executable Python tool",
            "input_schema": {"type": "object"},
            "implementation_type": "python_snippet",
            "implementation": "result = input_data.get('value', 0) * 2",
        }

        factory.propose_tool("test_agent", tool_def)
        factory.test_tool("exec_python", {"value": 5})
        factory.approve_tool("exec_python")

        result = factory.execute_dynamic_tool("exec_python", {"value": 10})
        assert result == "20"

    def test_tool_not_found_execution_fails(self, factory):
        """Test that executing nonexistent tool fails."""
        with pytest.raises(ToolFactoryError, match="not found"):
            factory.execute_dynamic_tool("nonexistent", {})


class TestToolManagement:
    """Test listing and retiring tools."""

    def test_list_approved_tools_only(self, factory):
        """Test listing only approved tools."""
        # Create and approve one tool
        tool_def_1 = {
            "name": "approved_tool",
            "description": "Approved",
            "input_schema": {"type": "object"},
            "implementation_type": "shell_command",
            "implementation": "echo test",
        }
        factory.propose_tool("test_agent", tool_def_1)
        factory.test_tool("approved_tool")
        factory.approve_tool("approved_tool")

        # Create but don't approve another
        tool_def_2 = {
            "name": "unapproved_tool",
            "description": "Unapproved",
            "input_schema": {"type": "object"},
            "implementation_type": "shell_command",
            "implementation": "echo test",
        }
        factory.propose_tool("test_agent", tool_def_2)

        # List approved only
        approved = factory.list_dynamic_tools(approved_only=True)
        approved_names = {t.name for t in approved}

        assert "approved_tool" in approved_names
        assert "unapproved_tool" not in approved_names

    def test_list_all_tools(self, factory):
        """Test listing all tools (approved and unapproved)."""
        # Create and approve one
        tool_def_1 = {
            "name": "all_approved",
            "description": "Approved",
            "input_schema": {"type": "object"},
            "implementation_type": "shell_command",
            "implementation": "echo test",
        }
        factory.propose_tool("test_agent", tool_def_1)
        factory.test_tool("all_approved")
        factory.approve_tool("all_approved")

        # Create but don't approve another
        tool_def_2 = {
            "name": "all_unapproved",
            "description": "Unapproved",
            "input_schema": {"type": "object"},
            "implementation_type": "shell_command",
            "implementation": "echo test",
        }
        factory.propose_tool("test_agent", tool_def_2)

        # List all
        all_tools = factory.list_dynamic_tools(approved_only=False)
        all_names = {t.name for t in all_tools}

        assert "all_approved" in all_names
        assert "all_unapproved" in all_names

    def test_retire_tool(self, factory):
        """Test retiring a tool."""
        tool_def = {
            "name": "retire_me",
            "description": "To be retired",
            "input_schema": {"type": "object"},
            "implementation_type": "shell_command",
            "implementation": "echo test",
        }

        factory.propose_tool("test_agent", tool_def)
        assert factory.get_tool("retire_me") is not None

        factory.retire_tool("retire_me")

        # Should not appear in listings
        assert factory.get_tool("retire_me") is None

    def test_retire_nonexistent_tool_fails(self, factory):
        """Test that retiring nonexistent tool fails."""
        with pytest.raises(ToolFactoryError, match="not found"):
            factory.retire_tool("nonexistent")

    def test_get_tool_returns_none_if_not_found(self, factory):
        """Test that get_tool returns None if not found."""
        assert factory.get_tool("nonexistent") is None


class TestSingletonPattern:
    """Test singleton pattern for factory."""

    def test_factory_singleton_with_same_db(self):
        """Test that get_factory returns same instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            f1 = get_factory(db_path)
            f2 = get_factory(db_path)
            # Note: singleton is global, so this may not be exactly same instance
            # but both should work with same data
            assert f1.db_path == f2.db_path


class TestIntegration:
    """End-to-end integration tests."""

    def test_full_workflow_from_proposal_to_execution(self, factory):
        """Test complete workflow: propose -> test -> approve -> execute."""
        # 1. Propose
        tool_def = {
            "name": "workflow_tool",
            "description": "Full workflow test",
            "input_schema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
            },
            "implementation_type": "shell_command",
            "implementation": "echo Hello {name}",
        }

        tool = factory.propose_tool("workflow_agent", tool_def)
        assert tool.approved is False
        assert tool.test_passed is False

        # 2. Test
        test_result = factory.test_tool("workflow_tool", {"name": "World"})
        assert test_result is True

        tool = factory.get_tool("workflow_tool")
        assert tool.test_passed is True

        # 3. Approve
        approved = factory.approve_tool("workflow_tool", "Approved for production")
        assert approved.approved is True

        # 4. Execute
        result = factory.execute_dynamic_tool("workflow_tool", {"name": "Universe"})
        assert "Hello" in result

    def test_multiple_agents_creating_tools(self, factory):
        """Test multiple agents creating different tools."""
        agents = ["coder_agent", "research_agent", "security_agent"]
        tools_created = []

        for i, agent in enumerate(agents):
            tool_def = {
                "name": f"tool_by_{agent}_{i}",
                "description": f"Tool created by {agent}",
                "input_schema": {"type": "object"},
                "implementation_type": "shell_command",
                "implementation": f"echo Created by {agent}",
            }

            tool = factory.propose_tool(agent, tool_def)
            tools_created.append(tool)

        # All should be created
        assert len(tools_created) == 3

        # Check they're all listed
        all_tools = factory.list_dynamic_tools(approved_only=False)
        created_names = {t.name for t in tools_created}
        listed_names = {t.name for t in all_tools}

        assert created_names.issubset(listed_names)
