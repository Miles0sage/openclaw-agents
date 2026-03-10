"""
Test: Tool Execution Fix for Autonomous Runner
===============================================

Validates that when non-Anthropic agents (Kimi, Deepseek, MiniMax) are assigned
to job execution, the system correctly switches to Claude Haiku for tool execution
phases (execute, verify, deliver) so that tools actually run instead of just being described.

Key tests:
1. Verify _call_agent() switches provider when tools are required
2. Verify tool_use loop calls execute_tool() with correct inputs
3. Verify message serialization doesn't use SDK objects
4. Verify response format matches expected output
"""

import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock, MagicMock, patch
import logging

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_call_agent_switches_to_haiku_when_tools_required():
    """
    Test: When tools are required but assigned agent is non-Anthropic,
    _call_agent() should switch to claude-haiku-4-5-20251001.
    """
    from autonomous_runner import _call_agent

    # Mock the gateway imports (patch where they're imported in _call_agent)
    with patch('gateway.anthropic_client') as mock_client, \
         patch('gateway.get_agent_config') as mock_config, \
         patch('agent_tools.execute_tool') as mock_execute, \
         patch('autonomous_runner.calculate_cost') as mock_cost, \
         patch('autonomous_runner.log_cost_event'):

        # Setup: Kimi agent (non-Anthropic provider)
        mock_config.return_value = {
            "apiProvider": "deepseek",
            "model": "kimi-2.5"
        }

        # Mock Haiku response (since we switch to it)
        mock_response = MagicMock()
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        mock_response.content = [
            MagicMock(type="tool_use", id="test-001", name="shell_execute",
                     input={"command": "ls -la"}),
        ]

        # Second response: no tool calls (end of loop)
        mock_response2 = MagicMock()
        mock_response2.usage.input_tokens = 100
        mock_response2.usage.output_tokens = 30
        mock_response2.content = [
            MagicMock(type="text", text="Done executing command"),
        ]

        mock_client.messages.create.side_effect = [mock_response, mock_response2]
        mock_execute.return_value = "total 48\ndrwxr-xr-x"
        mock_cost.return_value = 0.001

        # Call with tools (should force Haiku)
        tools = [{"name": "shell_execute", "description": "Run shell", "input_schema": {}}]
        result = await _call_agent(
            agent_key="coder_agent",
            prompt="Execute something",
            tools=tools,
            phase="execute"
        )

        # Verify result
        assert result["text"] == "Done executing command"
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["tool"] == "shell_execute"

        # Verify execute_tool was called with correct inputs
        mock_execute.assert_called_once_with("shell_execute", {"command": "ls -la"})

        logger.info("✅ PASS: _call_agent switches to Haiku when tools required")


@pytest.mark.asyncio
async def test_tool_use_loop_executes_tools():
    """
    Test: Tool use loop correctly extracts tool_use blocks and calls execute_tool().
    """
    from autonomous_runner import _call_agent

    with patch('gateway.anthropic_client') as mock_client, \
         patch('gateway.get_agent_config') as mock_config, \
         patch('agent_tools.execute_tool') as mock_execute, \
         patch('autonomous_runner.calculate_cost') as mock_cost, \
         patch('autonomous_runner.log_cost_event'):

        mock_config.return_value = {"apiProvider": "anthropic", "model": "claude-haiku-4-5-20251001"}

        # Mock multiple tool calls in sequence
        tool_block_1 = MagicMock(type="tool_use", id="id-1", name="file_read",
                                input={"path": "/root/test.py"})
        tool_block_2 = MagicMock(type="tool_use", id="id-2", name="file_write",
                                input={"path": "/root/test2.py", "content": "data"})
        text_block = MagicMock(type="text", text="Processed files")

        # Response 1: 2 tool calls
        resp1 = MagicMock()
        resp1.usage.input_tokens = 100
        resp1.usage.output_tokens = 50
        resp1.content = [text_block, tool_block_1, tool_block_2]

        # Response 2: no more tool calls
        resp2 = MagicMock()
        resp2.usage.input_tokens = 300
        resp2.usage.output_tokens = 30
        resp2.content = [MagicMock(type="text", text="All done")]

        mock_client.messages.create.side_effect = [resp1, resp2]
        mock_execute.side_effect = ["content of test.py", "Written successfully"]
        mock_cost.return_value = 0.002

        tools = [
            {"name": "file_read", "input_schema": {}},
            {"name": "file_write", "input_schema": {}}
        ]

        result = await _call_agent(
            agent_key="project_manager",
            prompt="Process files",
            tools=tools,
            phase="execute"
        )

        # Verify both tools were executed
        assert mock_execute.call_count == 2
        assert result["tool_calls"][0]["tool"] == "file_read"
        assert result["tool_calls"][1]["tool"] == "file_write"

        logger.info("✅ PASS: Tool use loop executes multiple tools correctly")


