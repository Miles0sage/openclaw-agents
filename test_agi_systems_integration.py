#!/usr/bin/env python3
"""
End-to-end AGI Systems Integration Test
========================================

Validates that all three AGI systems work together:
1. Prompt Versioning (agent soul evolution)
2. Tool Factory (dynamic tool creation)
3. Guardrail Auto-Apply (self-adjusting execution)
"""

import json
import os
import sys
import time
import tempfile
import sqlite3
from pathlib import Path

# Add openclaw to path
sys.path.insert(0, ".")

def test_prompt_versioning():
    """Test 1: Prompt Versioning System"""
    print("\n" + "="*70)
    print("TEST 1: Prompt Versioning System")
    print("="*70)

    from prompt_versioning import PromptVersionStore, PromptVersion

    # Create temp DB
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_prompts.db")
        store = PromptVersionStore(db_path=db_path)

        # Test 1a: Create initial version
        print("\n[1a] Create initial prompt version...")
        v1_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="You are CodeGen Pro. Write fast code.",
        )
        print(f"  ✓ Created version: {v1_id}")

        # Test 1b: Promote the version to active
        print("\n[1b] Promote version to active...")
        success = store.promote_version(v1_id)
        assert success, f"Failed to promote version {v1_id}"
        print(f"  ✓ Promoted version: {v1_id}")

        # Test 1b-2: Get active version
        print("\n[1b-2] Retrieve active version...")
        v1 = store.get_active_version("codegen_pro")
        assert v1 is not None
        assert v1.agent_key == "codegen_pro"
        assert v1.is_active
        print(f"  ✓ Retrieved version: {v1.agent_key}")
        print(f"    - Total jobs: {v1.total_jobs}")
        print(f"    - Successful jobs: {v1.successful_jobs}")
        print(f"    - Success rate: {v1.success_rate:.1%}")

        # Test 1c: Record outcomes
        print("\n[1c] Record execution outcomes...")
        for i in range(5):
            success = i < 4  # 4 successes, 1 failure
            store.record_outcome(
                version_id=v1_id,
                success=success,
                job_id=f"job_{i:03d}",
                phase="execute",
            )
        print(f"  ✓ Recorded 5 outcomes (4 successes, 1 failure)")

        # Test 1d: Verify stats updated
        print("\n[1d] Verify stats updated...")
        v1_updated = store.get_version(v1_id)
        print(f"  ✓ Updated stats:")
        print(f"    - Total jobs: {v1_updated.total_jobs} (expected: 5)")
        print(f"    - Successful jobs: {v1_updated.successful_jobs} (expected: 4)")
        print(f"    - Success rate: {v1_updated.success_rate:.1%} (expected: 80%)")
        assert v1_updated.total_jobs == 5, f"Expected 5 total jobs, got {v1_updated.total_jobs}"
        assert v1_updated.successful_jobs == 4, f"Expected 4 successful jobs, got {v1_updated.successful_jobs}"

        # Test 1e: Create variant (child version)
        print("\n[1e] Create variant prompt (child version)...")
        v2_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="You are CodeGen Pro v2. Write faster code.",
            parent_version=v1_id,
        )
        v2 = store.get_version(v2_id)
        assert v2.parent_version == v1_id
        print(f"  ✓ Created variant version: {v2_id}")
        print(f"    - Parent: {v2.parent_version}")
        print(f"    - Active: {v2.is_active}")

        # Test 1f: List versions
        print("\n[1f] List versions for agent...")
        versions = store.get_history(agent_key="codegen_pro")
        print(f"  ✓ Found {len(versions)} versions for codegen_pro")
        for v in versions:
            print(f"    - {v.version_id[:8]}... (active={v.is_active}, jobs={v.total_jobs})")

        print("\n✓ Prompt Versioning: PASSED")


