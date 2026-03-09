"""Tests for pool_config — agent-to-pool routing."""
import os
import pytest
from pool_config import (
    get_current_pool,
    get_pool_agents,
    get_pool_concurrency,
    agent_belongs_to_pool,
    AGENT_POOL_MAP,
    DEFAULT_POOL,
)


def test_default_pool_is_p2(monkeypatch):
    monkeypatch.delenv("OPENCLAW_POOL", raising=False)
    assert get_current_pool() == "p2"


def test_pool_env_var_p0(monkeypatch):
    monkeypatch.setenv("OPENCLAW_POOL", "p0")
    assert get_current_pool() == "p0"


def test_pool_env_var_p1(monkeypatch):
    monkeypatch.setenv("OPENCLAW_POOL", "p1")
    assert get_current_pool() == "p1"


def test_pool_env_var_case_insensitive(monkeypatch):
    monkeypatch.setenv("OPENCLAW_POOL", "P2")
    assert get_current_pool() == "p2"


def test_invalid_pool_raises(monkeypatch):
    monkeypatch.setenv("OPENCLAW_POOL", "p9")
    with pytest.raises(ValueError, match="Invalid OPENCLAW_POOL"):
        get_current_pool()


def test_p0_agents_include_overseer():
    agents = get_pool_agents("p0")
    assert "overseer" in agents
    assert "supabase_connector" in agents
    assert "debugger" in agents
    assert "codegen_elite" in agents


def test_p1_agents_include_pentest():
    agents = get_pool_agents("p1")
    assert "pentest_ai" in agents


def test_p2_agents_include_cheap():
    agents = get_pool_agents("p2")
    assert "codegen_pro" in agents
    assert "researcher" in agents
    assert "content_creator" in agents


def test_all_agents_assigned_to_a_pool():
    """Every agent in the map belongs to exactly one pool."""
    all_agents = set(AGENT_POOL_MAP.keys())
    covered = get_pool_agents("p0") | get_pool_agents("p1") | get_pool_agents("p2")
    assert all_agents == covered


def test_no_agent_in_multiple_pools():
    """No agent should appear in two different pools."""
    p0 = get_pool_agents("p0")
    p1 = get_pool_agents("p1")
    p2 = get_pool_agents("p2")
    assert p0 & p1 == set()
    assert p0 & p2 == set()
    assert p1 & p2 == set()


def test_pool_concurrency_p0():
    assert get_pool_concurrency("p0") == 2


def test_pool_concurrency_p2():
    assert get_pool_concurrency("p2") == 5


def test_agent_belongs_to_pool_true():
    assert agent_belongs_to_pool("overseer", "p0") is True
    assert agent_belongs_to_pool("codegen_pro", "p2") is True
    assert agent_belongs_to_pool("pentest_ai", "p1") is True


def test_agent_belongs_to_pool_false():
    assert agent_belongs_to_pool("overseer", "p2") is False
    assert agent_belongs_to_pool("codegen_pro", "p0") is False


def test_unknown_agent_defaults_to_p2():
    """Agents not in the map default to P2 (cheapest fallback)."""
    assert agent_belongs_to_pool("some_new_agent", "p2") is True
    assert agent_belongs_to_pool("some_new_agent", "p0") is False
