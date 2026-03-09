"""
cost_breakdown.py — Per-job, per-tool, per-agent cost aggregation for OpenClaw.

Provides detailed cost breakdowns by phase, agent, model, and tool.
Integrates with cost_tracker for pricing and supabase_client for data access.
Handles missing data gracefully with JSONL fallback.
"""

import json
import os
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional, Callable, Any

logger = logging.getLogger("cost_breakdown")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_jsonl(path: str, filter_fn: Optional[Callable[[dict], bool]] = None) -> list:
    """
    Read JSONL file, optionally filter entries, return list of dicts.
    Handles missing files gracefully.
    """
    if not os.path.exists(path):
        return []

    entries = []
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        if filter_fn is None or filter_fn(entry):
                            entries.append(entry)
                    except (json.JSONDecodeError, ValueError):
                        pass
    except Exception as e:
        logger.warning(f"Error reading JSONL from {path}: {e}")
    return entries


def _get_supabase_costs(job_id: str) -> list:
    """
    Attempt to read costs from Supabase for a given job_id.
    Returns empty list if Supabase unavailable.
    """
    try:
        from supabase_client import table_select
        rows = table_select("costs", f"job_id=eq.{job_id}", limit=1000)
        if rows:
            return rows
    except Exception as e:
        logger.debug(f"Supabase cost fetch for {job_id} failed: {e}")
    return []


def _get_supabase_project_costs(project: str, days: int = 7) -> list:
    """
    Fetch all costs for a project from Supabase within the last N days.
    Returns empty list if Supabase unavailable.
    """
    try:
        from supabase_client import table_select
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        query = f"project=eq.{project}&created_at=gte.{cutoff}"
        rows = table_select("costs", query, limit=5000)
        if rows:
            return rows
    except Exception as e:
        logger.debug(f"Supabase project cost fetch for {project} failed: {e}")
    return []


