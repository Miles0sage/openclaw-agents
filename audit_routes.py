"""
OpenClaw Audit Trail API Routes

Endpoints for viewing request logs and audit data:
- GET /api/logs?limit=100 — Recent requests
- GET /api/logs/{date} — Daily summary
- GET /api/audit/costs — Cost breakdown
- GET /api/audit/errors — Error analysis
- GET /api/audit/agents — Agent statistics
- GET /api/audit/slowest — Slowest requests
"""

from fastapi import APIRouter, Query, HTTPException, Path
from typing import Optional, Dict, Any
import logging
from datetime import datetime

from request_logger import get_logger

router = APIRouter(prefix="/api/audit", tags=["audit"])
logger = logging.getLogger("openclaw_audit")


@router.get("/logs")
async def get_logs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """
    Get recent request logs
    
    Query Parameters:
    - limit: Number of logs to return (default 100, max 1000)
    - offset: Offset for pagination (default 0)
    
    Returns: List of request logs with metadata
    """
    try:
        logger_instance = get_logger()
        logs = logger_instance.get_logs(limit=limit, offset=offset)
        
        return {
            "status": "success",
            "count": len(logs),
            "limit": limit,
            "offset": offset,
            "logs": logs
        }
    except Exception as e:
        logger.error(f"Error fetching logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs/{date}")
async def get_daily_summary(
    date: str = Path(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
) -> Dict[str, Any]:
    """
    Get daily summary for a specific date
    
    Parameters:
    - date: Date in format YYYY-MM-DD
    
    Returns:
    - total_requests, total_cost, token usage
    - Success/error/timeout breakdown
    - Agent and channel usage
    - Model breakdown
    """
    try:
        # Validate date format
        datetime.strptime(date, "%Y-%m-%d")
        
        logger_instance = get_logger()
        summary = logger_instance.get_daily_summary(date)
        
        return {
            "status": "success",
            "date": date,
            "summary": summary
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    except Exception as e:
        logger.error(f"Error fetching daily summary for {date}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/costs")
async def get_cost_breakdown(
    days: int = Query(30, ge=1, le=365)
) -> Dict[str, Any]:
    """
    Get cost breakdown for last N days
    
    Query Parameters:
    - days: Number of days to analyze (default 30)
    
    Returns:
    - Daily cost totals
    - Cost breakdown by agent
    - Cost breakdown by model
    """
    try:
        logger_instance = get_logger()
        breakdown = logger_instance.get_cost_breakdown(days=days)
        
        return {
            "status": "success",
            "period_days": days,
            "breakdown": breakdown
        }
    except Exception as e:
        logger.error(f"Error fetching cost breakdown: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/errors")
async def get_error_analysis(
    days: int = Query(30, ge=1, le=365)
) -> Dict[str, Any]:
    """
    Analyze errors for last N days
    
    Query Parameters:
    - days: Number of days to analyze (default 30)
    
    Returns:
    - Errors broken down by type
    - Errors by affected agent
    - HTTP error code distribution
    """
    try:
        logger_instance = get_logger()
        analysis = logger_instance.get_error_analysis(days=days)
        
        return {
            "status": "success",
            "period_days": days,
            "analysis": analysis
        }
    except Exception as e:
        logger.error(f"Error analyzing errors: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents")
async def get_agent_statistics(
    days: int = Query(30, ge=1, le=365)
) -> Dict[str, Any]:
    """
    Get agent usage statistics
    
    Query Parameters:
    - days: Number of days to analyze (default 30)
    
    Returns:
    - Per-agent: requests, cost, latency, success rate, confidence
    """
    try:
        logger_instance = get_logger()
        stats = logger_instance.get_agent_stats(days=days)
        
        return {
            "status": "success",
            "period_days": days,
            "agents": stats
        }
    except Exception as e:
        logger.error(f"Error fetching agent stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/slowest")
async def get_slowest_requests(
    limit: int = Query(10, ge=1, le=100)
) -> Dict[str, Any]:
    """
    Get slowest requests
    
    Query Parameters:
    - limit: Number of requests to return (default 10, max 100)
    
    Returns: Sorted list of slowest requests with latency info
    """
    try:
        logger_instance = get_logger()
        slowest = logger_instance.get_slowest_requests(limit=limit)
        
        return {
            "status": "success",
            "count": len(slowest),
            "limit": limit,
            "slowest_requests": slowest
        }
    except Exception as e:
        logger.error(f"Error fetching slowest requests: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def audit_health() -> Dict[str, str]:
    """Health check for audit system"""
    try:
        logger_instance = get_logger()
        # Try a simple query to verify database is working
        logger_instance.get_logs(limit=1)
        return {
            "status": "healthy",
            "message": "Audit trail system operational"
        }
    except Exception as e:
        logger.error(f"Audit health check failed: {e}")
        raise HTTPException(status_code=500, detail="Audit system unhealthy")
