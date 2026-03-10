"""
Semantic Memory Examples — Real-world usage patterns for agents

These examples show how CoderClaw, PA Worker, and other agents
use the semantic memory system to search, save, and manage context.
"""

# ═══════════════════════════════════════════════════════════════
# EXAMPLE 1: Agent Searching for Deployment Strategy
# ═══════════════════════════════════════════════════════════════

def example_pa_worker_context_search():
    """
    PA Worker needs context about deployment strategy.
    Uses semantic search to find relevant docs even with different wording.
    """
    import sys
    sys.path.insert(0, '.')
    from agent_tools import _search_memory

    # User asks: "How should we deploy to production?"
    # PA Worker searches with semantic meaning:
    result = _search_memory(
        "deployment strategy production environment setup",
        limit=5
    )

    print("=== PA Worker Context Search ===")
    print(result)
    # Output:
    # Found 5 semantic matches:
    # [2456a857] (imp=7, sim=43%) memory_md:openclaw-deployment-status.md: ...
    # [65648ed9] (imp=7, sim=34%) memory_md:business-strategy.md: ...
    # ...


# ═══════════════════════════════════════════════════════════════
# EXAMPLE 2: Agent Saving Important Decision
# ═══════════════════════════════════════════════════════════════

def example_save_critical_decision():
    """
    CodeGen Pro makes a critical architectural decision.
    Saves it to memory for future reference.
    """
    import sys
    sys.path.insert(0, '.')
    from agent_tools import _save_memory

    # Save decision with high importance
    result = _save_memory(
        content="Decision: Migrating from JWT to OAuth2 for SSO integration. "
                "Using Auth0 provider, requires OIDC discovery endpoint.",
        tags=["authentication", "oauth2", "architecture"],
        importance=9  # Critical decision
    )

    print("=== Save Critical Decision ===")
    print(result)
    # Output: Memory saved (id=abc123): Decision: Migrating from JWT to OAuth2...


# ═══════════════════════════════════════════════════════════════
# EXAMPLE 3: Semantic Search Finds Related Concepts
# ═══════════════════════════════════════════════════════════════

def example_semantic_search_related_concepts():
    """
    User asks about something slightly different, but semantic search
    finds the related concept from memory.
    """
    import sys
    sys.path.insert(0, '.')
    from semantic_memory import semantic_search

    # Query: "How do we handle user login?"
    # System searches semantically and finds authentication docs
    results = semantic_search(
        "user login session management",
        limit=3
    )

    print("=== Semantic Search: Related Concepts ===")
    for i, result in enumerate(results, 1):
        print(f"{i}. [{result['id']}] {result['source']}")
        print(f"   Similarity: {result['score']:.1%}")
        print(f"   Importance: {result['importance']}")
        print(f"   Preview: {result['content'][:100]}...\n")


# ═══════════════════════════════════════════════════════════════
# EXAMPLE 4: Rebuild Index After Many Updates
# ═══════════════════════════════════════════════════════════════

def example_rebuild_index():
    """
    After a big working session with many memory updates,
    rebuild the semantic index to include all new documents.
    """
    import sys
    sys.path.insert(0, '.')
    from agent_tools import _rebuild_semantic_index

    result = _rebuild_semantic_index()

    print("=== Rebuild Semantic Index ===")
    print(result)
    # Output: Semantic memory index rebuilt successfully


# ═══════════════════════════════════════════════════════════════
# EXAMPLE 5: Memory Compaction Before Context Cleanup
# ═══════════════════════════════════════════════════════════════

def example_memory_compaction():
    """
    Before long break or context compaction, flush important facts
    to MEMORY.md so they survive the cleanup.
    """
    import sys
    sys.path.insert(0, '.')
    from agent_tools import _flush_memory_before_compaction

    important_facts = [
        "Decision: Using Supabase RLS for row-level security (critical for multi-tenant)",
        "Critical: Email verification required before account activation",
        "Learning: JWT refresh tokens need rotation after 7 days",
        "TODO: Update all services to use new authentication middleware",
        "Bug: Session timeout not working on mobile Safari (known issue)",
    ]

    result = _flush_memory_before_compaction(important_facts)

    print("=== Memory Compaction ===")
    print(result)
    # Output: Flushed 5 items to MEMORY.md: /root/.claude/projects/-root/memory/MEMORY.md


# ═══════════════════════════════════════════════════════════════
# EXAMPLE 6: Pattern-based Fact Extraction
# ═══════════════════════════════════════════════════════════════

def example_auto_extract_facts():
    """
    Automatically extract important facts from a conversation
    using pattern detection.
    """
    import sys
    sys.path.insert(0, '.')
    from memory_compaction import get_compactor

    conversation = """
    Miles: We need better error handling
    Claude: Important: Most timeouts are in the database query layer
    Claude: Decision: We're switching to connection pooling with pgBouncer
    Claude: Critical: Backup the production database before deploying
    Claude: Learning: Prepared statements reduce SQL injection risk by 95%
    Miles: When can we deploy?
    Claude: TODO: Add monitoring alerts for connection pool saturation
    """

    compactor = get_compactor()
    facts = compactor.extract_important_facts(conversation)

    print("=== Auto-Extracted Facts ===")
    for fact in facts:
        print(f"[imp={fact['importance']}] {fact['tags']}")
        print(f"  {fact['content']}\n")