def _normalize_cost_entry(entry: dict) -> dict:
    """
    Normalize cost entry field names (Supabase vs JSONL differences).
    Returns a dict with consistent keys: cost, agent, project, model, job_id, timestamp.
    """
    return {
        "cost": float(entry.get("cost_usd") or entry.get("cost", 0)),
        "agent": entry.get("agent", "unknown"),
        "project": entry.get("project", "unknown"),
        "model": entry.get("model", "unknown"),
        "job_id": entry.get("job_id", ""),
        "timestamp": entry.get("created_at") or entry.get("timestamp", ""),
        "tokens_input": entry.get("tokens_input") or entry.get("tokens_in", 0),
        "tokens_output": entry.get("tokens_output") or entry.get("tokens_out", 0),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_job_cost_breakdown(job_id: str) -> dict:
    """
    Get detailed cost breakdown for a specific job.

    Returns:
        {
            "total_cost": $X.XX,
            "entries_count": N,
            "by_phase": {"research": $x, "execute": $y, ...},
            "by_agent": {"overseer": $x, "coder": $y, ...},
            "by_model": {"claude-opus-4-6": $x, ...},
            "by_tool": {
                "shell_execute": {
                    "count": N,
                    "total_cost": $X.XX,
                    "avg_elapsed_s": Y.Y
                },
                ...
            },
            "details": [list of individual cost entries]
        }
    """
    entries = []

    # Try Supabase first
    sb_entries = _get_supabase_costs(job_id)
    if sb_entries:
        entries = [_normalize_cost_entry(e) for e in sb_entries]
    else:
        # JSONL fallback
        from cost_tracker import get_cost_log_path
        cost_path = get_cost_log_path()
        entries = _read_jsonl(cost_path, lambda e: e.get("job_id") == job_id)
        entries = [_normalize_cost_entry(e) for e in entries]

    # Aggregate by phase, agent, model
    by_phase = defaultdict(float)
    by_agent = defaultdict(float)
    by_model = defaultdict(float)
    total_cost = 0.0

    # Load tool audit to correlate phases and tool metrics
    tool_audit = get_tool_usage_breakdown(job_id)

    for entry in entries:
        cost = entry["cost"]
        total_cost += cost
        by_agent[entry["agent"]] += cost
        by_model[entry["model"]] += cost

    # Map tools to phases from audit log
    by_tool = defaultdict(lambda: {"count": 0, "total_cost": 0.0, "avg_elapsed_s": 0.0, "elapsed_sum": 0.0})
    for tool_name, tool_data in tool_audit.get("by_tool", {}).items():
        by_tool[tool_name] = {
            "count": tool_data.get("count", 0),
            "total_cost": 0.0,  # Will aggregate from cost entries
            "avg_elapsed_s": tool_data.get("avg_elapsed_s", 0.0),
        }

    # Try to match tool costs if we have phase info from audit
    phase_costs = defaultdict(float)
    if tool_audit.get("by_phase"):
        # Group entries by phase from audit log
        for tool_name, tool_data in tool_audit["by_phase"].items():
            phase_costs[tool_name] = 0.0  # Will be computed

    # Build by_phase from audit log phases
    for phase_name, phase_data in tool_audit.get("by_phase", {}).items():
        by_phase[phase_name] = 0.0  # Placeholder - costs aren't directly tied to phases in cost entries

    # Distribute costs proportionally if phases are available
    total_calls = tool_audit.get("total_calls", 0)
    if total_calls > 0 and tool_audit.get("by_tool"):
        cost_per_call = total_cost / total_calls if total_calls > 0 else 0
        for tool_name, tool_data in tool_audit.get("by_tool", {}).items():
            count = tool_data.get("count", 0)
            by_tool[tool_name]["total_cost"] = round(count * cost_per_call, 6)

    return {
        "job_id": job_id,
        "total_cost": round(total_cost, 6),
        "entries_count": len(entries),
        "by_phase": {k: round(v, 6) for k, v in by_phase.items()},
        "by_agent": {k: round(v, 6) for k, v in by_agent.items()},
        "by_model": {k: round(v, 6) for k, v in by_model.items()},
        "by_tool": {
            k: {
                "count": v["count"],
                "total_cost": round(v["total_cost"], 6),
                "avg_elapsed_s": round(v["avg_elapsed_s"], 3),
            }
            for k, v in by_tool.items()
        },
        "details": entries,
    }


def get_tool_usage_breakdown(job_id: str) -> dict:
    """
    Get tool usage breakdown from the audit log for a specific job.

    Returns:
        {
            "job_id": "abc123",
            "total_calls": N,
            "by_phase": {
                "research": {"count": N, "tools": [...]},
                "execute": {"count": N, "tools": [...]},
            },
            "by_tool": {
                "shell_execute": {
                    "count": N,
                    "avg_elapsed_s": Y.Y,
                    "by_status": {"success": N, "rejected": N, ...},
                    "by_risk_level": {"low": N, "high": N, ...},
                },
                ...
            },
            "by_risk_level": {"low": N, "high": N, ...},
            "by_status": {"success": N, "rejected": N, ...},
            "timeline": [list of tool calls in chronological order]
        }
    """
    audit_path = "os.environ.get("OPENCLAW_DATA_DIR", "./data")/audit/tool_calls.jsonl"
    entries = _read_jsonl(audit_path, lambda e: e.get("job_id") == job_id)

    if not entries:
        return {
            "job_id": job_id,
            "total_calls": 0,
            "by_phase": {},
            "by_tool": {},
            "by_risk_level": {},
            "by_status": {},
            "timeline": [],
        }

    # Sort by timestamp for timeline
    entries = sorted(entries, key=lambda e: e.get("timestamp", 0))

    by_phase = defaultdict(lambda: {"count": 0, "tools": []})
    by_tool = defaultdict(
        lambda: {
            "count": 0,
            "total_elapsed_s": 0.0,
            "avg_elapsed_s": 0.0,
            "by_status": defaultdict(int),
            "by_risk_level": defaultdict(int),
        }
    )
    by_risk_level = defaultdict(int)
    by_status = defaultdict(int)

    for entry in entries:
        phase = entry.get("phase", "unknown")
        tool = entry.get("tool", "unknown")
        status = entry.get("status", "unknown")
        risk = entry.get("risk_level", "unknown")
        elapsed = entry.get("elapsed_s", 0.0)

        # Count by phase
        by_phase[phase]["count"] += 1
        if tool not in by_phase[phase]["tools"]:
            by_phase[phase]["tools"].append(tool)

        # Count by tool
        by_tool[tool]["count"] += 1
        by_tool[tool]["total_elapsed_s"] += elapsed
        by_tool[tool]["by_status"][status] += 1
        by_tool[tool]["by_risk_level"][risk] += 1

        # Count by risk and status
        by_risk_level[risk] += 1
        by_status[status] += 1

    # Compute averages
    for tool_name, tool_data in by_tool.items():
        if tool_data["count"] > 0:
            tool_data["avg_elapsed_s"] = tool_data["total_elapsed_s"] / tool_data["count"]
        del tool_data["total_elapsed_s"]  # Remove intermediate

    return {
        "job_id": job_id,
        "total_calls": len(entries),
        "by_phase": {
            k: {
                "count": v["count"],
                "tools": v["tools"],
            }
            for k, v in by_phase.items()
        },
        "by_tool": {
            k: {
                "count": v["count"],
                "avg_elapsed_s": round(v["avg_elapsed_s"], 3),
                "by_status": dict(v["by_status"]),
                "by_risk_level": dict(v["by_risk_level"]),
            }
            for k, v in by_tool.items()
        },
        "by_risk_level": dict(by_risk_level),
        "by_status": dict(by_status),
        "timeline": entries,
    }


def get_project_cost_summary(project: Optional[str] = None, days: int = 7) -> dict:
    """
    Aggregate costs across all jobs for a project (or all projects if None).

    Args:
        project: Project name, or None for all projects
        days: Look back N days

    Returns:
        {
            "total_cost": $X.XX,
            "job_count": N,
            "avg_cost_per_job": $Y.YY,
            "by_project": {
                "openclaw": {
                    "total_cost": $X.XX,
                    "job_count": N,
                    "avg_cost_per_job": $Y.YY,
                },
                ...
            },
            "by_agent": {"overseer": $x, ...},
            "by_model": {"claude-opus-4-6": $x, ...},
            "period_days": N,
            "entries_count": N,
        }
    """
    entries = []

    # Try Supabase first
    if project:
        sb_entries = _get_supabase_project_costs(project, days)
        if sb_entries:
            entries = [_normalize_cost_entry(e) for e in sb_entries]
    else:
        # Fetch all projects from Supabase
        try:
            from supabase_client import table_select
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            query = f"created_at=gte.{cutoff}"
            rows = table_select("costs", query, limit=5000)
            if rows:
                entries = [_normalize_cost_entry(e) for e in rows]
        except Exception as e:
            logger.debug(f"Supabase project summary fetch failed: {e}")

    # JSONL fallback if no Supabase data
    if not entries:
        from cost_tracker import get_cost_log_path
        cost_path = get_cost_log_path()
        all_entries = _read_jsonl(cost_path)

        # Filter by project and date
        cutoff = datetime.now() - timedelta(days=days)
        for entry in all_entries:
            entry = _normalize_cost_entry(entry)
            if project and entry["project"] != project:
                continue
            # Try to parse timestamp
            try:
                ts = entry.get("timestamp")
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                elif isinstance(ts, (int, float)):
                    pass
                else:
                    ts = 0
                if ts >= cutoff.timestamp():
                    entries.append(entry)
            except Exception:
                entries.append(entry)  # Include if can't parse timestamp

    # Aggregate
    by_project = defaultdict(lambda: {"total_cost": 0.0, "job_count": 0, "jobs": set()})
    by_agent = defaultdict(float)
    by_model = defaultdict(float)
    total_cost = 0.0
    all_jobs = set()

    for entry in entries:
        proj = entry["project"]
        cost = entry["cost"]
        job_id = entry.get("job_id", "")

        total_cost += cost
        by_agent[entry["agent"]] += cost
        by_model[entry["model"]] += cost

        by_project[proj]["total_cost"] += cost
        if job_id:
            by_project[proj]["jobs"].add(job_id)
            all_jobs.add(job_id)

    # Compute job counts and averages
    for proj_data in by_project.values():
        proj_data["job_count"] = len(proj_data["jobs"])
        del proj_data["jobs"]
        avg = proj_data["total_cost"] / proj_data["job_count"] if proj_data["job_count"] > 0 else 0
        proj_data["avg_cost_per_job"] = round(avg, 6)
        proj_data["total_cost"] = round(proj_data["total_cost"], 6)

    job_count = len(all_jobs)
    avg_per_job = total_cost / job_count if job_count > 0 else 0

    return {
        "total_cost": round(total_cost, 6),
        "job_count": job_count,
        "avg_cost_per_job": round(avg_per_job, 6),
        "by_project": dict(by_project),
        "by_agent": {k: round(v, 6) for k, v in by_agent.items()},
        "by_model": {k: round(v, 6) for k, v in by_model.items()},
        "period_days": days,
        "entries_count": len(entries),
    }


# ---------------------------------------------------------------------------
# CLI / Debug
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG)

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python cost_breakdown.py job <job_id>")
        print("  python cost_breakdown.py tools <job_id>")
        print("  python cost_breakdown.py project [project_name] [days]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "job":
        job_id = sys.argv[2] if len(sys.argv) > 2 else "test"
        result = get_job_cost_breakdown(job_id)
        print(json.dumps(result, indent=2, default=str))

    elif cmd == "tools":
        job_id = sys.argv[2] if len(sys.argv) > 2 else "test"
        result = get_tool_usage_breakdown(job_id)
        print(json.dumps(result, indent=2, default=str))

    elif cmd == "project":
        proj = sys.argv[2] if len(sys.argv) > 2 else None
        days = int(sys.argv[3]) if len(sys.argv) > 3 else 7
        result = get_project_cost_summary(proj, days)
        print(json.dumps(result, indent=2, default=str))

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
