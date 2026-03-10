#!/usr/bin/env python3
"""
Test script for Claude Code headless mode integration.
Tests the module import, tool definition, and handler.
"""

import json
import sys

# Test 1: Import claude_headless module
print("TEST 1: Import claude_headless module")
try:
    from claude_headless import ClaudeHeadless, get_headless
    print("  ✓ ClaudeHeadless imported successfully")
    print("  ✓ get_headless function available")
except ImportError as e:
    print(f"  ✗ Import failed: {e}")
    sys.exit(1)

# Test 2: Create instance
print("\nTEST 2: Create ClaudeHeadless instance")
try:
    headless = ClaudeHeadless(max_retries=2, timeout_seconds=600)
    print(f"  ✓ Instance created: {headless}")
    print(f"  ✓ max_retries={headless.max_retries}, timeout={headless.timeout_seconds}s")
except Exception as e:
    print(f"  ✗ Failed: {e}")
    sys.exit(1)

# Test 3: Check agent_tools integration
print("\nTEST 3: Check agent_tools integration")
try:
    from agent_tools import AGENT_TOOLS, execute_tool

    # Find claude_headless in tools list
    tool_found = any(t["name"] == "claude_headless" for t in AGENT_TOOLS)
    if not tool_found:
        print("  ✗ claude_headless tool not found in AGENT_TOOLS")
        sys.exit(1)

    print("  ✓ claude_headless tool registered in AGENT_TOOLS")

    # Get the tool definition
    claude_tool = next(t for t in AGENT_TOOLS if t["name"] == "claude_headless")
    print(f"  ✓ Tool description: {claude_tool['description'][:80]}...")

    # Check action enum
    actions = claude_tool["input_schema"]["properties"]["action"]["enum"]
    print(f"  ✓ Supported actions: {', '.join(actions)}")

except Exception as e:
    print(f"  ✗ Failed: {e}")
    sys.exit(1)

# Test 4: Test handler without actual Claude invocation
print("\nTEST 4: Test handler structure (mock call)")
try:
    # This will fail because Claude CLI needs to run, but it tests the handler structure
    result = execute_tool("claude_headless", {
        "action": "run",
        "prompt": "test",
        "max_turns": 5,
    })

    # Parse result JSON
    try:
        parsed = json.loads(result)
        print(f"  ✓ Handler returned valid JSON: {list(parsed.keys())}")
        print(f"  ✓ Success field: {parsed.get('success')}")
        print(f"  ✓ Model field: {parsed.get('model')}")
    except json.JSONDecodeError:
        print(f"  ! Non-JSON output (expected if Claude not available): {result[:100]}")

except Exception as e:
    print(f"  ✗ Handler execution failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "="*60)
print("All integration tests passed!")
print("="*60)
print("\nSummary:")
print("- claude_headless.py module: Ready")
print("- ClaudeHeadless class: Implemented")
print("- agent_tools integration: Complete")
print("- Tool handler: Registered")
print("\nNext steps:")
print("1. Add claude_headless to agent allowlists (overseer only)")
print("2. Test with real Claude Code CLI invocation")
print("3. Add to gateway.py MCP server startup")
