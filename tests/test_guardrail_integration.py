"""
Integration tests: Auto-apply engine basic functionality.
Tests applied recommendations and their effects.
"""

import json
import tempfile
from pathlib import Path
from guardrail_auto_apply import GuardrailAutoApply, GuardrailChange


class TestGuardrailChangeDataclass:
    """Test GuardrailChange dataclass functionality."""

    def test_change_serialization(self):
        """GuardrailChange should serialize to dict."""
        change = GuardrailChange(
            timestamp="2026-03-08T00:00:00Z",
            change_id="test-123",
            recommendation_type="tighten",
            project="test-proj",
            parameter="max_iterations",
            old_value=400,
            new_value=300,
            reason="Low success",
            applied_by="auto_apply",
        )
        d = change.to_dict()
        assert d["parameter"] == "max_iterations"
        assert d["old_value"] == 400
        assert d["new_value"] == 300


class TestAutoApplyEngineValidation:
    """Test validation logic in isolation."""

    def test_validation_per_task_budget(self):
        """Test per-task budget validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            os.environ["OPENCLAW_DATA_DIR"] = tmpdir
            Path(tmpdir, "costs").mkdir(exist_ok=True)

            engine = GuardrailAutoApply(auto_apply=True)

            # Min bound check
            is_valid, clamped, reason = engine._validate_and_clamp(
                "per_task_limit", 0.25, 2.0
            )
            assert not is_valid
            assert clamped == 2.0

            # Max bound check
            is_valid, clamped, reason = engine._validate_and_clamp(
                "per_task_limit", 10.0, 2.0
            )
            assert is_valid
            assert clamped == 5.0

    def test_validation_daily_budget(self):
        """Test daily budget validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            os.environ["OPENCLAW_DATA_DIR"] = tmpdir
            Path(tmpdir, "costs").mkdir(exist_ok=True)

            engine = GuardrailAutoApply(auto_apply=True)

            # Max bound check
            is_valid, clamped, reason = engine._validate_and_clamp(
                "daily_limit", 100.0, 50.0
            )
            assert is_valid
            assert clamped == 50.0

    def test_validation_iteration_limit(self):
        """Test iteration limit validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            os.environ["OPENCLAW_DATA_DIR"] = tmpdir
            Path(tmpdir, "costs").mkdir(exist_ok=True)

            engine = GuardrailAutoApply(auto_apply=True)

            # Min bound check
            is_valid, clamped, reason = engine._validate_and_clamp(
                "max_iterations", 2, 400
            )
            assert not is_valid


class TestRecommendationTypes:
    """Test different recommendation types."""

    def test_tighten_recommendation_modifies_config(self):
        """Tighten rec should reduce iteration limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            os.environ["OPENCLAW_DATA_DIR"] = tmpdir
            Path(tmpdir, "costs").mkdir(exist_ok=True)

            engine = GuardrailAutoApply(auto_apply=True)
            original_config = engine.load_config()

            rec = {
                "type": "tighten",
                "project": "test",
                "reason": "Low success",
                "suggested_max_iterations": 200,
            }
            change = engine.apply_recommendation(rec)

            assert change is not None
            assert change.new_value == 200
            updated_config = engine.load_config()
            assert updated_config["max_iterations"] == 200

    def test_loosen_recommendation_modifies_config(self):
        """Loosen rec should increase per-task budget."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            os.environ["OPENCLAW_DATA_DIR"] = tmpdir
            Path(tmpdir, "costs").mkdir(exist_ok=True)

            engine = GuardrailAutoApply(auto_apply=True)

            rec = {
                "type": "loosen",
                "project": "test",
                "reason": "High success",
                "suggested_max_cost_usd": 3.5,
            }
            change = engine.apply_recommendation(rec)

            assert change is not None
            assert change.new_value == 3.5
            updated_config = engine.load_config()
            assert updated_config["per_task_limit"] == 3.5

    def test_increase_budget_recommendation_modifies_config(self):
        """Increase budget rec should raise daily limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            os.environ["OPENCLAW_DATA_DIR"] = tmpdir
            Path(tmpdir, "costs").mkdir(exist_ok=True)

            engine = GuardrailAutoApply(auto_apply=True)

            # Lower initial daily limit
            config = engine.load_config()
            config["daily_limit"] = 30.0
            engine.save_config(config)

            rec = {
                "type": "increase_budget",
                "project": "test",
                "reason": "Budget kills",
            }
            change = engine.apply_recommendation(rec)

            assert change is not None
            # Should be increased (20% of 30 = 36 minimum)
            assert change.new_value >= 36.0


class TestAutoApplyDisabled:
    """Test behavior when auto_apply is False."""

    def test_disabled_prevents_application(self):
        """When disabled, recommendations should not be applied."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            os.environ["OPENCLAW_DATA_DIR"] = tmpdir
            Path(tmpdir, "costs").mkdir(exist_ok=True)

            engine = GuardrailAutoApply(auto_apply=False)

            rec = {
                "type": "tighten",
                "project": "test",
                "reason": "Test",
                "suggested_max_iterations": 200,
            }

            change = engine.apply_recommendation(rec)
            # Should return None when disabled
            assert change is None


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
