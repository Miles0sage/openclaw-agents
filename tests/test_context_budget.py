"""Tests for context_budget module."""

import pytest
from context_budget import ContextBudgetManager, ContextAction


@pytest.fixture
def mgr():
    return ContextBudgetManager(default_max_messages=100, default_max_tokens=10000)


def test_init_job(mgr):
    state = mgr.init_job("j1", max_messages=50, max_tokens=5000)
    assert state.max_messages == 50
    assert state.max_tokens_estimate == 5000


def test_no_action_under_threshold(mgr):
    mgr.init_job("j1")
    mgr.record_messages("j1", count=10, tokens=500)
    check = mgr.check("j1")
    assert check.action == ContextAction.NONE
    assert check.usage_pct < 70


def test_warn_at_70_pct(mgr):
    mgr.init_job("j1", max_messages=100)
    mgr.record_messages("j1", count=71, tokens=0)
    check = mgr.check("j1")
    assert check.action == ContextAction.WARN
    assert check.usage_pct >= 70


def test_compact_at_85_pct(mgr):
    mgr.init_job("j1", max_messages=100)
    mgr.record_messages("j1", count=86, tokens=0)
    check = mgr.check("j1")
    assert check.action == ContextAction.COMPACT
    assert check.should_compact


def test_checkpoint_restart_at_95_pct(mgr):
    mgr.init_job("j1", max_messages=100)
    mgr.record_messages("j1", count=96, tokens=0)
    check = mgr.check("j1")
    assert check.action == ContextAction.CHECKPOINT_RESTART
    assert check.should_checkpoint_restart


def test_token_based_threshold(mgr):
    mgr.init_job("j1", max_messages=1000, max_tokens=1000)
    mgr.record_messages("j1", count=5, tokens=860)
    check = mgr.check("j1")
    assert check.action == ContextAction.COMPACT
    assert check.should_compact


def test_record_compaction_updates_counts(mgr):
    mgr.init_job("j1", max_messages=100)
    mgr.record_messages("j1", count=90, tokens=9000)
    mgr.record_compaction("j1", old_msg_count=90, new_msg_count=20, old_tokens=9000, new_tokens=2000)
    status = mgr.get_status("j1")
    assert status["messages"] == 20
    assert status["tokens_estimate"] == 2000
    assert status["compactions"] == 1


def test_clear(mgr):
    mgr.init_job("j1")
    mgr.record_messages("j1", count=50)
    mgr.clear("j1")
    # After clear, get_status creates fresh state
    status = mgr.get_status("j1")
    assert status["messages"] == 0


def test_estimate_tokens(mgr):
    tokens = mgr.estimate_tokens("hello world")  # 11 chars
    assert tokens == 2  # 11 // 4


def test_get_all_statuses(mgr):
    mgr.init_job("j1")
    mgr.init_job("j2")
    statuses = mgr.get_all_statuses()
    assert len(statuses) == 2


def test_auto_creates_state_for_unknown_job(mgr):
    mgr.record_messages("unknown-job", count=5)
    status = mgr.get_status("unknown-job")
    assert status["messages"] == 5


def test_compaction_ratio_estimation(mgr):
    """When new_tokens not provided, estimate from ratio."""
    mgr.init_job("j1", max_messages=100)
    mgr.record_messages("j1", count=80, tokens=8000)
    mgr.record_compaction("j1", old_msg_count=80, new_msg_count=20)
    status = mgr.get_status("j1")
    assert status["tokens_estimate"] == 2000  # 8000 * (20/80)


def test_usage_pct_takes_max(mgr):
    """usage_pct should be max of message_pct and token_pct."""
    mgr.init_job("j1", max_messages=100, max_tokens=1000)
    mgr.record_messages("j1", count=10, tokens=900)  # 10% msgs, 90% tokens
    status = mgr.get_status("j1")
    assert status["usage_pct"] == 90.0
