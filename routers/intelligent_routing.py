"""
Intelligent Routing Router Module

FastAPI APIRouter for query classification and model routing endpoints:
- POST /api/route       - Classify query and get optimal model routing
- POST /api/route/test  - Test routing with multiple queries
- GET  /api/route/models - Get available models and pricing
- GET  /api/route/health - Health check for router
"""

import logging
import json
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from routers.shared import (
    classify_query,
    ClassificationResult,
    MODEL_PRICING,
    MODEL_ALIASES,
    MODEL_RATE_LIMITS,
    get_cost_gates,
    check_cost_budget,
    BudgetStatus,
    log_cost_event,
)

logger = logging.getLogger("openclaw_gateway")
router = APIRouter()


# ── Pydantic Models ────────────────────────────────────────────────────

class RouteRequest(BaseModel):
    query: str
    context: Optional[str] = None
    sessionKey: Optional[str] = None
    force_model: Optional[str] = None


class RouteTestRequest(BaseModel):
    queries: list


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("/api/route")
async def route_endpoint(req: RouteRequest):
    """Classify query and route to optimal model (Haiku/Sonnet/Opus)"""
    try:
        if not req.query or not isinstance(req.query, str):
            return JSONResponse(status_code=400, content={
                "success": False,
                "error": "query is required and must be a string",
            })

        # Force model override
        if req.force_model and req.force_model in ("haiku", "sonnet", "opus"):
            forced = ClassificationResult(
                complexity=0, model=req.force_model, confidence=1.0,
                reasoning=f"Forced to {req.force_model.upper()} by request",
                estimated_tokens=0, cost_estimate=0,
            )
            return {
                "success": True,
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "model": req.force_model,
                "complexity": 0,
                "confidence": 1.0,
                "reasoning": forced.reasoning,
                "cost_estimate": 0,
                "estimated_tokens": 0,
                "metadata": {
                    "pricing": MODEL_PRICING.get(req.force_model, {}),
                    "cost_savings_vs_sonnet": 0,
                    "cost_savings_percentage": 0,
                    "rate_limit": MODEL_RATE_LIMITS.get(req.force_model, {}),
                },
            }

        # Combine query and context
        full_query = f"{req.query}\n\nContext: {req.context}" if req.context else req.query

        # Classify
        result = classify_query(full_query)

        # ═ COST GATES: Check budget before routing decision
        project = req.sessionKey.split(":")[0] if req.sessionKey and ":" in req.sessionKey else "default"
        cost_gates = get_cost_gates()

        # Estimate tokens for routing decision
        estimated_tokens = len(full_query.split()) * 2

        budget_check = check_cost_budget(
            project=project,
            agent="router",
            model=result.model,
            tokens_input=estimated_tokens // 2,
            tokens_output=estimated_tokens // 2,
            task_id=f"{project}:router:{req.sessionKey}"
        )

        if budget_check.status == BudgetStatus.REJECTED:
            logger.warning(f"💰 Cost gate REJECTED routing: {budget_check.message}")
            return JSONResponse(
                status_code=402,
                content={
                    "success": False,
                    "error": "Budget limit exceeded",
                    "detail": budget_check.message,
                    "gate": budget_check.gate_name,
                    "remaining_budget": budget_check.remaining_budget,
                    "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                }
            )
        elif budget_check.status == BudgetStatus.WARNING:
            logger.warning(f"⚠️  Cost gate WARNING: {budget_check.message}")


        # Calculate savings vs sonnet baseline
        sonnet_cost = (result.estimated_tokens // 3 * MODEL_PRICING["sonnet"]["input"]
                       + (result.estimated_tokens - result.estimated_tokens // 3) * MODEL_PRICING["sonnet"]["output"]) / 1_000_000
        savings = max(0, sonnet_cost - result.cost_estimate)
        savings_pct = round((savings / sonnet_cost) * 100, 2) if sonnet_cost > 0 else 0

        # Log cost event if sessionKey provided
        if req.sessionKey:
            try:
                log_cost_event(
                    project="openclaw",
                    agent="router",
                    model=MODEL_ALIASES.get(result.model, result.model),
                    tokens_input=result.estimated_tokens // 3,
                    tokens_output=result.estimated_tokens - result.estimated_tokens // 3,
                    cost=result.cost_estimate,
                )
            except Exception as e:
                logger.warning(f"Failed to log cost event: {e}")

        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "model": result.model,
            "complexity": result.complexity,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "cost_estimate": result.cost_estimate,
            "estimated_tokens": result.estimated_tokens,
            "metadata": {
                "pricing": MODEL_PRICING.get(result.model, {}),
                "cost_savings_vs_sonnet": round(savings, 6),
                "cost_savings_percentage": savings_pct,
                "rate_limit": MODEL_RATE_LIMITS.get(result.model, {}),
            },
        }
    except Exception as e:
        logger.error(f"Router endpoint error: {e}")
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": str(e),
        })


