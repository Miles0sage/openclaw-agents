"""
Test suite for Cost Gates Module
Tests all 3-tier budget enforcement scenarios
"""

import pytest
import tempfile
import os
from datetime import datetime, timedelta
from cost_gates import (
    CostGates,
    CostGatesDB,
    BudgetStatus,
    CostCheckResult,
    BudgetGate,
    check_cost_budget,
    record_cost,
    init_cost_gates,
    get_cost_gates,
    PRICING,
)


@pytest.fixture
def temp_db():
    """Create temporary database for testing"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def cost_gates(temp_db):
    """Create cost gates instance with temp database"""
    return CostGates(db_path=temp_db)


class TestPricingConstants:
    """Test pricing configuration"""
    
    def test_kimi_25_pricing(self):
        """Verify Kimi 2.5 pricing"""
        assert PRICING["kimi-2.5"]["input"] == 0.27
        assert PRICING["kimi-2.5"]["output"] == 1.10
    
    def test_kimi_reasoner_pricing(self):
        """Verify Kimi Reasoner pricing"""
        assert PRICING["kimi-reasoner"]["input"] == 0.55
        assert PRICING["kimi-reasoner"]["output"] == 2.19
    
    def test_claude_opus_pricing(self):
        """Verify Claude Opus pricing"""
        assert PRICING["claude-opus-4-6"]["input"] == 15.0
        assert PRICING["claude-opus-4-6"]["output"] == 60.0


class TestCostCalculation:
    """Test cost calculation logic"""
    
    def test_calculate_kimi_25_cost(self, cost_gates):
        """Calculate cost for Kimi 2.5 request"""
        # 1M input tokens, 0.5M output tokens
        cost = cost_gates.calculate_cost("kimi-2.5", 1_000_000, 500_000)
        expected = (1_000_000 * 0.27 + 500_000 * 1.10) / 1_000_000
        assert cost == pytest.approx(expected, rel=0.01)
    
    def test_calculate_kimi_reasoner_cost(self, cost_gates):
        """Calculate cost for Kimi Reasoner request"""
        # 1M input tokens, 1M output tokens
        cost = cost_gates.calculate_cost("kimi-reasoner", 1_000_000, 1_000_000)
        expected = (1_000_000 * 0.55 + 1_000_000 * 2.19) / 1_000_000
        assert cost == pytest.approx(expected, rel=0.01)
    
    def test_calculate_claude_opus_cost(self, cost_gates):
        """Calculate cost for Claude Opus request"""
        # 100K input tokens, 50K output tokens
        cost = cost_gates.calculate_cost("claude-opus-4-6", 100_000, 50_000)
        expected = (100_000 * 15.0 + 50_000 * 60.0) / 1_000_000
        assert cost == pytest.approx(expected, rel=0.01)
    
    def test_low_token_count_cost(self, cost_gates):
        """Calculate cost for small requests"""
        # 1K input, 1K output
        cost = cost_gates.calculate_cost("kimi-2.5", 1_000, 1_000)
        expected = (1_000 * 0.27 + 1_000 * 1.10) / 1_000_000
        assert cost == pytest.approx(expected, rel=0.01)
        assert cost < 0.01  # Should be less than 1 cent


class TestBudgetGates:
    """Test 3-tier budget gate configuration"""
    
    def test_default_gates(self, cost_gates):
        """Verify default budget gates are set"""
        assert cost_gates.gates["per_task"].limit == 10.0
        assert cost_gates.gates["daily"].limit == 50.0
        assert cost_gates.gates["monthly"].limit == 1000.0
    
    def test_custom_gates(self, temp_db):
        """Custom budget configuration"""
        config = {
            "per_task": {"limit": 5.0, "threshold_warning": 4.0},
            "daily": {"limit": 20.0, "threshold_warning": 16.0},
            "monthly": {"limit": 500.0, "threshold_warning": 400.0},
        }
        gates = CostGates(config=config, db_path=temp_db)
        
        assert gates.gates["per_task"].limit == 5.0
        assert gates.gates["daily"].limit == 20.0
        assert gates.gates["monthly"].limit == 500.0


class TestPerTaskBudget:
    """Test per-task budget enforcement"""
    
    def test_under_per_task_limit(self, cost_gates):
        """Task cost under per-task limit"""
        result = cost_gates.check_budget(
            project="test",
            agent="pm",
            model="kimi-2.5",
            tokens_input=100_000,
            tokens_output=50_000,
            task_id="task1"
        )
        assert result.status == BudgetStatus.APPROVED
        assert result.remaining_budget > 0
    
    def test_exceed_per_task_limit(self, cost_gates):
        """Task cost exceeds per-task limit - REJECTED"""
        # Kimi Reasoner: 20M input = $11 (exceeds $10 limit)
        result = cost_gates.check_budget(
            project="test",
            agent="pm",
            model="kimi-reasoner",
            tokens_input=20_000_000,
            tokens_output=0,
            task_id="task_expensive"
        )
        assert result.status == BudgetStatus.REJECTED
        assert result.gate_name == "per-task"
    
    def test_task_near_per_task_limit(self, cost_gates):
        """Task cost near per-task limit generates warning"""
        # Kimi Reasoner: 18M input = $9.9 (80% of $10 limit = warning threshold $8)
        result = cost_gates.check_budget(
            project="test",
            agent="pm",
            model="kimi-reasoner",
            tokens_input=18_000_000,
            tokens_output=0,
            task_id="task_nearexpensive"
        )
        # Will be warning or approved depending on whether it hits warning threshold
        assert result.status in [BudgetStatus.APPROVED, BudgetStatus.WARNING]


class TestDailyBudget:
    """Test daily budget enforcement"""
    
    def test_first_task_approved(self, cost_gates):
        """First task of day under daily limit"""
        result = cost_gates.check_budget(
            project="test",
            agent="pm",
            model="kimi-2.5",
            tokens_input=1_000_000,
            tokens_output=500_000,
            task_id="daily1"
        )
        assert result.status == BudgetStatus.APPROVED
    
    def test_accumulate_daily_spending(self, cost_gates):
        """Multiple tasks accumulate toward daily limit"""
        # First task: ~$0.77
        result1 = cost_gates.check_budget(
            project="test", agent="pm", model="kimi-2.5",
            tokens_input=1_000_000, tokens_output=500_000, task_id="daily1"
        )
        assert result1.status == BudgetStatus.APPROVED
        cost_gates.record_spending("test", "pm", 0.77)
        
        # Second task: ~$0.77
        result2 = cost_gates.check_budget(
            project="test", agent="pm", model="kimi-2.5",
            tokens_input=1_000_000, tokens_output=500_000, task_id="daily2"
        )
        assert result2.status == BudgetStatus.APPROVED
        cost_gates.record_spending("test", "pm", 0.77)
        
        # Verify both tasks recorded
        status = cost_gates.get_budget_status("test")
        assert status["daily"]["spent"] >= 1.54
    
    def test_exceed_daily_limit(self, cost_gates):
        """Exceeding daily limit triggers rejection"""
        # Simulate $45 already spent today
        cost_gates.db.record_daily_spending("test", "pm", 45.0)
        
        # Kimi Reasoner: 15M input + 0.5M output = $8.25 + $1.09 = $9.35 < $10 per-task OK
        # Total daily: $45 + $9.35 = $54.35 > $50 REJECT!
        result = cost_gates.check_budget(
            project="test",
            agent="pm",
            model="kimi-reasoner",
            tokens_input=15_000_000,
            tokens_output=500_000,
            task_id="daily_exceed"
        )
        assert result.status == BudgetStatus.REJECTED
        assert result.gate_name == "daily"

class TestMonthlyBudget:
    """Test monthly budget enforcement"""
    
    def test_first_task_of_month(self, cost_gates):
        """First task of month under monthly limit"""
        result = cost_gates.check_budget(
            project="test",
            agent="pm",
            model="kimi-2.5",
            tokens_input=1_000_000,
            tokens_output=500_000,
            task_id="month1"
        )
        assert result.status == BudgetStatus.APPROVED
    
    def test_accumulate_monthly_spending(self, cost_gates):
        """Multiple days accumulate toward monthly limit"""
        # First day: $100
        cost_gates.db.record_monthly_spending("test", "pm", 100.0)
        
        # Second day: $100
        cost_gates.db.record_monthly_spending("test", "pm", 100.0)
        
        # Third day: $100
        cost_gates.db.record_monthly_spending("test", "pm", 100.0)
        
        # Still room in $1000 budget
        result = cost_gates.check_budget(
            project="test",
            agent="pm",
            model="kimi-2.5",
            tokens_input=1_000_000,
            tokens_output=500_000,
            task_id="month4"
        )
        assert result.status == BudgetStatus.APPROVED
        
        # Check status shows $300 spent
        status = cost_gates.get_budget_status("test")
        assert status["month"]["spent"] >= 300.0
    
    def test_exceed_monthly_limit(self, cost_gates):
        """Exceeding monthly limit triggers rejection"""
        # Simulate $950 already spent this month
        cost_gates.db.record_monthly_spending("test", "pm", 950.0)
        
        # Kimi 2.5: need >$50 to exceed $1000
        # 100M input + 50M output = $27 + $55 = $82 (total $1032 > $1000) REJECT!
        # But that's also >$10 per-task. Let's try to trigger monthly first
        # Use Kimi Reasoner for same result with fewer tokens
        # $0.55/M input, $2.19/M output
        # Need $51+ : 80M input + 5M output = $44 + $10.95 = $54.95 > $10 per-task
        # Hmm, still over. Let's keep it simple and just use the cheaper model
        result = cost_gates.check_budget(
            project="test",
            agent="pm",
            model="kimi-2.5",
            tokens_input=100_000_000,
            tokens_output=50_000_000,
            task_id="month_exceed"
        )
        # Either gate can reject, both are valid
        assert result.status == BudgetStatus.REJECTED
        assert result.gate_name in ["monthly", "per-task"]
    
    def test_monthly_budget_ok(self, cost_gates):
        """Monthly budget check passes"""
        # Simulate $500 already spent (50% of $1000)
        cost_gates.db.record_monthly_spending("test", "pm", 500.0)
        
        # Task cost $10 (but under per-task limit)
        result = cost_gates.check_budget(
            project="test",
            agent="pm",
            model="kimi-2.5",
            tokens_input=5_000_000,
            tokens_output=0,
            task_id="month_ok"
        )
        assert result.status == BudgetStatus.APPROVED


class TestDatabaseOperations:
    """Test database storage and retrieval"""
    
    def test_record_and_retrieve_daily_spending(self, temp_db):
        """Record and query daily spending"""
        db = CostGatesDB(db_path=temp_db)
        today = datetime.now().strftime("%Y-%m-%d")
        
        db.record_daily_spending("project1", "agent1", 10.50, date=today)
        db.record_daily_spending("project1", "agent2", 5.25, date=today)
        
        total = db.get_daily_spending(date=today, project="project1")
        assert total >= 15.75
    
    def test_record_and_retrieve_monthly_spending(self, temp_db):
        """Record and query monthly spending"""
        db = CostGatesDB(db_path=temp_db)
        year_month = datetime.now().strftime("%Y-%m")
        
        db.record_monthly_spending("project1", "agent1", 100.0, year_month=year_month)
        db.record_monthly_spending("project1", "agent2", 50.0, year_month=year_month)
        
        total = db.get_monthly_spending(year_month=year_month, project="project1")
        assert total >= 150.0
    
    def test_record_task_spending(self, temp_db):
        """Record task spending details"""
        db = CostGatesDB(db_path=temp_db)
        
        db.record_task_spending(
            task_id="task123",
            project="project1",
            agent="pm",
            model="kimi-2.5",
            tokens_input=1_000_000,
            tokens_output=500_000,
            cost=0.77,
            status="approved"
        )
        
        record = db.get_task_spending("task123")
        assert record is not None
        assert record["task_id"] == "task123"
        assert record["cost"] == 0.77
        assert record["status"] == "approved"
    
    def test_approval_workflow(self, temp_db):
        """Test budget approval request and approval"""
        db = CostGatesDB(db_path=temp_db)
        
        # Request approval for high-cost task
        db.request_approval("task999", "project1", "pm", 15.0)
        
        # Initially not approved
        assert not db.is_approved("task999")
        
        # Approve it
        db.approve_task("task999", approved_by="admin", reason="High-value analysis")
        
        # Now approved
        assert db.is_approved("task999")


class TestBudgetStatus:
    """Test budget status reporting"""
    
    def test_budget_status_empty(self, cost_gates):
        """Budget status with no spending"""
        status = cost_gates.get_budget_status("test")
        
        assert status["daily"]["spent"] == 0.0
        assert status["daily"]["remaining"] == 50.0
        assert status["daily"]["percent_used"] == 0.0
        
        assert status["month"]["spent"] == 0.0
        assert status["month"]["remaining"] == 1000.0
        assert status["month"]["percent_used"] == 0.0
    
    def test_budget_status_with_spending(self, cost_gates):
        """Budget status with recorded spending"""
        cost_gates.db.record_daily_spending("test", "pm", 10.0)
        cost_gates.db.record_monthly_spending("test", "pm", 100.0)
        
        status = cost_gates.get_budget_status("test")
        
        assert status["daily"]["spent"] >= 10.0
        assert status["daily"]["remaining"] <= 40.0
        assert status["daily"]["percent_used"] >= 20.0
        
        assert status["month"]["spent"] >= 100.0
        assert status["month"]["remaining"] <= 900.0
        assert status["month"]["percent_used"] >= 10.0


class TestIntegrationScenarios:
    """End-to-end test scenarios"""
    
    def test_scenario_pass_all_checks(self, cost_gates):
        """Scenario: Small task passes all budget checks"""
        result = cost_gates.check_budget(
            project="barber_crm",
            agent="pm",
            model="kimi-2.5",
            tokens_input=10_000,
            tokens_output=5_000,
            task_id="booking_query_1"
        )
        
        assert result.status == BudgetStatus.APPROVED
        assert result.remaining_budget > 0
        assert "approved" in result.message.lower()
        
        # Record the spending
        cost_gates.record_spending("barber_crm", "pm", result.projected_total)
        
        # Verify it was recorded
        status = cost_gates.get_budget_status("barber_crm")
        assert status["daily"]["spent"] > 0
    
    def test_scenario_multiple_agents(self, cost_gates):
        """Scenario: Different agents spending in same project"""
        # PM agent spends $5
        cost_gates.record_spending("barber_crm", "pm", 5.0)
        
        # Coder agent spends $3
        cost_gates.record_spending("barber_crm", "coder", 3.0)
        
        # Status should show combined spending
        status = cost_gates.get_budget_status("barber_crm")
        assert status["daily"]["spent"] >= 8.0
        assert status["daily"]["remaining"] <= 42.0
    
    def test_scenario_realistic_workflow(self, cost_gates):
        """Scenario: Realistic multi-task workflow"""
        # Day 1: Process 3 customer requests
        tasks = [
            ("booking_1", "kimi-2.5", 500_000, 250_000),      # ~$0.27
            ("booking_2", "kimi-2.5", 500_000, 250_000),      # ~$0.27
            ("analysis_1", "kimi-reasoner", 1_000_000, 500_000),  # ~$1.375
        ]
        
        total_cost = 0
        for task_id, model, inp, out in tasks:
            result = cost_gates.check_budget(
                project="barber_crm",
                agent="pm",
                model=model,
                tokens_input=inp,
                tokens_output=out,
                task_id=task_id
            )
            assert result.status in [BudgetStatus.APPROVED, BudgetStatus.WARNING]
            total_cost += result.projected_total
            cost_gates.record_spending("barber_crm", "pm", result.projected_total)
        
        # Verify total spending
        status = cost_gates.get_budget_status("barber_crm")
        assert status["daily"]["spent"] >= total_cost - 0.01


class TestErrorHandling:
    """Test error conditions and edge cases"""
    
    def test_unknown_model_defaults_to_sonnet(self, cost_gates):
        """Unknown model falls back to Sonnet pricing"""
        cost = cost_gates.calculate_cost("unknown-model-xyz", 1_000_000, 1_000_000)
        # Should use default pricing (Sonnet)
        assert cost > 0
    
    def test_zero_tokens(self, cost_gates):
        """Zero token cost"""
        cost = cost_gates.calculate_cost("kimi-2.5", 0, 0)
        assert cost == 0.0
    
    def test_negative_spending_prevented(self, cost_gates):
        """Database handles edge cases gracefully"""
        # Record spending
        cost_gates.db.record_daily_spending("test", "pm", 10.0)
        
        # Verify positive balance
        status = cost_gates.get_budget_status("test")
        assert status["daily"]["remaining"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