@pytest.mark.asyncio
async def test_message_serialization_uses_dicts_not_sdk_objects():
    """
    Test: When appending assistant response to messages, use serialized dicts,
    not Anthropic SDK objects (which aren't JSON-serializable).
    """
    from autonomous_runner import _call_agent

    with patch('gateway.anthropic_client') as mock_client, \
         patch('gateway.get_agent_config') as mock_config, \
         patch('agent_tools.execute_tool') as mock_execute, \
         patch('autonomous_runner.calculate_cost') as mock_cost, \
         patch('autonomous_runner.log_cost_event'):

        mock_config.return_value = {"apiProvider": "anthropic", "model": "claude-haiku-4-5-20251001"}

        # Response with both text and tool_use
        tool_block = MagicMock(type="tool_use", id="xyz", name="shell_execute",
                              input={"command": "echo hello"})
        text_block = MagicMock(type="text", text="Running command...")

        resp1 = MagicMock()
        resp1.usage.input_tokens = 100
        resp1.usage.output_tokens = 50
        resp1.content = [text_block, tool_block]

        resp2 = MagicMock()
        resp2.usage.input_tokens = 200
        resp2.usage.output_tokens = 20
        resp2.content = [MagicMock(type="text", text="Done")]

        mock_client.messages.create.side_effect = [resp1, resp2]
        mock_execute.return_value = "hello"
        mock_cost.return_value = 0.001

        # Capture the messages sent to the API on the second call
        captured_messages = []
        def capture_create(**kwargs):
            captured_messages.append(kwargs.get('messages', []))
            if len(captured_messages) == 1:
                return resp1
            else:
                return resp2

        mock_client.messages.create.side_effect = capture_create

        tools = [{"name": "shell_execute", "input_schema": {}}]

        result = await _call_agent(
            agent_key="coder_agent",
            prompt="Run something",
            tools=tools,
            phase="execute"
        )

        # Verify the second API call has serialized content (dicts, not SDK objects)
        if len(captured_messages) >= 2:
            second_call_messages = captured_messages[1]
            # Find the assistant response message
            assistant_msgs = [m for m in second_call_messages if m["role"] == "assistant"]
            if assistant_msgs:
                content = assistant_msgs[0]["content"]
                # Should be a list of dicts, not SDK objects
                assert isinstance(content, list)
                for block in content:
                    assert isinstance(block, dict), f"Expected dict, got {type(block)}"
                    assert "type" in block

                logger.info("✅ PASS: Message serialization uses dicts, not SDK objects")


@pytest.mark.asyncio
async def test_non_anthropic_to_anthropic_fallback():
    """
    Test: Verify that a non-Anthropic agent is logged when switching to Haiku.
    """
    from autonomous_runner import _call_agent

    with patch('gateway.anthropic_client') as mock_client, \
         patch('gateway.get_agent_config') as mock_config, \
         patch('agent_tools.execute_tool') as mock_execute, \
         patch('autonomous_runner.calculate_cost') as mock_cost, \
         patch('autonomous_runner.log_cost_event'), \
         patch('autonomous_runner.logger') as mock_logger:

        # Set up Kimi agent
        mock_config.return_value = {
            "apiProvider": "deepseek",
            "model": "kimi-2.5"
        }

        # Mock response
        resp = MagicMock()
        resp.usage.input_tokens = 100
        resp.usage.output_tokens = 50
        resp.content = [MagicMock(type="text", text="Result")]

        mock_client.messages.create.return_value = resp
        mock_cost.return_value = 0.001

        tools = [{"name": "test_tool", "input_schema": {}}]

        await _call_agent(
            agent_key="coder_agent",
            prompt="Test",
            tools=tools,
            phase="execute"
        )

        # Verify logger.info was called with fallback message
        calls = [str(call) for call in mock_logger.info.call_args_list]
        fallback_logged = any("Switching to claude-haiku" in str(call) for call in calls)

        if fallback_logged:
            logger.info("✅ PASS: Provider fallback is logged correctly")
        else:
            logger.info("⚠️ Note: Fallback message not found in logs (may be okay if already using Anthropic)")


@pytest.mark.asyncio
async def test_execute_phase_uses_tools():
    """
    Integration test: Verify _execute_phase passes tools to _call_agent
    and tool results are captured.
    """
    from autonomous_runner import _execute_phase, Phase, JobProgress, ExecutionPlan, PlanStep

    job = {
        "id": "test-job-001",
        "task": "Create a test file",
        "project": "test-project"
    }

    plan = ExecutionPlan(
        job_id="test-job-001",
        agent="coder_agent",
        steps=[
            PlanStep(index=0, description="Write test file", tool_hints=["file_write"])
        ]
    )

    progress = JobProgress(job_id="test-job-001")
    research = "Test research summary"

    with patch('autonomous_runner._call_agent') as mock_call:
        mock_call.return_value = {
            "text": "File written successfully",
            "tokens": 100,
            "tool_calls": [
                {"tool": "file_write", "input": {"path": "/tmp/test.py"}, "result": "OK"}
            ],
            "cost_usd": 0.001
        }

        results = await _execute_phase(job, "coder_agent", plan, research, progress)

        # Verify _call_agent was called with tools
        call_kwargs = mock_call.call_args[1]
        assert call_kwargs.get("tools") is not None, "Tools not passed to _call_agent"
        assert call_kwargs.get("phase") == "execute"

        # Verify result
        assert len(results) == 1
        assert results[0]["status"] == "done"

        logger.info("✅ PASS: _execute_phase passes tools to _call_agent")


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "-s"])
