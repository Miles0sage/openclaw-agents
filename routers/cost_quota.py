"""Cost tracking, cache, and quota endpoints."""

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from cost_tracker import get_cost_metrics, get_cost_summary, log_cost_event
from cost_gates import get_cost_gates, check_cost_budget, BudgetStatus
from routers.shared import load_quota_config, check_all_quotas, get_quota_status
from response_cache import get_response_cache

logger = logging.getLogger("openclaw.routers.cost_quota")

router = APIRouter()


# ---------------------------------------------------------------------------
# Cost endpoints
# ---------------------------------------------------------------------------

@router.get("/api/costs/summary")
async def costs_summary():
    """Get cost metrics summary"""
    try:
        metrics = get_cost_metrics()
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": metrics
        }
    except Exception as e:
        logger.error(f"Error getting cost metrics: {e}")
        return {"success": False, "error": str(e)}


@router.get("/api/costs/text")
async def costs_text():
    """Get cost summary as text"""
    try:
        summary = get_cost_summary()
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary
        }
    except Exception as e:
        logger.error(f"Error getting cost summary: {e}")
        return {"success": False, "error": str(e)}


@router.get("/api/digest")
async def daily_digest():
    """Get daily digest stats for n8n Daily Digest workflow"""
    try:
        from event_engine import get_event_engine

        engine = get_event_engine()

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        all_events = engine.get_recent_events(limit=500)

        recent_events = [
            e for e in all_events
            if datetime.fromisoformat(e.get("timestamp", "")) >= cutoff
        ]

        jobs_completed = len([e for e in recent_events if e.get("event_type") == "job.completed"])
        jobs_failed = len([e for e in recent_events if e.get("event_type") == "job.failed"])
        jobs_created = len([e for e in recent_events if e.get("event_type") == "job.created"])

        metrics = get_cost_metrics()
        total_cost = metrics.get("daily_spend", 0) if isinstance(metrics, dict) else 0

        uptime = "100%" if recent_events else "Unknown"

        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "jobs_completed": jobs_completed,
            "jobs_failed": jobs_failed,
            "jobs_created": jobs_created,
            "total_cost": total_cost,
            "uptime": uptime,
            "event_count": len(recent_events),
            "period": "24h"
        }
    except Exception as e:
        logger.error(f"Error generating daily digest: {e}")
        return {
            "success": False,
            "error": str(e),
            "jobs_completed": 0,
            "jobs_failed": 0,
            "total_cost": 0,
            "uptime": "Error",
            "event_count": 0
        }


# ---------------------------------------------------------------------------
# Response cache endpoints
# ---------------------------------------------------------------------------

@router.get("/api/cache/stats")
async def cache_stats():
    """Get response cache statistics"""
    cache = get_response_cache()
    if not cache:
        return {"success": False, "error": "Cache not initialized"}
    return {"success": True, "data": cache.get_stats()}


@router.post("/api/cache/clear")
async def cache_clear():
    """Clear response cache"""
    cache = get_response_cache()
    if not cache:
        return {"success": False, "error": "Cache not initialized"}
    count = cache.invalidate()
    return {"success": True, "cleared": count}


@router.post("/api/cache/cleanup")
async def cache_cleanup():
    """Remove expired cache entries"""
    cache = get_response_cache()
    if not cache:
        return {"success": False, "error": "Cache not initialized"}
    count = cache.cleanup_expired()
    return {"success": True, "expired_removed": count}


# ---------------------------------------------------------------------------
# Quota endpoints
# ---------------------------------------------------------------------------

@router.get("/api/quotas/status")
async def global_quota_status():
    """Get global quota/budget status"""
    try:
        quota_config = load_quota_config()

        if not quota_config.get("enabled", False):
            return {
                "success": True,
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "data": {
                    "quotas_enabled": False,
                    "message": "Quotas are disabled"
                }
            }

        metrics = get_cost_metrics()

        daily_spend = metrics.get("daily_total", 0.0)
        monthly_spend = metrics.get("monthly_total", 0.0)

        daily_budget = quota_config.get("daily_limit_usd", 50)
        monthly_budget = quota_config.get("monthly_limit_usd", 1000)

        daily_remaining = max(0, daily_budget - daily_spend)
        monthly_remaining = max(0, monthly_budget - monthly_spend)

        daily_percent = (daily_spend / daily_budget * 100) if daily_budget > 0 else 0
        monthly_percent = (monthly_spend / monthly_budget * 100) if monthly_budget > 0 else 0

        warning_threshold = quota_config.get("warning_threshold_percent", 80)

        status = "healthy"
        if daily_percent >= 100 or monthly_percent >= 100:
            status = "critical"
        elif daily_percent >= warning_threshold or monthly_percent >= warning_threshold:
            status = "warning"

        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "data": {
                "daily_budget": daily_budget,
                "daily_used": round(daily_spend, 4),
                "daily_remaining": round(daily_remaining, 4),
                "daily_percent": round(daily_percent, 1),
                "monthly_budget": monthly_budget,
                "monthly_used": round(monthly_spend, 4),
                "monthly_remaining": round(monthly_remaining, 4),
                "monthly_percent": round(monthly_percent, 1),
                "status": status,
                "warning_threshold_percent": warning_threshold,
                "quotas_enabled": True
            }
        }
    except Exception as e:
        logger.error(f"Error getting global quota status: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
        }


@router.get("/api/quotas/status/{project_id}")
async def quota_status_endpoint(project_id: str = "default"):
    """Get current quota usage for a project"""
    try:
        status = get_quota_status(project_id)
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "data": status
        }
    except Exception as e:
        logger.error(f"Error getting quota status: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
        }


@router.get("/api/quotas/config")
async def quota_config_endpoint():
    """Get quota configuration"""
    try:
        quota_config = load_quota_config()
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "data": quota_config
        }
    except Exception as e:
        logger.error(f"Error getting quota config: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
        }
