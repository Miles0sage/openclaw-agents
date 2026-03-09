"""
Memory Policies — Smart memory injection, dedup, and auto-extraction for OpenClaw agents.

Provides:
- Dedup: cosine similarity > 0.85 = skip/update existing
- Ranked injection: relevance + recency + importance scoring
- Auto-extract learnings from completed jobs
- Context injection into job prompts

Uses existing semantic_memory.py (TF-IDF) for similarity checks.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("memory_policies")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "os.environ.get("OPENCLAW_DATA_DIR", "./data")")
MEMORIES_FILE = os.path.join(DATA_DIR, "memories.jsonl")
DEDUP_THRESHOLD = 0.85  # cosine similarity above this = duplicate


# ---------------------------------------------------------------------------
# Dedup check
# ---------------------------------------------------------------------------

def should_save(content: str, existing_memories: list = None) -> dict:
    """Check if content is a duplicate of existing memories.

    Returns {"save": bool, "update_id": str|None, "reason": str}
    If a near-duplicate exists (>0.85 similarity), returns update_id
    so caller can update instead of insert.
    """
    if not content or len(content.strip()) < 10:
        return {"save": False, "update_id": None, "reason": "Content too short"}

    # Try semantic similarity check
    try:
        from semantic_memory import get_semantic_index
        index = get_semantic_index()
        if index.vectorizer is not None and index.matrix is not None:
            from sklearn.metrics.pairwise import cosine_similarity
            query_vec = index.vectorizer.transform([content])
            similarities = cosine_similarity(query_vec, index.matrix)[0]
            import numpy as np
            max_idx = int(np.argmax(similarities))
            max_sim = float(similarities[max_idx])

            if max_sim >= DEDUP_THRESHOLD:
                doc = index.documents[max_idx]
                return {
                    "save": False,
                    "update_id": doc[4],  # mem_id
                    "reason": f"Duplicate (similarity={max_sim:.2f})",
                    "existing_content": doc[0][:200],
                }
    except Exception as e:
        logger.debug(f"Semantic dedup check failed: {e}")

    # Fallback: exact substring check on existing_memories
    if existing_memories:
        content_lower = content.lower().strip()
        for mem in existing_memories:
            existing = mem.get("content", "").lower().strip()
            if content_lower in existing or existing in content_lower:
                return {
                    "save": False,
                    "update_id": mem.get("id"),
                    "reason": "Substring duplicate",
                }

    return {"save": True, "update_id": None, "reason": "New content"}


# ---------------------------------------------------------------------------
# Ranked memory retrieval
# ---------------------------------------------------------------------------

def rank_memories(query: str, memories: list, max_items: int = 5) -> list:
    """Rank memories by relevance + recency + importance.

    Each memory gets a composite score:
    - relevance: semantic similarity to query (0-1, weight 0.5)
    - recency: newer = higher (0-1, weight 0.2)
    - importance: normalized importance (0-1, weight 0.3)
    """
    if not memories:
        return []

    # Get semantic scores
    semantic_scores = {}
    try:
        from semantic_memory import get_semantic_index
        index = get_semantic_index()
        if index.vectorizer is not None and index.matrix is not None:
            results = index.search(query, limit=max_items * 3, min_score=0.05)
            for r in results:
                semantic_scores[r["id"]] = r["score"]
    except Exception:
        pass

    # Score each memory
    now = datetime.now(timezone.utc)
    scored = []
    for mem in memories:
        mem_id = mem.get("id", "")
        relevance = semantic_scores.get(mem_id, 0.0)

        # Recency: days since creation, capped at 90
        try:
            created = mem.get("created_at", mem.get("timestamp", ""))
            if created:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                days_ago = (now - dt).days
                recency = max(0, 1.0 - (days_ago / 90))
            else:
                recency = 0.3
        except Exception:
            recency = 0.3

        importance = min(mem.get("importance", 5), 10) / 10.0

        composite = (relevance * 0.5) + (recency * 0.2) + (importance * 0.3)
        scored.append((composite, mem))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:max_items]]


# ---------------------------------------------------------------------------
# Context injection
# ---------------------------------------------------------------------------

def inject_context(job_prompt: str, job_metadata: dict) -> str:
    """Prepend relevant memories + past reflections to a job prompt.

    Args:
        job_prompt: The original prompt for the job
        job_metadata: dict with 'task', 'project', 'department' keys

    Returns:
        Enhanced prompt with memory context prepended
    """
    task = job_metadata.get("task", "")
    project = job_metadata.get("project", "")
    department = job_metadata.get("department", "")

    context_parts = []

    # 1. Search memories for relevant context
    try:
        from semantic_memory import semantic_search
        memories = semantic_search(task, limit=5)
        if memories:
            ranked = rank_memories(task, memories, max_items=3)
            if ranked:
                mem_lines = ["## Relevant Memories"]
                for mem in ranked:
                    content = mem.get("content", "")[:200]
                    source = mem.get("source", "")
                    mem_lines.append(f"- [{source}] {content}")
                context_parts.append("\n".join(mem_lines))
    except Exception as e:
        logger.debug(f"Memory injection failed: {e}")

    # 2. Search reflections for past experience
    try:
        from reflexion import search_reflections, format_reflections_for_prompt
        reflections = search_reflections(task, project=project, department=department, limit=3)
        if reflections:
            formatted = format_reflections_for_prompt(reflections)
            if formatted:
                context_parts.append(formatted)
    except Exception as e:
        logger.debug(f"Reflection injection failed: {e}")

    if not context_parts:
        return job_prompt

    context_block = "\n\n".join(context_parts)
    return (
        f"{context_block}\n\n"
        f"---\n\n"
        f"{job_prompt}"
    )


# ---------------------------------------------------------------------------
# Auto-extract learnings
# ---------------------------------------------------------------------------

def auto_extract_learnings(job_result: dict, job_metadata: dict) -> list[str]:
    """Pull actionable facts from a completed job result.

    Extracts:
    - Discoveries (DISCOVERY: lines from agent output)
    - Error patterns that were resolved
    - Cost/performance observations
    """
    learnings = []
    text = job_result.get("text", "")
    task = job_metadata.get("task", "")
    project = job_metadata.get("project", "unknown")

    # Extract DISCOVERY lines from agent output
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.upper().startswith("DISCOVERY:"):
            discovery = stripped[len("DISCOVERY:"):].strip()
            if discovery:
                learnings.append(f"[{project}] {discovery}")

    # Extract error resolution patterns
    phases = job_result.get("phases", {})
    exec_phase = phases.get("execute", {})
    if exec_phase.get("steps_failed", 0) > 0 and exec_phase.get("steps_done", 0) > 0:
        learnings.append(
            f"[{project}] Task '{task[:80]}' had partial failures "
            f"({exec_phase['steps_failed']} failed, {exec_phase['steps_done']} succeeded) "
            f"— some steps may need different approach"
        )

    # Cost observation for expensive jobs
    cost = job_result.get("cost_usd", 0)
    if cost > 0.50:
        learnings.append(
            f"[{project}] Task '{task[:60]}' cost ${cost:.4f} — "
            f"consider decomposing similar tasks for cheaper execution"
        )

    return learnings


def save_learnings(learnings: list[str], project: str = "openclaw"):
    """Save extracted learnings to memory, with dedup check."""
    if not learnings:
        return

    for learning in learnings:
        check = should_save(learning)
        if check["save"]:
            try:
                # Use the agent_tools save_memory path (dual-write Supabase + JSONL)
                import uuid
                record = {
                    "id": str(uuid.uuid4())[:8],
                    "content": learning,
                    "tags": ["auto_learning", project],
                    "importance": 6,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                os.makedirs(os.path.dirname(MEMORIES_FILE), exist_ok=True)
                with open(MEMORIES_FILE, "a") as f:
                    f.write(json.dumps(record) + "\n")
                logger.info(f"Auto-saved learning: {learning[:80]}")
            except Exception as e:
                logger.warning(f"Failed to save learning: {e}")
        else:
            logger.debug(f"Skipped duplicate learning: {check['reason']}")
