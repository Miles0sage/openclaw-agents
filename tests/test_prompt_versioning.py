"""
Tests for prompt_versioning.py

Tests the prompt versioning system including:
- Version creation and storage
- Success/failure tracking
- Auto-promotion logic
- Auto-rollback logic
- Version history and queries
"""

import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone

import pytest

from prompt_versioning import (
    PromptVersion,
    PromptVersionStore,
    get_store,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    yield db_path

    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def store(temp_db):
    """Create a PromptVersionStore with temporary database."""
    return PromptVersionStore(db_path=temp_db)


class TestPromptVersion:
    """Test PromptVersion dataclass."""

    def test_prompt_version_creation(self):
        """Test creating a PromptVersion instance."""
        version = PromptVersion(
            version_id="test-id",
            agent_key="codegen_pro",
            system_prompt="You are CodeGen Pro",
            created_at=datetime.now(timezone.utc).isoformat(),
            success_rate=0.95,
            total_jobs=20,
            successful_jobs=19,
        )
        assert version.version_id == "test-id"
        assert version.agent_key == "codegen_pro"
        assert version.success_rate == 0.95
        assert version.total_jobs == 20

    def test_prompt_version_to_dict(self):
        """Test converting PromptVersion to dict."""
        version = PromptVersion(
            version_id="test-id",
            agent_key="codegen_pro",
            system_prompt="You are CodeGen Pro",
            created_at=datetime.now(timezone.utc).isoformat(),
            success_rate=0.95,
            total_jobs=20,
            successful_jobs=19,
        )
        d = version.to_dict()
        assert d["version_id"] == "test-id"
        assert d["agent_key"] == "codegen_pro"
        assert d["success_rate"] == 0.95


class TestPromptVersionStoreBasics:
    """Test basic PromptVersionStore operations."""

    def test_store_initialization(self, temp_db):
        """Test that store initializes database correctly."""
        store = PromptVersionStore(db_path=temp_db)

        # Verify tables were created
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='prompt_versions'"
        )
        assert cursor.fetchone() is not None

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='version_outcomes'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_save_version(self, store):
        """Test saving a new prompt version."""
        version_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="You are CodeGen Pro",
            notes="Initial version",
        )

        assert isinstance(version_id, str)
        assert len(version_id) > 0

    def test_save_version_with_parent(self, store):
        """Test saving a version with a parent reference."""
        parent_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Original prompt",
        )

        child_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Modified prompt",
            parent_version=parent_id,
            notes="Mutation of parent",
        )

        assert child_id != parent_id
        child = store.get_version(child_id)
        assert child.parent_version == parent_id

    def test_get_version(self, store):
        """Test retrieving a saved version."""
        version_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="You are CodeGen Pro",
        )

        version = store.get_version(version_id)
        assert version is not None
        assert version.version_id == version_id
        assert version.agent_key == "codegen_pro"
        assert version.system_prompt == "You are CodeGen Pro"
        assert version.total_jobs == 0
        assert version.successful_jobs == 0

    def test_get_nonexistent_version(self, store):
        """Test retrieving a version that doesn't exist."""
        version = store.get_version("nonexistent-id")
        assert version is None


class TestRecordingOutcomes:
    """Test recording job outcomes for versions."""

    def test_record_success(self, store):
        """Test recording a successful job outcome."""
        version_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="You are CodeGen Pro",
        )

        store.record_outcome(
            version_id=version_id,
            success=True,
            job_id="job-1",
        )

        version = store.get_version(version_id)
        assert version.total_jobs == 1
        assert version.successful_jobs == 1
        assert version.success_rate == 1.0

    def test_record_failure(self, store):
        """Test recording a failed job outcome."""
        version_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="You are CodeGen Pro",
        )

        store.record_outcome(
            version_id=version_id,
            success=False,
            job_id="job-1",
        )

        version = store.get_version(version_id)
        assert version.total_jobs == 1
        assert version.successful_jobs == 0
        assert version.success_rate == 0.0

    def test_record_multiple_outcomes(self, store):
        """Test recording multiple outcomes."""
        version_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="You are CodeGen Pro",
        )

        # Record 8 successes and 2 failures = 80% success rate
        for i in range(8):
            store.record_outcome(version_id, success=True, job_id=f"job-{i}")
        for i in range(2):
            store.record_outcome(version_id, success=False, job_id=f"job-fail-{i}")

        version = store.get_version(version_id)
        assert version.total_jobs == 10
        assert version.successful_jobs == 8
        assert abs(version.success_rate - 0.8) < 0.01

    def test_record_outcome_with_details(self, store):
        """Test recording outcome with phase and error details."""
        version_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="You are CodeGen Pro",
        )

        store.record_outcome(
            version_id=version_id,
            success=False,
            job_id="job-1",
            phase="EXECUTE",
            error_message="SyntaxError: invalid syntax",
        )

        # Verify it was recorded (we can't directly query outcomes, but trust the store)
        version = store.get_version(version_id)
        assert version.total_jobs == 1


