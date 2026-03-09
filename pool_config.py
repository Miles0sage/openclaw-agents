"""
OpenClaw v5 — Worker Pool Configuration
========================================
Defines the 3 priority pools and which agents each pool owns.

Usage:
    OPENCLAW_POOL=p0 python3 autonomous_runner.py   # P0 worker (expensive agents)
    OPENCLAW_POOL=p1 python3 autonomous_runner.py   # P1 worker (mid-tier agents)
    OPENCLAW_POOL=p2 autonomous_runner.py           # P2 worker (cheap agents, default)

Pool design:
    P0 — High-cost, high-capability: Opus 4.6 class agents.
         Max concurrency: 2 (expensive, don't parallelize aggressively)
         Fault isolation: P0 crash does not affect P1/P2 jobs.

    P1 — Mid-tier: Extended-thinking models, security specialists.
         Max concurrency: 3

    P2 — Cheap bulk workers: Kimi 2.5 / fast models.
         Max concurrency: 5 (cheap, safe to parallelize)
         Default pool when OPENCLAW_POOL is not set.
"""

import os

# Agent key → pool assignment
# Keys must match CLAUDE.md agent names exactly (lowercased with underscores)
AGENT_POOL_MAP: dict[str, str] = {
    # P0 — Expensive agents (Opus 4.6, MiniMax M2.5)
    "overseer": "p0",
    "supabase_connector": "p0",
    "debugger": "p0",
    "codegen_elite": "p0",
    "architecture_designer": "p0",

    # P1 — Mid-tier (extended thinking, security)
    "pentest_ai": "p1",

    # P2 — Cheap bulk agents (Kimi 2.5 / fast models)
    "codegen_pro": "p2",
    "researcher": "p2",
    "content_creator": "p2",
    "financial_analyst": "p2",
    "code_reviewer": "p2",
    "test_generator": "p2",
    "betting_bot": "p2",
}

# Pool concurrency limits
POOL_CONCURRENCY: dict[str, int] = {
    "p0": 2,
    "p1": 3,
    "p2": 5,
}

# Default pool if env var not set
DEFAULT_POOL = "p2"


def get_current_pool() -> str:
    """Return pool name for this worker instance (from env var)."""
    pool = os.getenv("OPENCLAW_POOL", DEFAULT_POOL).lower().strip()
    if pool not in ("p0", "p1", "p2"):
        raise ValueError(
            f"Invalid OPENCLAW_POOL={pool!r}. Must be one of: p0, p1, p2"
        )
    return pool


def get_pool_agents(pool: str) -> set[str]:
    """Return the set of agent keys owned by this pool."""
    return {agent for agent, p in AGENT_POOL_MAP.items() if p == pool}


def get_pool_concurrency(pool: str) -> int:
    """Return max concurrent jobs for this pool."""
    return POOL_CONCURRENCY.get(pool, 3)


def agent_belongs_to_pool(agent_key: str, pool: str) -> bool:
    """Check if an agent key belongs to the given pool.

    Unknown agents (not in map) fall through to P2 as default.
    """
    assigned = AGENT_POOL_MAP.get(agent_key, DEFAULT_POOL)
    return assigned == pool
