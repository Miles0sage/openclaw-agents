"""
OpenClaw Analytics Router
Real-time metrics and performance analytics from event logs
"""

import json
import logging
import pathlib
import os
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from routers.shared import logger, CONFIG

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# Configuration
DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")


def parse_event_log(log_path: pathlib.Path, limit: int = 10000) -> List[Dict[str, Any]]:
    """Parse JSONL event log file"""
    events = []
    if not log_path.exists():
        return events

    try:
        with open(log_path, 'r') as f:
            for line in f:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.error(f"Error parsing events: {e}")

    return events[-limit:]  # Return most recent


@router.get("/agents")
async def get_agent_analytics():
    """Agent performance statistics from event logs"""
    try:
        events_file = pathlib.Path(DATA_DIR) / "events" / "events.jsonl"
        events = parse_event_log(events_file)

        agent_stats = {}

        # Parse job completion events
        for event in events:
            try:
                data = event.get("data", {})
                event_type = event.get("event_type", "")

                # Look for job completion events
                if "job" in event_type and "completed" in event_type:
                    agent = data.get("agent", "unknown")
                    if agent not in agent_stats:
                        agent_stats[agent] = {
                            "jobs": 0,
                            "success": 0,
                            "failed": 0,
                            "total_cost": 0.0,
                            "total_duration": 0.0
                        }

                    agent_stats[agent]["jobs"] += 1
                    if data.get("status") == "done":
                        agent_stats[agent]["success"] += 1
                    else:
                        agent_stats[agent]["failed"] += 1

                    agent_stats[agent]["total_cost"] += float(data.get("cost_usd", 0))
                    agent_stats[agent]["total_duration"] += float(data.get("duration", 0))
            except Exception:
                continue

        # Calculate averages
        for agent, stats in agent_stats.items():
            if stats["jobs"] > 0:
                stats["success_rate"] = round((stats["success"] / stats["jobs"]) * 100, 1)
                stats["avg_duration"] = round(stats["total_duration"] / stats["jobs"], 2)
                stats["avg_cost"] = round(stats["total_cost"] / stats["jobs"], 4)
            else:
                stats["success_rate"] = 0
                stats["avg_duration"] = 0
                stats["avg_cost"] = 0

        return {
            "agent_stats": agent_stats,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Error in agent analytics: {e}")
        return {"agent_stats": {}, "error": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/costs")
async def get_cost_analytics():
    """Cost tracking with daily/weekly breakdown"""
    try:
        events_file = pathlib.Path(DATA_DIR) / "events" / "events.jsonl"
        events = parse_event_log(events_file)

        daily_costs = {}
        agent_costs = {}
        total_cost = 0.0

        # Parse cost events
        for event in events:
            try:
                timestamp = event.get("timestamp", "")
                data = event.get("data", {})

                # Extract date
                if timestamp:
                    date_key = timestamp.split("T")[0]
                else:
                    continue

                cost = float(data.get("cost_usd", 0))
                agent = data.get("agent", "unknown")

                if cost > 0:
                    total_cost += cost

                    if date_key not in daily_costs:
                        daily_costs[date_key] = 0.0
                    daily_costs[date_key] += cost

                    if agent not in agent_costs:
                        agent_costs[agent] = 0.0
                    agent_costs[agent] += cost
            except Exception:
                continue

        # Calculate weekly costs
        weekly_costs = {}
        for date_str, cost in sorted(daily_costs.items()):
            try:
                date_obj = datetime.fromisoformat(date_str)
                week_key = f"week_{date_obj.isocalendar()[1]}"
                if week_key not in weekly_costs:
                    weekly_costs[week_key] = 0.0
                weekly_costs[week_key] += cost
            except Exception:
                continue

        return {
            "total_cost": round(total_cost, 4),
            "daily_costs": {k: round(v, 4) for k, v in sorted(daily_costs.items())[-30:]},
            "weekly_costs": {k: round(v, 4) for k, v in weekly_costs.items()},
            "by_agent": {k: round(v, 4) for k, v in sorted(agent_costs.items(), key=lambda x: x[1], reverse=True)},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Error in cost analytics: {e}")
        return {"total_cost": 0, "error": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/jobs")
async def get_job_analytics(status: Optional[str] = None, agent: Optional[str] = None, limit: int = 50):
    """Recent job history with filters"""
    try:
        events_file = pathlib.Path(DATA_DIR) / "events" / "events.jsonl"
        events = parse_event_log(events_file, limit=10000)

        jobs = []

        # Extract job events
        for event in events:
            try:
                event_type = event.get("event_type", "")
                data = event.get("data", {})
                timestamp = event.get("timestamp", "")

                # Look for job-related events
                if "job" in event_type or "task" in event_type:
                    job_data = {
                        "id": event.get("event_id", ""),
                        "agent": data.get("agent", "unknown"),
                        "status": data.get("status", "unknown"),
                        "duration": float(data.get("duration", 0)),
                        "cost": round(float(data.get("cost_usd", 0)), 4),
                        "timestamp": timestamp,
                        "event_type": event_type
                    }

                    # Apply filters
                    if status and job_data["status"] != status:
                        continue
                    if agent and job_data["agent"] != agent:
                        continue

                    jobs.append(job_data)
            except Exception:
                continue

        # Sort by timestamp descending
        jobs = sorted(jobs, key=lambda x: x["timestamp"], reverse=True)[:limit]

        return {
            "jobs": jobs,
            "count": len(jobs),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Error in job analytics: {e}")
        return {"jobs": [], "count": 0, "error": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}


# ═══════════════════════════════════════════════════════════════════════
# Streaming SSE endpoint
# ═══════════════════════════════════════════════════════════════════════

@router.get("/stream/{job_id}")
async def stream_job(job_id: str):
    """Stream real-time job progress via Server-Sent Events."""
    try:
        from streaming import get_stream_manager
        mgr = get_stream_manager()
        return StreamingResponse(
            mgr.stream_job(job_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as e:
        logger.error(f"Stream error for job {job_id}: {e}")
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# Tracing endpoints
# ═══════════════════════════════════════════════════════════════════════

@router.get("/traces/recent")
async def get_recent_traces(limit: int = Query(20, ge=1, le=100)):
    """Get summaries of recent job traces."""
    try:
        from otel_tracer import get_tracer
        tracer = get_tracer()
        return {"traces": tracer.get_recent_traces(limit=limit)}
    except Exception as e:
        logger.error(f"Error fetching traces: {e}")
        return {"traces": [], "error": str(e)}


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str):
    """Get all spans for a specific trace (job)."""
    try:
        from otel_tracer import get_tracer
        tracer = get_tracer()
        spans = tracer.get_trace(trace_id)
        summary = tracer.get_trace_summary(trace_id)
        return {"trace_id": trace_id, "spans": spans, "summary": summary}
    except Exception as e:
        logger.error(f"Error fetching trace {trace_id}: {e}")
        return {"trace_id": trace_id, "spans": [], "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# Knowledge Graph endpoints
# ═══════════════════════════════════════════════════════════════════════

@router.get("/kg/summary")
async def kg_summary():
    """Get knowledge graph overview statistics."""
    try:
        from kg_engine import get_kg_engine
        kg = get_kg_engine()
        return kg.get_graph_summary()
    except Exception as e:
        logger.error(f"KG summary error: {e}")
        return {"error": str(e)}


@router.get("/kg/recommend")
async def kg_recommend(agent: str = "", task_type: str = "", limit: int = 5):
    """Get tool chain recommendations from the knowledge graph."""
    try:
        from kg_engine import get_kg_engine
        kg = get_kg_engine()
        recs = kg.recommend_tools(agent_key=agent, task_type=task_type, limit=limit)
        return {"recommendations": [r.to_dict() for r in recs]}
    except Exception as e:
        logger.error(f"KG recommend error: {e}")
        return {"recommendations": [], "error": str(e)}


@router.get("/kg/tools")
async def kg_tool_stats(limit: int = 20):
    """Get tool usage statistics from the knowledge graph."""
    try:
        from kg_engine import get_kg_engine
        kg = get_kg_engine()
        return {"tools": kg.get_tool_stats(limit=limit)}
    except Exception as e:
        logger.error(f"KG tools error: {e}")
        return {"tools": [], "error": str(e)}


@router.get("/kg/agent/{agent_key}")
async def kg_agent_performance(agent_key: str, task_type: str = ""):
    """Get performance stats for a specific agent."""
    try:
        from kg_engine import get_kg_engine
        kg = get_kg_engine()
        perf = kg.get_agent_performance(agent_key, task_type=task_type)
        return perf.to_dict() if perf else {"agent_key": agent_key, "total_jobs": 0}
    except Exception as e:
        logger.error(f"KG agent perf error: {e}")
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# LLM Judge endpoint
# ═══════════════════════════════════════════════════════════════════════

@router.get("/quality/{job_id}")
async def get_quality_score(job_id: str):
    """Get quality evaluation score for a completed job."""
    try:
        # Check if we have a cached score in the job run directory
        score_path = pathlib.Path(DATA_DIR) / "jobs" / "runs" / job_id / "quality_score.json"
        if score_path.exists():
            with open(score_path) as f:
                return json.load(f)
        return {"job_id": job_id, "score": None, "message": "No quality score available"}
    except Exception as e:
        logger.error(f"Quality score error for {job_id}: {e}")
        return {"error": str(e)}