# ═══════════════════════════════════════════════════════════════
# EXAMPLE 7: Multi-Agent Memory Sharing
# ═══════════════════════════════════════════════════════════════

def example_multi_agent_memory():
    """
    Multiple agents sharing the same semantic memory index.
    PA Worker finds context, CodeGen Pro saves findings.
    """
    import sys
    sys.path.insert(0, '.')
    from agent_tools import _search_memory, _save_memory

    # PA Worker searches for API documentation pattern
    print("=== Multi-Agent Memory Sharing ===")
    print("\n[PA Worker] Searching for API patterns...")
    context = _search_memory("REST API endpoint design best practices", limit=2)
    print(context[:200])

    # CodeGen Pro discovers a bug pattern and saves it
    print("\n[CodeGen Pro] Saving discovered bug pattern...")
    bug_finding = _save_memory(
        content="Bug pattern: Race condition in concurrent session writes. "
                "Root cause: Missing database transaction isolation level. "
                "Fix: Use SERIALIZABLE isolation level for session updates.",
        tags=["concurrency", "database", "session"],
        importance=8
    )
    print(bug_finding)

    # PA Worker searches again and finds the newly saved finding
    print("\n[PA Worker] Searching for session concurrency issues...")
    context = _search_memory("concurrent session database race condition", limit=2)
    print(context[:200])


# ═══════════════════════════════════════════════════════════════
# EXAMPLE 8: Importance Scoring Best Practices
# ═══════════════════════════════════════════════════════════════

def example_importance_scoring():
    """
    Guide to importance scoring:
    - 9: Critical go/no-go decisions, security vulnerabilities
    - 8: Important milestones, API changes, major refactors
    - 7: Key learnings, debugging breakthroughs, patterns
    - 6: Implementation details, TODOs, architecture notes
    - 5: Reference information, defaults, parameters
    - 1-4: Minor details, edge cases
    """
    import sys
    sys.path.insert(0, '.')
    from agent_tools import _save_memory

    print("=== Importance Scoring Examples ===\n")

    # 9 - Critical decision
    _save_memory(
        "CRITICAL DECISION: Do not deploy to production without security audit.",
        tags=["security", "deployment"],
        importance=9
    )
    print("[9] Critical: Security decision, blocks deployment")

    # 8 - Important milestone
    _save_memory(
        "Milestone: OAuth2 authentication now fully integrated with all services.",
        tags=["authentication"],
        importance=8
    )
    print("[8] Important: Feature milestone, affects multiple services")

    # 7 - Key learning
    _save_memory(
        "Learning: Database connection pooling increased throughput by 300%.",
        tags=["performance", "database"],
        importance=7
    )
    print("[7] Learning: Performance insight, useful for future optimization")

    # 6 - Implementation detail
    _save_memory(
        "TODO: Add rate limiting middleware to API endpoints (max 100 req/min).",
        tags=["api", "middleware"],
        importance=6
    )
    print("[6] Implementation: Action item, specific to current project")

    # 5 - Reference information
    _save_memory(
        "Reference: Default JWT expiry is 1 hour, refresh token is 7 days.",
        tags=["authentication", "config"],
        importance=5
    )
    print("[5] Reference: Configuration info, useful for future lookups")


# ═══════════════════════════════════════════════════════════════
# EXAMPLE 9: Semantic Search vs Keyword Search
# ═══════════════════════════════════════════════════════════════

def example_semantic_vs_keyword():
    """
    Show the difference between semantic and keyword search.
    Semantic search finds related concepts with different wording.
    """
    import sys
    sys.path.insert(0, '.')
    from semantic_memory import get_semantic_index

    index = get_semantic_index()

    print("=== Semantic vs Keyword Search ===\n")

    # Semantic search: finds related concept
    print("[SEMANTIC] Query: 'user authentication and authorization'")
    results = index.search("user authentication and authorization", limit=2)
    for r in results:
        print(f"  ✓ {r['source'][:40]:40} ({r['score']:.1%})")

    # Keyword search would need exact words
    print("\n[KEYWORD] Query: 'OAuth2'")
    keyword_results = [r for r in index.documents
                      if 'oauth' in r[0].lower() or 'oauth' in ' '.join(r[3]).lower()]
    if keyword_results:
        print(f"  ✓ Found {len(keyword_results)} exact matches")
    else:
        print("  ✗ No exact matches")


if __name__ == "__main__":
    import sys

    examples = {
        "1": ("PA Worker Context Search", example_pa_worker_context_search),
        "2": ("Save Critical Decision", example_save_critical_decision),
        "3": ("Semantic Search Relations", example_semantic_search_related_concepts),
        "4": ("Rebuild Index", example_rebuild_index),
        "5": ("Memory Compaction", example_memory_compaction),
        "6": ("Auto Extract Facts", example_auto_extract_facts),
        "7": ("Multi-Agent Memory", example_multi_agent_memory),
        "8": ("Importance Scoring", example_importance_scoring),
        "9": ("Semantic vs Keyword", example_semantic_vs_keyword),
    }

    if len(sys.argv) > 1 and sys.argv[1] in examples:
        name, func = examples[sys.argv[1]]
        print(f"\n{'=' * 70}")
        print(f"  {name.upper()}")
        print(f"{'=' * 70}\n")
        func()
    else:
        print("\nAvailable examples:")
        for key, (name, _) in examples.items():
            print(f"  {key}. {name}")
        print(f"\nRun: python examples/semantic_memory_examples.py <number>")