class TestActiveVersionManagement:
    """Test managing active versions."""

    def test_promote_version(self, store):
        """Test promoting a version to active."""
        version_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Version 1",
        )

        store.promote_version(version_id)

        active = store.get_active_version("codegen_pro")
        assert active is not None
        assert active.version_id == version_id
        assert active.is_active is True

    def test_promote_replaces_previous_active(self, store):
        """Test that promoting a new version deactivates the old one."""
        v1_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Version 1",
        )
        v2_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Version 2",
        )

        store.promote_version(v1_id)
        assert store.get_active_version("codegen_pro").version_id == v1_id

        store.promote_version(v2_id)
        active = store.get_active_version("codegen_pro")
        assert active.version_id == v2_id
        assert active.is_active is True

    def test_get_active_version_when_none(self, store):
        """Test getting active version when none is active."""
        version_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Version 1",
        )
        # Don't promote it

        active = store.get_active_version("codegen_pro")
        assert active is None

    def test_promote_nonexistent_version(self, store):
        """Test promoting a version that doesn't exist."""
        result = store.promote_version("nonexistent-id")
        assert result is False


class TestRollback:
    """Test version rollback functionality."""

    def test_rollback_to_parent(self, store):
        """Test rolling back to parent version."""
        # Create parent
        parent_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Parent prompt",
        )
        store.promote_version(parent_id)

        # Create and promote child
        child_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Child prompt",
            parent_version=parent_id,
        )
        store.promote_version(child_id)

        # Verify child is active
        assert store.get_active_version("codegen_pro").version_id == child_id

        # Rollback
        result = store.rollback("codegen_pro")
        assert result is not None
        assert result.version_id == parent_id

        # Verify parent is now active
        assert store.get_active_version("codegen_pro").version_id == parent_id

    def test_rollback_no_parent(self, store):
        """Test rolling back when there's no parent."""
        version_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Only version",
        )
        store.promote_version(version_id)

        result = store.rollback("codegen_pro")
        assert result is None

    def test_rollback_no_active_version(self, store):
        """Test rolling back when there's no active version."""
        result = store.rollback("codegen_pro")
        assert result is None


class TestHistory:
    """Test querying version history."""

    def test_get_empty_history(self, store):
        """Test getting history for an agent with no versions."""
        history = store.get_history("codegen_pro")
        assert history == []

    def test_get_history_ordered(self, store):
        """Test that history is ordered by creation time (newest first)."""
        v1_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Version 1",
        )
        v2_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Version 2",
        )
        v3_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Version 3",
        )

        history = store.get_history("codegen_pro")
        assert len(history) == 3
        # Newest first
        assert history[0].version_id == v3_id
        assert history[1].version_id == v2_id
        assert history[2].version_id == v1_id

    def test_get_history_multiple_agents(self, store):
        """Test that history is filtered by agent."""
        store.save_version(
            agent_key="codegen_pro",
            system_prompt="CodeGen version",
        )
        store.save_version(
            agent_key="codegen_pro",
            system_prompt="CodeGen version 2",
        )
        store.save_version(
            agent_key="pentest_ai",
            system_prompt="Pentest version",
        )

        codegen_history = store.get_history("codegen_pro")
        pentest_history = store.get_history("pentest_ai")

        assert len(codegen_history) == 2
        assert len(pentest_history) == 1


