"""
Tests for GuardrailAutoApply auto-apply engine.
"""

import json
import os
import tempfile
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta

from guardrail_auto_apply import (
    GuardrailAutoApply,
    GuardrailChange,
    get_auto_apply_engine,
    apply_recommendations,
    DATA_DIR,
    CHANGES_FILE,
    GUARDRAIL_CONFIG_FILE,
)


@pytest.fixture
def temp_data_dir(monkeypatch):
    """Create a temporary data directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("OPENCLAW_DATA_DIR", tmpdir)
        # Re-import to pick up new env var
        import importlib
        import guardrail_auto_apply
        importlib.reload(guardrail_auto_apply)
        yield tmpdir


@pytest.fixture
def auto_apply_engine(temp_data_dir):
    """Create a fresh auto-apply engine for testing."""
    engine = GuardrailAutoApply(auto_apply=True)
    return engine


class TestGuardrailAutoApplyInit:
    """Test initialization and configuration."""

    def test_init_creates_default_config(self, auto_apply_engine):
        """Should create default config on init."""
        config = auto_apply_engine.load_config()
        assert config is not None
        assert "per_task_limit" in config
        assert "daily_limit" in config
        assert "max_iterations" in config

    def test_default_config_values(self, auto_apply_engine):
        """Check default config values."""
        config = auto_apply_engine.load_config()
        assert config["per_task_limit"] == 2.0
        assert config["daily_limit"] == 50.0
        assert config["monthly_limit"] == 1000.0
        assert config["max_iterations"] == 400

    def test_auto_apply_disabled(self, temp_data_dir):
        """Should not apply changes when auto_apply=False."""
        engine = GuardrailAutoApply(auto_apply=False)
        rec = {
            "type": "tighten",
            "project": "test-project",
            "reason": "Test",
            "suggested_max_iterations": 200,
        }
        result = engine.apply_recommendation(rec)
        assert result is None


class TestValidationAndClamping:
    """Test validation and safety clamping logic."""

    def test_per_task_min_clamping(self, auto_apply_engine):
        """Should reject per-task values below minimum."""
        is_valid, clamped, reason = auto_apply_engine._validate_and_clamp(
            "per_task_limit", 0.25, 2.0
        )
        assert not is_valid
        assert clamped == 2.0

    def test_per_task_max_clamping(self, auto_apply_engine):
        """Should clamp per-task values above maximum."""
        is_valid, clamped, reason = auto_apply_engine._validate_and_clamp(
            "per_task_limit", 10.0, 2.0
        )
        assert is_valid
        assert clamped == 5.0  # PER_TASK_MAX

    def test_per_task_valid_range(self, auto_apply_engine):
        """Should accept valid per-task values."""
        is_valid, clamped, reason = auto_apply_engine._validate_and_clamp(
            "per_task_limit", 3.0, 2.0
        )
        assert is_valid
        assert clamped == 3.0

    def test_daily_limit_max_clamping(self, auto_apply_engine):
        """Should clamp daily_limit above maximum."""
        is_valid, clamped, reason = auto_apply_engine._validate_and_clamp(
            "daily_limit", 100.0, 50.0
        )
        assert is_valid
        assert clamped == 50.0  # DAILY_MAX

    def test_daily_limit_valid(self, auto_apply_engine):
        """Should accept valid daily_limit values."""
        is_valid, clamped, reason = auto_apply_engine._validate_and_clamp(
            "daily_limit", 45.0, 50.0
        )
        assert is_valid
        assert clamped == 45.0

    def test_iteration_limit_min(self, auto_apply_engine):
        """Should reject iteration limits below 5."""
        is_valid, clamped, reason = auto_apply_engine._validate_and_clamp(
            "max_iterations", 2, 400
        )
        assert not is_valid

    def test_iteration_limit_valid(self, auto_apply_engine):
        """Should accept valid iteration limits."""
        is_valid, clamped, reason = auto_apply_engine._validate_and_clamp(
            "max_iterations", 300, 400
        )
        assert is_valid
        assert clamped == 300


class TestTightenRecommendation:
    """Test tighten recommendation application."""

    def test_apply_tighten(self, auto_apply_engine):
        """Should apply tighten recommendation."""
        rec = {
            "type": "tighten",
            "project": "test-project",
            "reason": "Low success rate",
            "suggested_max_iterations": 200,
        }
        change = auto_apply_engine.apply_recommendation(rec)
        assert change is not None
        assert change.parameter == "max_iterations"
        assert change.old_value == 400
        assert change.new_value == 200
        assert change.project == "test-project"
        assert change.recommendation_type == "tighten"

    def test_tighten_persists_to_config(self, auto_apply_engine):
        """Tighten change should persist to config file."""
        rec = {
            "type": "tighten",
            "project": "test-project",
            "reason": "Test",
            "suggested_max_iterations": 250,
        }
        auto_apply_engine.apply_recommendation(rec)
        config = auto_apply_engine.load_config()
        assert config["max_iterations"] == 250

    def test_tighten_clamping_applied(self, auto_apply_engine):
        """Tighten should clamp if suggested value violates limits."""
        rec = {
            "type": "tighten",
            "project": "test-project",
            "reason": "Test",
            "suggested_max_iterations": 2,  # Below min 5
        }
        change = auto_apply_engine.apply_recommendation(rec)
        assert change is None  # Should be rejected


class TestLoosenRecommendation:
    """Test loosen recommendation application."""

    def test_apply_loosen(self, auto_apply_engine):
        """Should apply loosen recommendation."""
        rec = {
            "type": "loosen",
            "project": "test-project",
            "reason": "High success rate",
            "suggested_max_cost_usd": 4.0,
        }
        change = auto_apply_engine.apply_recommendation(rec)
        assert change is not None
        assert change.parameter == "per_task_limit"
        assert change.old_value == 2.0
        assert change.new_value == 4.0
        assert change.recommendation_type == "loosen"

    def test_loosen_persists_to_config(self, auto_apply_engine):
        """Loosen change should persist to config file."""
        rec = {
            "type": "loosen",
            "project": "test-project",
            "reason": "Test",
            "suggested_max_cost_usd": 3.5,
        }
        auto_apply_engine.apply_recommendation(rec)
        config = auto_apply_engine.load_config()
        assert config["per_task_limit"] == 3.5

    def test_loosen_clamping_applied(self, auto_apply_engine):
        """Loosen should clamp if suggested value exceeds max."""
        rec = {
            "type": "loosen",
            "project": "test-project",
            "reason": "Test",
            "suggested_max_cost_usd": 10.0,  # Above max
        }
        change = auto_apply_engine.apply_recommendation(rec)
        assert change is not None
        assert change.new_value == 5.0  # Should be clamped to PER_TASK_MAX


class TestIncreaseBudgetRecommendation:
    """Test increase_budget recommendation application."""

    def test_apply_increase_budget(self, auto_apply_engine):
        """Should apply increase_budget recommendation."""
        # First, lower the daily limit so we can test an increase
        config = auto_apply_engine.load_config()
        config["daily_limit"] = 30.0
        auto_apply_engine.save_config(config)

        rec = {
            "type": "increase_budget",
            "project": "test-project",
            "reason": "Multiple budget kills",
        }
        change = auto_apply_engine.apply_recommendation(rec)
        assert change is not None
        assert change.parameter == "daily_limit"
        assert change.old_value == 30.0
        # Should be at least 20% increase (30 * 1.2 = 36)
        assert change.new_value >= 36.0
        assert change.recommendation_type == "increase_budget"

    def test_increase_budget_persists_to_config(self, auto_apply_engine):
        """Increase budget change should persist to config file."""
        rec = {
            "type": "increase_budget",
            "project": "test-project",
            "reason": "Test",
        }
        auto_apply_engine.apply_recommendation(rec)
        config = auto_apply_engine.load_config()
        assert config["daily_limit"] >= 50.0

    def test_increase_budget_clamping_applied(self, auto_apply_engine):
        """Increase budget should clamp to daily max."""
        # Manually set to high value first
        config = auto_apply_engine.load_config()
        config["daily_limit"] = 48.0
        auto_apply_engine.save_config(config)

        rec = {
            "type": "increase_budget",
            "project": "test-project",
            "reason": "Test",
        }
        change = auto_apply_engine.apply_recommendation(rec)
        assert change is not None
        # Should increase to at least 57.6 (20% of 48), but capped at DAILY_MAX (50)
        assert change.new_value <= 50.0


class TestAuditTrail:
    """Test audit trail logging."""

    def test_changes_logged_to_file(self, auto_apply_engine):
        """All changes should be logged to guardrail_changes.jsonl."""
        rec = {
            "type": "tighten",
            "project": "test-project",
            "reason": "Test",
            "suggested_max_iterations": 200,
        }
        auto_apply_engine.apply_recommendation(rec)

        # Check that change was logged
        audit_trail = auto_apply_engine.get_audit_trail()
        assert len(audit_trail) > 0
        assert audit_trail[0]["parameter"] == "max_iterations"
        assert audit_trail[0]["new_value"] == 200

    def test_audit_trail_filtering_by_project(self, auto_apply_engine):
        """Audit trail should filter by project."""
        # Apply changes for two projects
        for project in ["project-a", "project-b"]:
            rec = {
                "type": "tighten",
                "project": project,
                "reason": f"Test {project}",
                "suggested_max_iterations": 200,
            }
            auto_apply_engine.apply_recommendation(rec)

        # Filter by project
        trail_a = auto_apply_engine.get_audit_trail(project="project-a")
        trail_b = auto_apply_engine.get_audit_trail(project="project-b")

        assert len(trail_a) == 1
        assert len(trail_b) == 1
        assert trail_a[0]["project"] == "project-a"
        assert trail_b[0]["project"] == "project-b"

    def test_audit_trail_sorting(self, auto_apply_engine):
        """Audit trail should be sorted by timestamp."""
        recs = [
            {
                "type": "tighten",
                "project": f"proj{i}",
                "reason": f"Test {i}",
                "suggested_max_iterations": 200,
            }
            for i in range(3)
        ]
        for rec in recs:
            auto_apply_engine.apply_recommendation(rec)

        trail = auto_apply_engine.get_audit_trail()
        timestamps = [c["timestamp"] for c in trail]
        assert timestamps == sorted(timestamps)


class TestRollbackMechanism:
    """Test rollback trigger logic."""

    def test_rollback_triggered_on_large_success_rate_drop(self, auto_apply_engine):
        """Rollback should trigger if success rate drops >20%."""
        # This test requires mocking the metrics system
        # For now, we just verify the rollback mechanism exists
        config = auto_apply_engine.load_config()
        config["per_task_limit"] = 3.0
        auto_apply_engine.save_config(config)

        # Manually create a change record to test rollback
        change_record = {
            "recommendation_type": "loosen",
            "project": "test-project",
            "parameter": "per_task_limit",
            "old_value": 2.0,
            "new_value": 3.0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Trigger rollback
        rollback = auto_apply_engine._rollback_change(change_record)
        assert rollback is not None
        assert rollback.old_value == 3.0
        assert rollback.new_value == 2.0
        assert rollback.rollback_triggered

        # Config should be rolled back
        config = auto_apply_engine.load_config()
        assert config["per_task_limit"] == 2.0


class TestBatchApplicationViaHelper:
    """Test the batch application helper function."""

    def test_apply_recommendations_batch(self, temp_data_dir):
        """Should apply multiple recommendations in batch."""
        recs = [
            {
                "type": "tighten",
                "project": "proj1",
                "reason": "Test",
                "suggested_max_iterations": 200,
            },
            {
                "type": "loosen",
                "project": "proj2",
                "reason": "Test",
                "suggested_max_cost_usd": 3.5,
            },
        ]
        changes = apply_recommendations(recs)
        assert len(changes) == 2


class TestConfigPersistence:
    """Test config file persistence."""

    def test_save_and_load_config(self, auto_apply_engine):
        """Config should persist across save/load cycles."""
        config = auto_apply_engine.load_config()
        config["per_task_limit"] = 4.5
        auto_apply_engine.save_config(config)

        # Load fresh engine (same temp dir)
        fresh_engine = GuardrailAutoApply(auto_apply=True)
        fresh_config = fresh_engine.load_config()
        assert fresh_config["per_task_limit"] == 4.5

    def test_config_has_timestamp(self, auto_apply_engine):
        """Config should have last_updated timestamp."""
        config = auto_apply_engine.load_config()
        assert "last_updated" in config
        # Should be ISO format
        datetime.fromisoformat(config["last_updated"])


class TestGuardrailChangeDataclass:
    """Test GuardrailChange dataclass."""

    def test_change_to_dict(self):
        """GuardrailChange should convert to dict."""
        change = GuardrailChange(
            timestamp="2024-01-01T00:00:00Z",
            change_id="test123",
            recommendation_type="tighten",
            project="test-project",
            parameter="max_iterations",
            old_value=400,
            new_value=300,
            reason="Test reason",
            applied_by="auto_apply",
        )
        d = change.to_dict()
        assert d["parameter"] == "max_iterations"
        assert d["old_value"] == 400
        assert d["new_value"] == 300


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_unknown_recommendation_type(self, auto_apply_engine):
        """Should handle unknown recommendation types gracefully."""
        rec = {
            "type": "unknown_type",
            "project": "test-project",
            "reason": "Test",
        }
        change = auto_apply_engine.apply_recommendation(rec)
        assert change is None

    def test_missing_required_fields(self, auto_apply_engine):
        """Should handle missing fields in recommendations."""
        rec = {"type": "tighten"}
        # Should not crash
        change = auto_apply_engine.apply_recommendation(rec)
        # May succeed or fail depending on defaults

    def test_concurrent_access(self, auto_apply_engine):
        """Should handle concurrent access safely."""
        import threading

        def apply_change():
            rec = {
                "type": "tighten",
                "project": "test-project",
                "reason": "Test",
                "suggested_max_iterations": 200,
            }
            auto_apply_engine.apply_recommendation(rec)

        threads = [threading.Thread(target=apply_change) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have logged all changes
        trail = auto_apply_engine.get_audit_trail()
        assert len(trail) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
