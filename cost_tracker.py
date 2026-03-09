"""
cost_tracker.py — Single source of truth for cost tracking in OpenClaw.

Extracted from gateway.py (was inline) and autonomous_runner.py (was duplicated).
All cost logging, calculation, and summary functions live here.

Primary backend: Supabase (real-time, queryable, multi-device)
Fallback: JSONL file (if Supabase is unreachable)
"""

import json
import os
import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger("cost_tracker")

# ---------------------------------------------------------------------------
# Pricing table (per million tokens, USD)
# ---------------------------------------------------------------------------
COST_PRICING = {
    "claude-haiku-4-5-20251001":  {"input": 0.8,  "output": 4.0},
    "claude-sonnet-4-20250514":   {"input": 3.0,  "output": 15.0},
    "claude-opus-4-6":            {"input": 15.0, "output": 75.0},
    "claude-3-5-haiku-20241022":  {"input": 0.8,  "output": 4.0},
    "claude-3-5-sonnet-20241022": {"input": 3.0,  "output": 15.0},
    "kimi-2.5":                   {"input": 0.14, "output": 0.28},
    "kimi":                       {"input": 0.27, "output": 0.68},
    "m2.5":                       {"input": 0.30, "output": 1.20},
    "gemini-2.5-flash-lite":      {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash":           {"input": 0.30, "output": 2.50},
    "gemini-3-flash-preview":     {"input": 0.00, "output": 0.00},
    "opencode":                    {"input": 0.05, "output": 0.08},
    "grok-3":                      {"input": 3.00, "output": 15.00},
    "grok-3-mini":                 {"input": 0.30, "output": 0.50},
    "grok-code-fast-1":            {"input": 0.30, "output": 0.50},
}

# Default fallback when a model is not in the table
_DEFAULT_PRICING = {"input": 3.0, "output": 15.0}


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _calc_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Return USD cost for the given token counts.
    Handles edge cases like zero or negative tokens to prevent invalid cost calculation.
    """
    if tokens_in < 0 or tokens_out < 0:
        logger.warning(f"Negative token counts provided for model {model}: tokens_in={tokens_in}, tokens_out={tokens_out}. Returning 0 cost.")
        return 0.0
    if tokens_in == 0 and tokens_out == 0:
        return 0.0

    pricing = COST_PRICING.get(model, _DEFAULT_PRICING)
    return round(
        (tokens_in * pricing["input"] + tokens_out * pricing["output"]) / 1_000_000,
        6,
    )


def get_cost_log_path() -> str:
    return os.environ.get(
        "OPENCLAW_COSTS_PATH",
        os.path.join(
            os.environ.get("OPENCLAW_DATA_DIR", "./data"),
            "costs",
            "costs.jsonl",
        ),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_cost(model: str, tokens_input: int, tokens_output: int) -> float:
    """Calculate cost without logging."""
    return _calc_cost(model, tokens_input, tokens_output)


def _sb():
    """Lazy import supabase_client to avoid circular imports."""
    try:
        from supabase_client import table_insert, table_select, is_connected
        return {"insert": table_insert, "select": table_select, "connected": is_connected}
    except Exception:
        return None


def _use_supabase() -> bool:
    try:
        sb = _sb()
        return sb is not None and sb["connected"]()
    except Exception:
        return False


def log_cost_event(
    project: str = "openclaw",
    agent: str = "unknown",
    model: str = "unknown",
    tokens_input: int = 0,
    tokens_output: int = 0,
    cost: float = None,
    event_type: str = "api_call",
    metadata: dict = None,
    job_id: str = None,
    **kwargs,          # absorb unknown kwargs for compat
) -> float:
    """Calculate (or accept) cost, write to Supabase + JSONL fallback, return cost."""
    calculated_cost = cost if cost is not None else _calc_cost(model, tokens_input, tokens_output)

    # Try Supabase first
    if _use_supabase():
        sb = _sb()
        row = {
            "project": project,
            "agent": agent,
            "model": model,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "cost_usd": calculated_cost,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if job_id:
            row["job_id"] = job_id
        result = sb["insert"]("costs", row)
        if result:
            logger.debug(f"Cost logged (Supabase): ${calculated_cost:.6f}")
            return calculated_cost
        logger.warning("Supabase cost insert failed, falling back to JSONL")

    # JSONL fallback
    entry = {
        "timestamp": time.time(),
        "type": event_type,
        "project": project,
        "agent": agent,
        "model": model,
        "tokens_in": tokens_input,
        "tokens_out": tokens_output,
        "cost": calculated_cost,
        "metadata": metadata or {},
    }
    if job_id:
        entry["job_id"] = job_id
    cost_path = get_cost_log_path()
    try:
        os.makedirs(os.path.dirname(cost_path), exist_ok=True)
        with open(cost_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
    return calculated_cost


def get_cost_metrics(days: int = None) -> dict:
    """Read costs and return aggregated metrics. Supabase-first, JSONL fallback."""
    entries = []

    if _use_supabase():
        sb = _sb()
        query = "order=created_at.desc"
        if days:
            cutoff = datetime.now(timezone.utc).isoformat()
            # PostgREST date filter
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            query = f"created_at=gte.{cutoff}&{query}"
        rows = sb["select"]("costs", query, limit=5000)
        if rows is not None:
            for r in rows:
                entries.append({
                    "cost": float(r.get("cost_usd", 0)),
                    "agent": r.get("agent", "unknown"),
                    "project": r.get("project", "unknown"),
                    "model": r.get("model", "unknown"),
                })

    if not entries:
        # JSONL fallback
        cost_path = get_cost_log_path()
        try:
            with open(cost_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except Exception:
                            pass
        except FileNotFoundError:
            pass

    total = sum(e.get("cost", e.get("cost_usd", 0)) for e in entries)
    by_agent: dict = {}
    for e in entries:
        a = e.get("agent", "unknown")
        by_agent[a] = by_agent.get(a, 0) + e.get("cost", e.get("cost_usd", 0))

    return {
        "total_cost":    round(total, 6),
        "entries_count": len(entries),
        "by_agent":      {k: round(v, 6) for k, v in by_agent.items()},
        "daily_total":   round(total, 6),
        "monthly_total": round(total, 6),
        "today_usd":     round(total, 6),
        "month_usd":     round(total, 6),
    }


def get_cost_summary() -> str:
    """One-liner summary string for dashboard/logs."""
    m = get_cost_metrics()
    return f"Total cost: ${m['total_cost']:.4f} across {m['entries_count']} API calls"