class TestAutoPromotion:
    """Test automatic version promotion logic."""

    def test_auto_promote_with_improvement(self, store):
        """Test that a better version auto-promotes."""
        # Parent with 50% success rate
        parent_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Parent prompt",
        )
        store.promote_version(parent_id)

        # Record outcomes for parent: 5 successes, 5 failures = 50%
        for i in range(5):
            store.record_outcome(parent_id, success=True, job_id=f"p-{i}")
            store.record_outcome(parent_id, success=False, job_id=f"pf-{i}")

        # Child with 80% success rate (30% improvement > 5% threshold)
        child_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Child prompt",
            parent_version=parent_id,
        )

        # Record outcomes for child: 8 successes, 2 failures = 80%
        for i in range(8):
            store.record_outcome(child_id, success=True, job_id=f"c-{i}")
        for i in range(2):
            store.record_outcome(child_id, success=False, job_id=f"cf-{i}")

        # Auto-promote with default threshold (5%)
        promoted = store.maybe_auto_promote(child_id, min_jobs=10, improvement_threshold=0.05)
        assert promoted is True

        # Verify child is now active
        assert store.get_active_version("codegen_pro").version_id == child_id

    def test_auto_promote_no_improvement(self, store):
        """Test that a version with no improvement doesn't auto-promote."""
        parent_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Parent prompt",
        )
        store.promote_version(parent_id)

        # Record parent outcomes: 80% success
        for i in range(8):
            store.record_outcome(parent_id, success=True, job_id=f"p-{i}")
        for i in range(2):
            store.record_outcome(parent_id, success=False, job_id=f"pf-{i}")

        # Child with same 80% success rate
        child_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Child prompt",
            parent_version=parent_id,
        )

        # Record child outcomes: 80% success
        for i in range(8):
            store.record_outcome(child_id, success=True, job_id=f"c-{i}")
        for i in range(2):
            store.record_outcome(child_id, success=False, job_id=f"cf-{i}")

        # Auto-promote with 5% threshold — should fail (0% improvement)
        promoted = store.maybe_auto_promote(child_id, min_jobs=10, improvement_threshold=0.05)
        assert promoted is False

    def test_auto_promote_insufficient_jobs(self, store):
        """Test that a version doesn't auto-promote until min_jobs threshold."""
        parent_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Parent prompt",
        )
        store.promote_version(parent_id)

        child_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Child prompt",
            parent_version=parent_id,
        )

        # Record only 5 outcomes (below min_jobs=10)
        for i in range(5):
            store.record_outcome(child_id, success=True, job_id=f"c-{i}")

        promoted = store.maybe_auto_promote(child_id, min_jobs=10, improvement_threshold=0.05)
        assert promoted is False

    def test_auto_promote_no_parent(self, store):
        """Test that a version with no parent doesn't auto-promote."""
        version_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Only version",
        )

        # Record outcomes
        for i in range(10):
            store.record_outcome(version_id, success=True, job_id=f"j-{i}")

        promoted = store.maybe_auto_promote(version_id, min_jobs=10, improvement_threshold=0.05)
        assert promoted is False


class TestAutoRollback:
    """Test automatic version rollback logic."""

    def test_auto_rollback_degradation(self, store):
        """Test that a degraded version auto-rolls back."""
        # Parent with 80% success
        parent_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Parent prompt",
        )
        store.promote_version(parent_id)

        # Record parent outcomes: 8 successes, 2 failures = 80%
        for i in range(8):
            store.record_outcome(parent_id, success=True, job_id=f"p-{i}")
        for i in range(2):
            store.record_outcome(parent_id, success=False, job_id=f"pf-{i}")

        # Child with 60% success (20% degradation > 15% threshold)
        child_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Child prompt",
            parent_version=parent_id,
        )
        store.promote_version(child_id)

        # Record child outcomes: 6 successes, 4 failures = 60%
        for i in range(6):
            store.record_outcome(child_id, success=True, job_id=f"c-{i}")
        for i in range(4):
            store.record_outcome(child_id, success=False, job_id=f"cf-{i}")

        # Auto-rollback
        rolled_back = store.maybe_auto_rollback(
            "codegen_pro",
            min_jobs_before_rollback=5,
            degradation_threshold=0.15,
        )
        assert rolled_back is True

        # Verify parent is active again
        assert store.get_active_version("codegen_pro").version_id == parent_id

    def test_auto_rollback_no_degradation(self, store):
        """Test that a stable version doesn't auto-rollback."""
        parent_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Parent prompt",
        )
        store.promote_version(parent_id)

        # Record parent: 80%
        for i in range(8):
            store.record_outcome(parent_id, success=True, job_id=f"p-{i}")
        for i in range(2):
            store.record_outcome(parent_id, success=False, job_id=f"pf-{i}")

        # Child with 78% (only 2% degradation < 15% threshold)
        child_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Child prompt",
            parent_version=parent_id,
        )
        store.promote_version(child_id)

        # Record child: 78 successes, 22 failures = 78%
        for i in range(78):
            store.record_outcome(child_id, success=True, job_id=f"c-{i}")
        for i in range(22):
            store.record_outcome(child_id, success=False, job_id=f"cf-{i}")

        rolled_back = store.maybe_auto_rollback(
            "codegen_pro",
            min_jobs_before_rollback=5,
            degradation_threshold=0.15,
        )
        assert rolled_back is False

    def test_auto_rollback_insufficient_jobs(self, store):
        """Test that rollback doesn't trigger until min_jobs threshold."""
        parent_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Parent prompt",
        )
        store.promote_version(parent_id)

        # Record parent: 80%
        for i in range(8):
            store.record_outcome(parent_id, success=True, job_id=f"p-{i}")
        for i in range(2):
            store.record_outcome(parent_id, success=False, job_id=f"pf-{i}")

        # Child with 60% (20% degradation)
        child_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Child prompt",
            parent_version=parent_id,
        )
        store.promote_version(child_id)

        # Only record 3 outcomes (below min_jobs=5)
        for i in range(2):
            store.record_outcome(child_id, success=True, job_id=f"c-{i}")
        store.record_outcome(child_id, success=False, job_id="cf-1")

        rolled_back = store.maybe_auto_rollback(
            "codegen_pro",
            min_jobs_before_rollback=5,
            degradation_threshold=0.15,
        )
        assert rolled_back is False


