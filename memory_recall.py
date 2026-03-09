"""
Unified Memory Recall System for OpenClaw

Orchestrates retrieval from all memory sources:
1. Semantic memory index (TF-IDF from memories.jsonl + MEMORY.md)
2. Reflexion system (learnings from past jobs)
3. MEMORY.md topic files (structured knowledge)
4. Supabase memories table (persistent store)

Provides one clean interface: recall() that combines all sources.
"""

import os
import json
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone

logger = logging.getLogger("memory_recall")

# ═══════════════════════════════════════════════════════════════
# Core Recall Function
# ═══════════════════════════════════════════════════════════════


def recall(
    query: str,
    limit: int = 5,
    memory_sources: List[str] = None,
    context: Dict = None,
) -> Dict:
    """
    Unified memory recall across all sources.

    Args:
        query: Search query (meaning-based)
        limit: Max results per source
        memory_sources: Which sources to search (default: all)
            - "semantic": TF-IDF search on memories.jsonl + MEMORY.md
            - "reflexion": Past job learnings
            - "topics": Structured MEMORY.md files
            - "supabase": Remote memories table
        context: Optional context dict with 'project', 'department', 'task'

    Returns:
        Dict with:
        {
            "query": query,
            "timestamp": ISO timestamp,
            "context": {project, department, task},
            "results": {
                "semantic": [...],
                "reflexion": [...],
                "topics": [...],
                "supabase": [...]
            },
            "summary": "X results across Y sources",
            "combined": [...] # All results merged and ranked
        }
    """
    if memory_sources is None:
        memory_sources = ["semantic", "reflexion", "topics", "supabase"]

    context = context or {}
    results = {}

    # Perform searches in parallel (conceptually)
    if "semantic" in memory_sources:
        results["semantic"] = _search_semantic(query, limit)

    if "reflexion" in memory_sources:
        results["reflexion"] = _search_reflexion(
            query, limit, context.get("project"), context.get("department")
        )

    if "topics" in memory_sources:
        results["topics"] = _search_topics(query, limit)

    if "supabase" in memory_sources:
        results["supabase"] = _search_supabase(query, limit)

    # Combine and rank results
    combined = _combine_results(results)

    return {
        "query": query,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "context": context,
        "results": results,
        "combined": combined,
        "summary": f"{sum(len(v) for v in results.values() if v)} results across {len([v for v in results.values() if v])} sources",
    }


# ═══════════════════════════════════════════════════════════════
# Search Implementations
# ═══════════════════════════════════════════════════════════════


def _search_semantic(query: str, limit: int) -> List[Dict]:
    """Search semantic memory index (TF-IDF)."""
    try:
        from semantic_memory import semantic_search

        results = semantic_search(query, limit)
        return [
            {
                "id": r["id"],
                "content": r["content"],
                "source": r["source"],
                "importance": r["importance"],
                "tags": r["tags"],
                "score": r["score"],
                "source_type": "semantic",
            }
            for r in results
        ]
    except Exception as e:
        logger.debug(f"Semantic search failed: {e}")
        return []


def _search_reflexion(
    query: str, limit: int, project: str = None, department: str = None
) -> List[Dict]:
    """Search reflexion database (past job learnings)."""
    try:
        from reflexion import search_reflections

        reflections = search_reflections(
            query, project=project, department=department, limit=limit
        )
        return [
            {
                "id": r.get("job_id", r.get("id", "?")),
                "content": _format_reflection_summary(r),
                "source": f"job:{r.get('job_id', '?')}",
                "importance": 7,  # Learnings are important
                "tags": r.get("tags", []),
                "score": r.get("_relevance_score", 0) / 10.0,  # Normalize to 0-1
                "source_type": "reflexion",
                "metadata": {
                    "outcome": r.get("outcome"),
                    "project": r.get("project"),
                    "task": r.get("task"),
                    "duration_seconds": r.get("duration_seconds"),
                    "cost_usd": r.get("cost_usd"),
                },
            }
            for r in reflections
        ]
    except Exception as e:
        logger.debug(f"Reflexion search failed: {e}")
        return []


