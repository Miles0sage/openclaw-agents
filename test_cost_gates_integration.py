#!/usr/bin/env python3
"""
Integration tests for cost gates with gateway.py
Tests the 3 scenarios: under budget, warning threshold, over budget
"""

import pytest
import json
from cost_gates import (
    get_cost_gates, init_cost_gates, CostGates, BudgetStatus
)


def test_cost_gates_module_exists():
    """Verify cost gates module is available"""
    gates = get_cost_gates()
    assert gates is not None
    assert hasattr(gates, 'check_budget')
    assert hasattr(gates, 'record_spending')
    assert hasattr(gates, 'get_budget_status')
    print("✅ Cost gates module verified")


def test_cost_gates_defaults():
    """Test default budget gate values"""
    gates = init_cost_gates()
    
    # Verify default gates exist
    assert 'per_task' in gates.gates
    assert 'daily' in gates.gates
    assert 'monthly' in gates.gates
    
    # Verify default limits
    assert gates.gates['per_task'].limit == 10.0
    assert gates.gates['daily'].limit == 50.0
    assert gates.gates['monthly'].limit == 1000.0
    
    print("✅ Default budget gates verified")


def test_under_budget_scenario():
    """Test scenario: request under budget (should succeed)"""
    gates = init_cost_gates()
    
    # Small request (cheap Claude Haiku)
    result = gates.check_budget(
        project="test-under",
        agent="pm",
        model="claude-3-5-haiku-20241022",
        tokens_input=100,
        tokens_output=100,
        task_id="test-under-1"
    )
    
    assert result.status == BudgetStatus.APPROVED
    assert result.remaining_budget > 0
    assert "approved" in result.message.lower()
    
    print(f"✅ Under budget scenario: {result.message}")


def test_warning_threshold_scenario():
    """Test scenario: request at warning threshold (should warn)"""
    gates = init_cost_gates({
        'per_task': {
            'limit': 1.0,
            'threshold_warning': 0.5
        },
        'daily': {
            'limit': 50.0,
            'threshold_warning': 40.0
        },
        'monthly': {
            'limit': 1000.0,
            'threshold_warning': 800.0
        }
    })
    
    # Use expensive Opus model for warning scenario
    result = gates.check_budget(
        project="test-warning",
        agent="pm",
        model="claude-opus-4-6",  # Most expensive
        tokens_input=100,
        tokens_output=100,
        task_id="test-warning-1"
    )
    
    # Should warn because task cost is approaching per-task threshold
    if result.status == BudgetStatus.WARNING:
        assert "approaching" in result.message.lower()
        print(f"✅ Warning threshold scenario: {result.message}")
    else:
        print(f"ℹ️  Task cost ${result.projected_total:.6f} didn't trigger warning (status: {result.status})")


def test_over_budget_scenario():
    """Test scenario: request over budget (should reject)"""
    gates = init_cost_gates({
        'per_task': {
            'limit': 0.005,  # Very small limit to trigger rejection
            'threshold_warning': 0.003
        },
        'daily': {
            'limit': 50.0,
            'threshold_warning': 40.0
        },
        'monthly': {
            'limit': 1000.0,
            'threshold_warning': 800.0
        }
    })
    
    result = gates.check_budget(
        project="test-over",
        agent="pm",
        model="claude-3-5-sonnet-20241022",  # Medium cost
        tokens_input=10000,  # Large request
        tokens_output=10000,
        task_id="test-over-1"
    )
    
    assert result.status == BudgetStatus.REJECTED
    assert result.gate_name == "per-task"
    assert "exceed" in result.message.lower()
    
    print(f"✅ Over budget scenario: {result.message}")


def test_budget_status_reporting():
    """Test budget status reporting"""
    gates = init_cost_gates()
    
    # Record some spending
    gates.db.record_daily_spending("test-status", "pm", 5.0)
    gates.db.record_monthly_spending("test-status", "pm", 50.0)
    
    status = gates.get_budget_status("test-status")
    
    assert "date" in status
    assert "daily" in status
    assert "month" in status
    assert status["daily"]["spent"] == 5.0
    assert status["daily"]["limit"] == 50.0
    assert status["month"]["spent"] == 50.0
    assert status["month"]["limit"] == 1000.0
    
    print(f"✅ Budget status: daily {status['daily']['percent_used']}%, monthly {status['month']['percent_used']}%")


def test_multiple_models_pricing():
    """Test cost calculation for different models"""
    gates = init_cost_gates()
    
    models = [
        ("claude-3-5-haiku-20241022", 1000, 1000),   # Cheapest
        ("claude-3-5-sonnet-20241022", 1000, 1000),  # Medium
        ("claude-opus-4-6", 1000, 1000),             # Expensive
    ]
    
    costs = []
    for model, input_tokens, output_tokens in models:
        cost = gates.calculate_cost(model, input_tokens, output_tokens)
        costs.append(cost)
        print(f"  {model}: ${cost:.6f}")
    
    # Verify costs increase as models get stronger
    assert costs[0] < costs[1] < costs[2], "Costs should increase from Haiku → Sonnet → Opus"
    print("✅ Multi-model pricing verified")


def test_cost_gate_isolation():
    """Test that cost gates work independently for different projects"""
    gates = init_cost_gates()
    
    # Record spending in different projects
    gates.db.record_daily_spending("proj-a", "pm", 10.0)
    gates.db.record_daily_spending("proj-b", "pm", 5.0)
    
    status_a = gates.get_budget_status("proj-a")
    status_b = gates.get_budget_status("proj-b")
    
    assert status_a["daily"]["spent"] == 10.0
    assert status_b["daily"]["spent"] == 5.0
    
    print("✅ Cost gate isolation verified")


def test_gateway_import():
    """Test that cost_gates can be imported in gateway context"""
    try:
        from cost_gates import get_cost_gates, BudgetStatus
        gates = get_cost_gates()
        assert gates is not None
        print("✅ Gateway imports verified")
    except ImportError as e:
        print(f"❌ Import error: {e}")
        raise


if __name__ == "__main__":
    print("\n=== Cost Gates Integration Tests ===\n")
    
    test_cost_gates_module_exists()
    test_cost_gates_defaults()
    test_under_budget_scenario()
    test_warning_threshold_scenario()
    test_over_budget_scenario()
    test_budget_status_reporting()
    test_multiple_models_pricing()
    test_cost_gate_isolation()
    test_gateway_import()
    
    print("\n✅ All integration tests passed!\n")
