"""
Admin API Router — Memory, Health, Reactions, Metrics, Cron

Provides endpoints for:
- Memory management: list, add, search
- Health data sync (iOS Shortcuts, Apple Health)
- Auto-reaction rules and triggers
- Agent performance metrics and recommendations
- Cron job management
- Dashboard aggregations
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from routers.shared import (
    DATA_DIR,
    get_memory_manager,
    get_cron_scheduler,
    get_cost_metrics,
    get_response_cache,
    get_quota_status,
    CONFIG,
    agent_router,
    broadcast_event,
)

logger = logging.getLogger("openclaw_gateway")

router = APIRouter(prefix="/api", tags=["admin"])


# ═══════════════════════════════════════════════════════════════════════
# MEMORY & CRON ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.get("/memories")
async def api_list_memories(tag: Optional[str] = None, query: Optional[str] = None, limit: int = 20):
    """List memories, optionally filtered by tag or text query"""
    try:
        mm = get_memory_manager()
        if not mm:
            return {"memories": [], "total": 0}
        if tag:
            memories = mm.get_by_tag(tag)
        elif query:
            # Simple text search across memory content
            all_mems = mm.get_recent(limit=200)
            q = query.lower()
            memories = [m for m in all_mems if q in m.get("content", "").lower()][:limit]
        else:
            memories = mm.get_recent(limit=limit)
        return {"memories": memories, "total": len(memories)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/memory/add")
async def api_add_memory(request: Request):
    """Manually add a memory"""
    try:
        data = await request.json()
        mm = get_memory_manager()
        if not mm:
            return JSONResponse({"error": "memory manager not initialized"}, status_code=500)
        mem_id = mm.add_memory(
            content=data.get("content", ""),
            tags=data.get("tags", []),
            source=data.get("source", "manual"),
            importance=data.get("importance", 5),
            remind_at=data.get("remind_at")
        )
        return {"memory_id": mem_id, "status": "saved"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/reminders/due")
async def api_reminders_due():
    """Get reminders that are due (remind_at in the past, not yet reminded)"""
    try:
        mm = get_memory_manager()
        if not mm:
            return {"reminders": [], "total": 0}
        due = mm.get_due_reminders()
        return {"reminders": due, "total": len(due)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/reminders/mark")
async def api_reminders_mark(request: Request):
    """Mark a reminder as sent"""
    try:
        data = await request.json()
        mem_id = data.get("memory_id")
        if not mem_id:
            return JSONResponse({"error": "memory_id required"}, status_code=400)
        mm = get_memory_manager()
        if not mm:
            return JSONResponse({"error": "memory manager not initialized"}, status_code=500)
        mm.mark_reminded(mem_id)
        return {"status": "marked", "memory_id": mem_id}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/cron/jobs")
async def api_cron_jobs():
    """List cron jobs"""
    try:
        cron = get_cron_scheduler()
        if not cron:
            return {"jobs": [], "total": 0}
        jobs = cron.list_jobs()
        return {"jobs": jobs, "total": len(jobs)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# HEALTH SYNC — Receive data from iOS Shortcuts (Apple Health)
# ═══════════════════════════════════════════════════════════════════════

@router.post("/health/sync")
async def api_health_sync(request: Request):
    """Receive health data from iOS Shortcuts (Apple Health export)."""
    try:
        data = await request.json()
        health_dir = os.path.join(DATA_DIR, "health")
        os.makedirs(health_dir, exist_ok=True)
        if "timestamp" not in data:
            data["timestamp"] = datetime.now(timezone.utc).isoformat()
        if "date" not in data:
            data["date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily_file = os.path.join(health_dir, "daily.jsonl")
        with open(daily_file, "a") as f:
            f.write(json.dumps(data) + "\n")
        logger.info(f"Health sync received: {list(data.keys())}")
        return {"status": "ok", "received_keys": list(data.keys())}
    except Exception as e:
        logger.error(f"Health sync error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/health/today")
async def api_health_today():
    """Get today's health data."""
    try:
        health_file = os.path.join(DATA_DIR, "health", "daily.jsonl")
        if not os.path.exists(health_file):
            return {"data": [], "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entries = []
        with open(health_file) as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    entry = json.loads(line)
                    if entry.get("date", "") == today:
                        entries.append(entry)
                except: continue
        return {"data": entries, "date": today}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# REACTIONS & SELF-IMPROVE API
# ═══════════════════════════════════════════════════════════════════════

@router.get("/reactions")
async def api_list_reactions():
    """List all reaction rules."""
    try:
        from reactions import get_reactions_engine
        engine = get_reactions_engine()
        return {"rules": engine.get_rules(), "status": engine.get_status()}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/reactions")
async def api_manage_reaction(request: Request):
    """Add/update/delete a reaction rule."""
    try:
        from reactions import get_reactions_engine
        data = await request.json()
        engine = get_reactions_engine()
        action = data.get("action", "add")
        if action == "add":
            rule_id = engine.add_rule(data.get("rule", data))
            return {"rule_id": rule_id, "status": "added"}
        elif action == "update":
            engine.update_rule(data["rule_id"], data.get("updates", {}))
            return {"status": "updated"}
        elif action == "delete":
            engine.delete_rule(data["rule_id"])
            return {"status": "deleted"}
        return JSONResponse({"error": f"Unknown action: {action}"}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/reactions/triggers")
async def api_reaction_triggers(limit: int = 20):
    """Get recent reaction trigger history."""
    try:
        from reactions import get_reactions_engine
        engine = get_reactions_engine()
        return {"triggers": engine.get_recent_triggers(limit=limit)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# METRICS & PERFORMANCE
# ═══════════════════════════════════════════════════════════════════════

@router.get("/metrics/summary")
async def api_metrics_summary(days: int = 7):
    """Get agent performance summary."""
    try:
        from self_improve import get_self_improve_engine
        engine = get_self_improve_engine()
        return engine.get_summary(days=days)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/metrics/sparkline")
async def api_metrics_sparkline(days: int = 7):
    """Get daily success rate data for sparkline charts."""
    try:
        from self_improve import get_self_improve_engine
        engine = get_self_improve_engine()
        return {"data": engine.get_daily_sparkline_data(days=days)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/metrics/recommendations")
async def api_metrics_recommendations():
    """Get guardrail adjustment recommendations."""
    try:
        from self_improve import get_self_improve_engine
        engine = get_self_improve_engine()
        return engine.get_guardrail_recommendations()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/metrics/retrospective")
async def api_generate_retrospective():
    """Generate and save a weekly retrospective."""
    try:
        from self_improve import get_self_improve_engine
        engine = get_self_improve_engine()
        return engine.generate_retrospective()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# MISSION CONTROL API
# ═══════════════════════════════════════════════════════════════════════

@router.get("/memory/list")
async def memory_list():
    """List all memories for Mission Control"""
    memory_mgr = get_memory_manager()
    if not memory_mgr:
        return {"success": True, "memories": [], "total": 0}

    memories = memory_mgr.list_all() if hasattr(memory_mgr, 'list_all') else []
    return {"success": True, "memories": memories, "total": len(memories)}


@router.get("/dashboard/summary")
async def dashboard_summary():
    """Aggregated dashboard summary for Mission Control"""
    # Get cost metrics
    cost_data = get_cost_metrics()

    # Get cache stats
    cache = get_response_cache()
    cache_stats = cache.get_stats() if cache else {}

    # Get quota status
    quota_status = get_quota_status("default")

    # Get agent count
    agent_count = len(CONFIG.get("agents", {}))

    # Get router stats
    router_stats = agent_router.get_cache_stats() if hasattr(agent_router, 'get_cache_stats') else {}

    return {
        "success": True,
        "summary": {
            "agents_total": agent_count,
            "cost_today": cost_data.get("today_usd", 0),
            "cost_month": cost_data.get("month_usd", 0),
            "daily_limit": quota_status.get("daily", {}).get("limit", 50),
            "monthly_limit": quota_status.get("monthly", {}).get("limit", 1000),
            "cache_hit_rate": cache_stats.get("hit_rate_percent", "0%"),
            "cache_tokens_saved": cache_stats.get("total_tokens_saved", 0),
            "cache_cost_saved": cache_stats.get("total_cost_saved_usd", 0),
            "router_cache": router_stats,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
        }
    }