def _search_topics(query: str, limit: int) -> List[Dict]:
    """Search MEMORY.md topic files."""
    try:
        memory_dir = "/root/.claude/projects/-root/memory"
        results = []

        if not os.path.isdir(memory_dir):
            return []

        query_lower = query.lower()

        # Search all .md files
        for root, dirs, files in os.walk(memory_dir):
            for file in files:
                if not file.endswith(".md"):
                    continue

                filepath = os.path.join(root, file)
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()

                    # Score by keyword match
                    content_lower = content.lower()
                    match_count = content_lower.count(query_lower)

                    if match_count > 0:
                        # Extract relevant section
                        section = _extract_relevant_section(content, query, max_len=200)
                        results.append(
                            {
                                "id": file.replace(".md", ""),
                                "content": section,
                                "source": f"topic:{file}",
                                "importance": 8,  # Topic files are important
                                "tags": ["memory", file.replace(".md", "")],
                                "score": min(1.0, match_count / 10),  # Normalize to 0-1
                                "source_type": "topics",
                                "filepath": filepath,
                            }
                        )
                except Exception:
                    continue

        # Sort by score
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    except Exception as e:
        logger.debug(f"Topic search failed: {e}")
        return []


def _search_supabase(query: str, limit: int) -> List[Dict]:
    """Search Supabase memories table."""
    try:
        from supabase_client import table_select, is_connected

        if not is_connected():
            return []

        rows = table_select("memories", "order=created_at.desc", limit=500)
        if not rows:
            return []

        query_lower = query.lower()
        scored = []

        for row in rows:
            content = row.get("content", "").lower()
            tags = row.get("tags", []) or []
            tags_str = " ".join(tags).lower()

            # Simple scoring
            score = 0
            if query_lower in content:
                score += 1
            if query_lower in tags_str:
                score += 2

            if score > 0:
                scored.append(
                    {
                        "id": row.get("id", "?"),
                        "content": row.get("content", "")[:200],
                        "source": f"supabase:{row.get('id', '?')}",
                        "importance": row.get("importance", 5),
                        "tags": tags,
                        "score": score / 3.0,  # Normalize to 0-1
                        "source_type": "supabase",
                    }
                )

        scored.sort(key=lambda x: (x["importance"], x["score"]), reverse=True)
        return scored[:limit]

    except Exception as e:
        logger.debug(f"Supabase search failed: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════════


def _format_reflection_summary(reflection: Dict) -> str:
    """Format a reflection for display."""
    task = reflection.get("task", "Unknown task")[:80]
    outcome = reflection.get("outcome", "unknown")
    learnings = reflection.get("learnings", [])

    summary = f"[{outcome.upper()}] {task}\n"

    if learnings and isinstance(learnings, list):
        summary += "\n".join(f"  • {item}" for item in learnings[:3])
    elif isinstance(learnings, str):
        summary += learnings[:200]

    return summary


def _extract_relevant_section(content: str, query: str, max_len: int = 200) -> str:
    """Extract the most relevant section of a document."""
    query_lower = query.lower()
    lines = content.split("\n")

    # Find line closest to query
    best_section = ""
    for i, line in enumerate(lines):
        if query_lower in line.lower():
            # Return context around this line
            start = max(0, i - 1)
            end = min(len(lines), i + 3)
            section = "\n".join(lines[start:end])
            if len(section) < max_len:
                best_section = section
                break

    # If no exact line match, just return first max_len chars
    if not best_section:
        best_section = content[:max_len]

    return best_section.strip()


def _combine_results(results: Dict[str, List[Dict]]) -> List[Dict]:
    """Combine results from all sources with unified ranking."""
    all_results = []

    # Flatten all results
    for source_type, items in results.items():
        if items:
            all_results.extend(items)

    # Rank by composite score
    for item in all_results:
        # Combine importance (0-10) and relevance score (0-1)
        importance_norm = item.get("importance", 5) / 10.0
        relevance = item.get("score", 0)

        # Weight: 60% relevance, 40% importance
        item["combined_score"] = (relevance * 0.6) + (importance_norm * 0.4)

    all_results.sort(key=lambda x: x["combined_score"], reverse=True)

    return all_results


# ═══════════════════════════════════════════════════════════════
# Recall Injection (for prompts)
# ═══════════════════════════════════════════════════════════════


def inject_recalled_memory(
    prompt: str, query: str = None, context: Dict = None, limit: int = 3
) -> str:
    """
    Inject recalled memory into a job prompt.

    Args:
        prompt: Original job prompt
        query: Search query (if None, use task from context)
        context: Context dict (task, project, department)
        limit: Max memories to inject

    Returns:
        Enhanced prompt with memory context
    """
    if not query and not context:
        return prompt

    # Determine search query
    if not query:
        query = context.get("task", "")

    if not query:
        return prompt

    # Recall memories
    recall_result = recall(query, limit=limit, context=context)

    if not recall_result["combined"] or len(recall_result["combined"]) == 0:
        return prompt

    # Format for injection
    memory_section = _format_memory_for_injection(recall_result["combined"][:limit])

    return f"{memory_section}\n\n---\n\n{prompt}"


def _format_memory_for_injection(memories: List[Dict]) -> str:
    """Format memories for injection into prompts."""
    lines = ["## Recalled Context (from past work)\n"]

    for i, mem in enumerate(memories, 1):
        source_type = mem.get("source_type", "unknown")
        content = mem.get("content", "")[:150]
        score = mem.get("combined_score", 0)

        lines.append(f"\n{i}. [{source_type}] (relevance: {score:.0%})")
        lines.append(f"   {content}")

        # Add metadata if available
        meta = mem.get("metadata", {})
        if meta:
            if meta.get("outcome"):
                lines.append(f"   Outcome: {meta['outcome']}")
            if meta.get("cost_usd"):
                lines.append(f"   Cost: ${meta['cost_usd']:.2f}")

    lines.append(
        "\nRefer to these past experiences to avoid repeating mistakes and leverage successful patterns."
    )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Batch Recall (for analysis)
# ═══════════════════════════════════════════════════════════════


def recall_by_topic(topic: str, limit: int = 10) -> Dict:
    """Recall all memories related to a topic."""
    return recall(topic, limit=limit, memory_sources=["topics"])


def recall_by_project(project: str, limit: int = 10) -> Dict:
    """Recall learnings from a specific project."""
    return recall(
        project,
        limit=limit,
        memory_sources=["reflexion"],
        context={"project": project},
    )


def recall_recent(days: int = 7, limit: int = 20) -> List[Dict]:
    """Get recent memories from the last N days."""
    try:
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        results = []

        # Load from memories.jsonl
        mem_file = os.path.join(
            os.environ.get("OPENCLAW_DATA_DIR", "os.environ.get("OPENCLAW_DATA_DIR", "./data")"), "memories.jsonl"
        )
        if os.path.exists(mem_file):
            with open(mem_file) as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        ts_str = record.get("timestamp", "")
                        if ts_str:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            if ts > cutoff:
                                results.append(
                                    {
                                        "id": record.get("id", ""),
                                        "content": record.get("content", ""),
                                        "importance": record.get("importance", 5),
                                        "tags": record.get("tags", []),
                                        "timestamp": ts_str,
                                        "source_type": "semantic",
                                    }
                                )
                    except Exception:
                        continue

        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return results[:limit]

    except Exception as e:
        logger.error(f"Error retrieving recent memories: {e}")
        return []


if __name__ == "__main__":
    # Test the recall system
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        result = recall(query, limit=5)
        print("\n=== MEMORY RECALL ===")
        print(f"Query: {query}\n")
        print(f"Summary: {result['summary']}\n")
        print("Combined Results:")
        for i, mem in enumerate(result["combined"][:5], 1):
            print(f"\n{i}. [{mem['source_type']}] (score: {mem.get('combined_score', 0):.1%})")
            print(f"   {mem['content'][:100]}...")
    else:
        print("Usage: python memory_recall.py <query>")
        print(f"\nExample: python memory_recall.py 'deployment strategy'")