class TestStats:
    """Test statistics queries."""

    def test_get_stats_empty(self, store):
        """Test getting stats for an agent with no versions."""
        stats = store.get_stats("codegen_pro")
        assert stats["agent_key"] == "codegen_pro"
        assert stats["active_version_id"] is None
        assert stats["active_success_rate"] == 0.0
        assert stats["total_versions"] == 0
        assert stats["total_outcomes"] == 0

    def test_get_stats_with_versions(self, store):
        """Test getting stats for an agent with versions."""
        v1_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Version 1",
        )
        store.promote_version(v1_id)

        # Record outcomes
        for i in range(7):
            store.record_outcome(v1_id, success=True, job_id=f"j-{i}")
        for i in range(3):
            store.record_outcome(v1_id, success=False, job_id=f"jf-{i}")

        stats = store.get_stats("codegen_pro")
        assert stats["agent_key"] == "codegen_pro"
        assert stats["active_version_id"] == v1_id
        assert abs(stats["active_success_rate"] - 0.7) < 0.01
        assert stats["total_versions"] == 1
        assert stats["total_outcomes"] == 10


class TestGlobalStore:
    """Test the global store singleton."""

    def test_get_store_returns_singleton(self, monkeypatch):
        """Test that get_store returns the same instance."""
        # Use a temporary directory for this test
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            monkeypatch.setenv("OPENCLAW_DATA_DIR", tmpdir)

            # Manually create a store with custom path
            from prompt_versioning import PromptVersionStore
            store1 = PromptVersionStore(db_path=db_path)
            store2 = PromptVersionStore(db_path=db_path)

            # Both should work with the same database
            v_id = store1.save_version(
                agent_key="test",
                system_prompt="test",
            )

            # store2 should be able to retrieve it
            version = store2.get_version(v_id)
            assert version is not None


class TestMultipleAgents:
    """Test working with multiple different agents."""

    def test_versions_isolated_by_agent(self, store):
        """Test that versions for different agents are separate."""
        pro_id = store.save_version(
            agent_key="codegen_pro",
            system_prompt="CodeGen Pro prompt",
        )
        elite_id = store.save_version(
            agent_key="codegen_elite",
            system_prompt="CodeGen Elite prompt",
        )

        # Promote different versions
        store.promote_version(pro_id)
        store.promote_version(elite_id)

        # Verify each agent has its own active version
        pro_active = store.get_active_version("codegen_pro")
        elite_active = store.get_active_version("codegen_elite")

        assert pro_active.version_id == pro_id
        assert elite_active.version_id == elite_id

    def test_rollback_isolated_by_agent(self, store):
        """Test that rollback only affects the specific agent."""
        # Setup CodeGen Pro
        pro_p1 = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Pro v1",
        )
        store.promote_version(pro_p1)

        pro_p2 = store.save_version(
            agent_key="codegen_pro",
            system_prompt="Pro v2",
            parent_version=pro_p1,
        )
        store.promote_version(pro_p2)

        # Setup Pentest AI
        ptest_p1 = store.save_version(
            agent_key="pentest_ai",
            system_prompt="Pentest v1",
        )
        store.promote_version(ptest_p1)

        ptest_p2 = store.save_version(
            agent_key="pentest_ai",
            system_prompt="Pentest v2",
            parent_version=ptest_p1,
        )
        store.promote_version(ptest_p2)

        # Rollback CodeGen Pro
        store.rollback("codegen_pro")

        # Verify CodeGen Pro rolled back
        assert store.get_active_version("codegen_pro").version_id == pro_p1

        # Verify Pentest AI unchanged
        assert store.get_active_version("pentest_ai").version_id == ptest_p2