@router.post("/api/route/test")
async def route_test_endpoint(req: RouteTestRequest):
    """Test routing with multiple queries"""
    try:
        if not req.queries or len(req.queries) == 0:
            return JSONResponse(status_code=400, content={
                "success": False,
                "error": "queries array is required and must not be empty",
            })

        results = []
        for q in req.queries:
            r = classify_query(q)
            sonnet_cost = (r.estimated_tokens // 3 * MODEL_PRICING["sonnet"]["input"]
                           + (r.estimated_tokens - r.estimated_tokens // 3) * MODEL_PRICING["sonnet"]["output"]) / 1_000_000
            savings_pct = round(((sonnet_cost - r.cost_estimate) / sonnet_cost) * 100, 2) if sonnet_cost > 0 else 0
            results.append({
                "query": q[:100] + ("..." if len(q) > 100 else ""),
                "model": r.model,
                "complexity": r.complexity,
                "confidence": r.confidence,
                "cost_estimate": r.cost_estimate,
                "savings_percentage": savings_pct,
            })

        by_model = {"haiku": 0, "sonnet": 0, "opus": 0}
        for r in results:
            by_model[r["model"]] = by_model.get(r["model"], 0) + 1

        stats = {
            "total_queries": len(results),
            "by_model": by_model,
            "avg_complexity": round(sum(r["complexity"] for r in results) / len(results), 1),
            "avg_confidence": round(sum(r["confidence"] for r in results) / len(results), 2),
            "total_estimated_cost": round(sum(r["cost_estimate"] for r in results), 6),
            "avg_savings_percentage": round(sum(r["savings_percentage"] for r in results) / len(results), 1),
        }

        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "results": results,
            "stats": stats,
        }
    except Exception as e:
        logger.error(f"Route test endpoint error: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.get("/api/route/models")
async def route_models_endpoint():
    """Get available models and pricing information"""
    models_info = [
        {
            "name": "Claude 3.5 Haiku",
            "model": "haiku",
            "alias": MODEL_ALIASES["haiku"],
            "pricing": MODEL_PRICING["haiku"],
            "contextWindow": 200000,
            "maxOutputTokens": 4096,
            "costSavingsPercentage": -75,
            "available": True,
            "rateLimit": MODEL_RATE_LIMITS["haiku"],
        },
        {
            "name": "Claude 3.5 Sonnet",
            "model": "sonnet",
            "alias": MODEL_ALIASES["sonnet"],
            "pricing": MODEL_PRICING["sonnet"],
            "contextWindow": 200000,
            "maxOutputTokens": 4096,
            "costSavingsPercentage": 0,
            "available": True,
            "rateLimit": MODEL_RATE_LIMITS["sonnet"],
        },
        {
            "name": "Claude Opus 4.6",
            "model": "opus",
            "alias": MODEL_ALIASES["opus"],
            "pricing": MODEL_PRICING["opus"],
            "contextWindow": 200000,
            "maxOutputTokens": 4096,
            "costSavingsPercentage": 400,
            "available": True,
            "rateLimit": MODEL_RATE_LIMITS["opus"],
        },
    ]

    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "models": models_info,
        "optimalDistribution": {"haiku": "70%", "sonnet": "20%", "opus": "10%"},
        "expectedCostSavings": "60-70% reduction vs always using Sonnet",
    }


@router.get("/api/route/health")
async def route_health_endpoint():
    """Health check for router"""
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "status": "healthy",
        "models_available": 3,
        "models": ["haiku", "sonnet", "opus"],
        "router_version": "1.0.0",
    }
