"""
Brick Builder router — proxy endpoints to brick-builder service at localhost:8001.

Provides gateway endpoints for:
- Health checks
- AI-powered building suggestions
- Block completion suggestions
- Build descriptions
- Listing saved builds
- Save/load builds
"""

import logging

import httpx
from fastapi import APIRouter, HTTPException

logger = logging.getLogger("openclaw_gateway")
router = APIRouter(prefix="/brick-builder", tags=["brick-builder"])

# Brick Builder service location
BRICK_BUILDER_URL = "http://localhost:8001"
PROXY_TIMEOUT = 30.0


@router.get("/health")
async def health_check():
    """Proxy health check to brick-builder service."""
    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            response = await client.get(f"{BRICK_BUILDER_URL}/health")
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Brick Builder health check failed: {e}")
        raise HTTPException(status_code=503, detail="Brick Builder service unavailable")
    except Exception as e:
        logger.error(f"Brick Builder health check error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai/suggest")
async def suggest_bricks(request: dict):
    """Proxy AI suggestion request to brick-builder service."""
    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            response = await client.post(
                f"{BRICK_BUILDER_URL}/api/ai/suggest",
                json=request
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Brick Builder suggest failed: {e}")
        raise HTTPException(status_code=503, detail="Brick Builder service unavailable")
    except Exception as e:
        logger.error(f"Brick Builder suggest error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai/complete")
async def complete_brick(request: dict):
    """Proxy block completion request to brick-builder service."""
    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            response = await client.post(
                f"{BRICK_BUILDER_URL}/api/ai/complete",
                json=request
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Brick Builder complete failed: {e}")
        raise HTTPException(status_code=503, detail="Brick Builder service unavailable")
    except Exception as e:
        logger.error(f"Brick Builder complete error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai/describe")
async def describe_build(request: dict):
    """Proxy build description request to brick-builder service."""
    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            response = await client.post(
                f"{BRICK_BUILDER_URL}/api/ai/describe",
                json=request
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Brick Builder describe failed: {e}")
        raise HTTPException(status_code=503, detail="Brick Builder service unavailable")
    except Exception as e:
        logger.error(f"Brick Builder describe error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/builds/save")
async def save_build(request: dict):
    """Proxy save build request to brick-builder service."""
    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            response = await client.post(
                f"{BRICK_BUILDER_URL}/api/builds/save",
                json=request
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Brick Builder save failed: {e}")
        raise HTTPException(status_code=503, detail="Brick Builder service unavailable")
    except Exception as e:
        logger.error(f"Brick Builder save error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/builds/load")
async def load_build(request: dict):
    """Proxy load build request to brick-builder service."""
    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            response = await client.post(
                f"{BRICK_BUILDER_URL}/api/builds/load",
                json=request
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Brick Builder load failed: {e}")
        raise HTTPException(status_code=503, detail="Brick Builder service unavailable")
    except Exception as e:
        logger.error(f"Brick Builder load error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/builds/list")
async def list_builds(skip: int = 0, limit: int = 50):
    """Proxy saved builds list request to brick-builder service."""
    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            response = await client.get(
                f"{BRICK_BUILDER_URL}/api/builds/list",
                params={"skip": skip, "limit": limit}
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Brick Builder builds list failed: {e}")
        raise HTTPException(status_code=503, detail="Brick Builder service unavailable")
    except Exception as e:
        logger.error(f"Brick Builder builds list error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