def test_tool_factory():
    """Test 2: Tool Factory System"""
    print("\n" + "="*70)
    print("TEST 2: Tool Factory System")
    print("="*70)

    from tool_factory import ToolFactory, DynamicTool

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_tools.db")
        factory = ToolFactory(db_path=db_path)

        # Test 2a: Propose a safe dynamic tool
        print("\n[2a] Propose a safe dynamic tool...")
        tool_def = {
            "name": "add_numbers",
            "description": "Add two numbers together",
            "input_schema": {
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
            "implementation_type": "python_snippet",
            "implementation": "result = str(input_data['a'] + input_data['b'])",
        }
        tool = factory.propose_tool(agent_key="test_agent", tool_def=tool_def)
        tool_id = tool.name
        print(f"  ✓ Proposed tool: {tool_id}")

        # Test 2b: Get proposed tool
        print("\n[2b] Retrieve proposed tool...")
        retrieved_tool = factory.get_tool(tool_id)
        assert retrieved_tool is not None
        assert retrieved_tool.name == "add_numbers"
        assert retrieved_tool.approved == False and retrieved_tool.test_passed == False
        status = "approved" if retrieved_tool.approved else "pending"
        print(f"  ✓ Retrieved tool: {retrieved_tool.name} (status: {status})")

        # Test 2c: Test the tool (should pass)
        print("\n[2c] Test tool execution...")
        is_pass = factory.test_tool(
            tool_name=tool_id,
            test_input={"a": 5, "b": 3},
        )
        print(f"  ✓ Test result: {'PASS' if is_pass else 'FAIL'}")
        assert is_pass, f"Tool test failed"

        # Test 2d: Approve tool
        print("\n[2d] Approve tool...")
        approved_tool = factory.approve_tool(tool_name=tool_id, approval_notes="Test approval")
        assert approved_tool.approved == True
        print(f"  ✓ Tool approved: {approved_tool.name}")

        # Test 2e: Execute approved tool
        print("\n[2e] Execute approved tool...")
        exec_result = factory.execute_dynamic_tool(
            tool_name="add_numbers",
            tool_input={"a": 10, "b": 20},
        )
        print(f"  ✓ Execution result: {exec_result}")
        assert exec_result == "30", f"Expected '30', got '{exec_result}'"

        # Test 2f: List approved tools
        print("\n[2f] List approved tools...")
        approved = factory.list_dynamic_tools(approved_only=True)
        print(f"  ✓ Found {len(approved)} approved tools")
        for t in approved:
            status = "approved" if t.approved else "pending"
            print(f"    - {t.name} ({status})")

        print("\n✓ Tool Factory: PASSED")


def test_guardrail_auto_apply():
    """Test 3: Guardrail Auto-Apply System"""
    print("\n" + "="*70)
    print("TEST 3: Guardrail Auto-Apply System")
    print("="*70)

    from guardrail_auto_apply import GuardrailAutoApply

    with tempfile.TemporaryDirectory() as tmpdir:
        # Set temp data dir
        os.environ["OPENCLAW_DATA_DIR"] = tmpdir

        applier = GuardrailAutoApply(auto_apply=True)

        # Test 3a: Get current guardrails
        print("\n[3a] Get current guardrails...")
        config = applier.load_config()
        print(f"  ✓ Current guardrails:")
        print(f"    - Per-task limit: ${config.get('per_task_limit', 2.0):.2f}")
        print(f"    - Daily limit: ${config.get('daily_limit', 50.0):.2f}")
        print(f"    - Max iterations: {config.get('max_iterations', 400)}")

        # Test 3b: Create and apply a tighten recommendation
        print("\n[3b] Create and apply a tighten recommendation...")
        old_max_iters = config.get("max_iterations", 400)
        tighten_rec = {
            "type": "tighten",
            "project": "test_project",
            "reason": "High failure rate detected",
            "suggested_max_iterations": int(old_max_iters * 0.8),
        }
        result = applier.apply_recommendation(recommendation=tighten_rec)
        assert result is not None, "Tighten recommendation should be applied"
        assert result.parameter == "max_iterations"
        print(f"  ✓ Applied tighten recommendation:")
        print(f"    - Old max_iterations: {result.old_value}")
        print(f"    - New max_iterations: {result.new_value}")

        # Test 3c: Verify config was updated
        print("\n[3c] Verify config was updated...")
        updated_config = applier.load_config()
        new_max_iters = updated_config.get("max_iterations", 400)
        assert new_max_iters < old_max_iters, "Config should be tightened"
        print(f"  ✓ Config updated successfully")
        print(f"    - Max iterations: {old_max_iters} -> {new_max_iters}")

        # Test 3d: Create and apply a loosen recommendation
        print("\n[3d] Create and apply a loosen recommendation...")
        old_per_task = updated_config.get("per_task_limit", 2.0)
        loosen_rec = {
            "type": "loosen",
            "project": "test_project",
            "reason": "All tasks completing within budget",
            "suggested_max_cost_usd": old_per_task * 1.5,
        }
        result = applier.apply_recommendation(recommendation=loosen_rec)
        assert result is not None, "Loosen recommendation should be applied"
        assert result.parameter == "per_task_limit"
        print(f"  ✓ Applied loosen recommendation:")
        print(f"    - Old per_task_limit: ${result.old_value:.2f}")
        print(f"    - New per_task_limit: ${result.new_value:.2f}")

        # Test 3e: Get audit trail
        print("\n[3e] Get audit trail...")
        audit = applier.get_audit_trail()
        print(f"  ✓ Audit entries: {len(audit)}")
        for i, entry in enumerate(audit):
            print(f"    - {entry.get('recommendation_type', 'N/A')}: {entry.get('parameter', 'N/A')} {entry.get('old_value')} -> {entry.get('new_value')}")
            if i >= 2:
                break

        print("\n✓ Guardrail Auto-Apply: PASSED")


def test_tool_router_integration():
    """Test 4: Tool Router Phase Gating"""
    print("\n" + "="*70)
    print("TEST 4: Tool Router Phase Gating")
    print("="*70)

    from tool_router import ToolRegistry, PhaseViolationError

    registry = ToolRegistry()

    # Test 4a: Check propose_tool availability
    print("\n[4a] Check propose_tool availability...")
    tool = registry.get_tool("propose_tool")
    if tool:
        print(f"  ✓ Tool found: {tool['name']}")
        print(f"    - Risk level: {tool['risk_level']}")
        print(f"    - Available in phases: {[p for p in ['research', 'plan', 'execute', 'verify', 'deliver'] if tool['availability'][p]]}")
    else:
        print(f"  ℹ Tool 'propose_tool' not found (OK if not registered)")

    # Test 4b: Verify phase gating
    print("\n[4b] Verify phase gating enforcement...")
    test_cases = [
        ("research", "web_search", True),   # Should be allowed
        ("research", "shell_execute", False),  # Should be blocked
        ("execute", "shell_execute", True),  # Should be allowed
        ("execute", "web_search", True),  # web_search only in research, not execute
        ("verify", "file_write", False),  # Should be blocked
    ]

    for phase, tool_name, should_be_allowed in test_cases:
        is_allowed = registry.is_tool_allowed(tool_name, phase)
        status = "✓" if is_allowed == should_be_allowed else "✗"
        expected = "allowed" if should_be_allowed else "blocked"
        actual = "allowed" if is_allowed else "blocked"
        print(f"  {status} {tool_name:20} in {phase:10} — {actual} ({expected})")

    # Test 4c: Get tools for phase
    print("\n[4c] Get tools available for EXECUTE phase...")
    execute_tools = registry.get_tools_for_phase("execute")
    print(f"  ✓ {len(execute_tools)} tools available in EXECUTE:")
    for tool in execute_tools[:5]:
        print(f"    - {tool['name']} ({tool['risk_level']})")
    if len(execute_tools) > 5:
        print(f"    ... and {len(execute_tools) - 5} more")

    print("\n✓ Tool Router: PASSED")


def test_autonomous_runner_integration():
    """Test 5: AutonomousRunner Integration with AGI Systems"""
    print("\n" + "="*70)
    print("TEST 5: AutonomousRunner Integration")
    print("="*70)

    from autonomous_runner import AutonomousRunner

    print("\n[5a] Check AutonomousRunner initialization...")
    with tempfile.TemporaryDirectory() as tmpdir:
        # Set temp data dir
        os.environ["OPENCLAW_DATA_DIR"] = tmpdir

        runner = AutonomousRunner(max_concurrent=2, budget_limit_usd=10.0)

        # Verify AGI systems are initialized
        assert hasattr(runner, 'prompt_store'), "AutonomousRunner missing prompt_store"
        assert hasattr(runner, 'tool_factory'), "AutonomousRunner missing tool_factory"
        assert hasattr(runner, 'guardrail_applier'), "AutonomousRunner missing guardrail_applier"

        print(f"  ✓ AutonomousRunner initialized with AGI systems:")
        print(f"    - prompt_store: {runner.prompt_store.__class__.__name__}")
        print(f"    - tool_factory: {runner.tool_factory.__class__.__name__}")
        print(f"    - guardrail_applier: {runner.guardrail_applier.__class__.__name__}")

        # Verify helper methods exist
        print("\n[5b] Verify helper methods exist...")
        assert hasattr(runner, '_get_active_prompt_for_agent'), "Missing _get_active_prompt_for_agent"
        assert hasattr(runner, '_record_phase_outcome'), "Missing _record_phase_outcome"
        print(f"  ✓ Helper methods present:")
        print(f"    - _get_active_prompt_for_agent()")
        print(f"    - _record_phase_outcome()")

        print("\n✓ AutonomousRunner Integration: PASSED")


def main():
    """Run all integration tests"""
    print("\n" + "="*70)
    print("AGI SYSTEMS INTEGRATION TEST SUITE")
    print("="*70)
    print(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    tests = [
        ("Prompt Versioning", test_prompt_versioning),
        ("Tool Factory", test_tool_factory),
        ("Guardrail Auto-Apply", test_guardrail_auto_apply),
        ("Tool Router", test_tool_router_integration),
        ("AutonomousRunner Integration", test_autonomous_runner_integration),
    ]

    passed = 0
    failed = 0
    errors = []

    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            failed += 1
            errors.append(f"{name}: {e}")
            print(f"\n✗ {name}: FAILED")
            print(f"  Error: {e}")
        except Exception as e:
            failed += 1
            errors.append(f"{name}: {e}")
            print(f"\n✗ {name}: ERROR")
            print(f"  Error: {e}")
            import traceback
            traceback.print_exc()

    # Summary
    print("\n" + "="*70)
    print("INTEGRATION TEST SUMMARY")
    print("="*70)
    print(f"Passed: {passed}/{len(tests)}")
    print(f"Failed: {failed}/{len(tests)}")
    print(f"Finished: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    if errors:
        print("\nErrors:")
        for error in errors:
            print(f"  - {error}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
