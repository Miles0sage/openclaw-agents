"""
Memory Recall API endpoints.

Provides REST interface to unified memory recall system combining:
- Semantic search (TF-IDF)
- Reflexion learnings (past job outcomes)
- Topic files (MEMORY.md structured knowledge)
- Supabase persistent store
"""

from fastapi import APIRouter, Query
from typing import Optional, List
import logging

router = APIRouter(prefix="/api/memory", tags=["memory"])
logger = logging.getLogger("memory_router")


@router.post("/recall")
async def recall_memory(
    query: str = Query(..., description="Search query"),
    limit: int = Query(5, description="Max results per source"),
    sources: Optional[List[str]] = Query(None, description="Memory sources to search (semantic, reflexion, topics, supabase)"),
    project: Optional[str] = Query(None, description="Project context for filtering"),
    department: Optional[str] = Query(None, description="Department context for filtering"),
):
    """Unified memory recall across all sources.

    Returns combined, ranked results from semantic index, reflexion learnings, topic files, and Supabase.

    Args:
        query: Search query (meaning-based)
        limit: Max results per source (default 5)
        sources: List of sources to search (default all)
        project: Project context for reflexion filtering
        department: Department context for reflexion filtering

    Returns:
        {
            "query": query,
            "timestamp": ISO timestamp,
            "results": {source_type: [results]},
            "combined": [merged ranked results],
            "summary": "X results across Y sources"
        }
    """
    try:
        from memory_recall import recall

        context = {}
        if project:
            context["project"] = project
        if department:
            context["department"] = department

        result = recall(
            query=query,
            limit=limit,
            memory_sources=sources,
            context=context
        )

        return result
    except Exception as e:
        logger.error(f"Memory recall error: {e}", exc_info=True)
        return {
            "error": str(e),
            "query": query,
            "results": {},
            "combined": [],
            "summary": "Error during recall"
        }


@router.get("/recall")
async def recall_memory_get(
    query: str = Query(..., description="Search query"),
    limit: int = Query(5, description="Max results per source"),
    sources: Optional[str] = Query(None, description="Comma-separated sources"),
    project: Optional[str] = Query(None, description="Project context"),
    department: Optional[str] = Query(None, description="Department context"),
):
    """Unified memory recall (GET variant for convenience)."""
    try:
        from memory_recall import recall

        context = {}
        if project:
            context["project"] = project
        if department:
            context["department"] = department

        # Parse sources from comma-separated string
        source_list = None
        if sources:
            source_list = [s.strip() for s in sources.split(",")]

        result = recall(
            query=query,
            limit=limit,
            memory_sources=source_list,
            context=context
        )

        return result
    except Exception as e:
        logger.error(f"Memory recall error: {e}", exc_info=True)
        return {
            "error": str(e),
            "query": query,
            "results": {},
            "combined": [],
            "summary": "Error during recall"
        }


@router.get("/recall/by-topic/{topic}")
async def recall_by_topic(
    topic: str,
    limit: int = Query(10, description="Max results"),
):
    """Recall all memories related to a specific topic from MEMORY.md."""
    try:
        from memory_recall import recall_by_topic

        result = recall_by_topic(topic, limit=limit)
        return result
    except Exception as e:
        logger.error(f"Topic recall error: {e}", exc_info=True)
        return {
            "error": str(e),
            "topic": topic,
            "results": {},
            "summary": "Error during topic recall"
        }


@router.get("/recall/by-project/{project}")
async def recall_by_project(
    project: str,
    limit: int = Query(10, description="Max results"),
):
    """Recall learnings from a specific project (reflexion-only)."""
    try:
        from memory_recall import recall_by_project

        result = recall_by_project(project, limit=limit)
        return result
    except Exception as e:
        logger.error(f"Project recall error: {e}", exc_info=True)
        return {
            "error": str(e),
            "project": project,
            "results": {},
            "summary": "Error during project recall"
        }


@router.get("/recall/recent")
async def recall_recent(
    days: int = Query(7, description="Number of days back"),
    limit: int = Query(20, description="Max results"),
):
    """Recall memories from the last N days."""
    try:
        from memory_recall import recall_recent

        results = recall_recent(days=days, limit=limit)
        return {
            "days": days,
            "count": len(results),
            "memories": results
        }
    except Exception as e:
        logger.error(f"Recent recall error: {e}", exc_info=True)
        return {
            "error": str(e),
            "days": days,
            "memories": []
        }
