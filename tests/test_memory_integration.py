"""
Integration tests for unified memory recall system.

Tests:
1. Tool schema validation
2. Agent tool execution
3. Gateway API endpoints
4. Multi-source recall (semantic, reflexion, topics, supabase)
5. Result ranking and combination
"""

import json
import pytest
import sys
import os

# Add openclaw to path
sys.path.insert(0, '.')

from agent_tools import AGENT_TOOLS, execute_tool
from memory_recall import recall, inject_recalled_memory, recall_by_topic, recall_recent


class TestMemoryRecallSchema:
    """Test tool schema validation."""

    def test_recall_memory_tool_exists(self):
        """Verify recall_memory tool is in AGENT_TOOLS."""
        tools = [t for t in AGENT_TOOLS if t['name'] == 'recall_memory']
        assert len(tools) == 1, "recall_memory tool not found in AGENT_TOOLS"

    def test_recall_memory_schema(self):
        """Verify recall_memory schema is correct."""
        tool = [t for t in AGENT_TOOLS if t['name'] == 'recall_memory'][0]
        schema = tool['input_schema']

        assert schema['type'] == 'object'
        assert 'query' in schema['properties']
        assert 'query' in schema['required']
        assert 'limit' in schema['properties']
        assert 'memory_sources' in schema['properties']
        assert 'project' in schema['properties']
        assert 'department' in schema['properties']

    def test_recall_memory_description(self):
        """Verify recall_memory has helpful description."""
        tool = [t for t in AGENT_TOOLS if t['name'] == 'recall_memory'][0]
        assert 'unified memory recall' in tool['description'].lower()
        assert 'semantic' in tool['description'].lower()


class TestMemoryRecallExecution:
    """Test agent tool execution."""

    def test_execute_recall_tool_basic(self):
        """Execute recall_memory tool with basic query."""
        result = execute_tool("recall_memory", {
            "query": "deployment strategy",
            "limit": 3
        })

        assert isinstance(result, str)
        assert len(result) > 0
        assert "Memory Recall" in result or "results" in result.lower()

    def test_execute_recall_tool_with_sources(self):
        """Execute recall_memory with specific sources."""
        result = execute_tool("recall_memory", {
            "query": "deployment strategy",
            "limit": 2,
            "memory_sources": ["semantic"]
        })

        assert isinstance(result, str)
        assert len(result) > 0

    def test_execute_recall_tool_with_context(self):
        """Execute recall_memory with project context."""
        result = execute_tool("recall_memory", {
            "query": "deployment strategy",
            "limit": 3,
            "project": "openclaw"
        })

        assert isinstance(result, str)
        assert len(result) > 0


class TestMemoryRecallFunctions:
    """Test memory recall library functions."""

    def test_recall_basic(self):
        """Test recall() function returns valid structure."""
        result = recall("deployment strategy", limit=3)

        assert isinstance(result, dict)
        assert 'query' in result
        assert 'timestamp' in result
        assert 'results' in result
        assert 'combined' in result
        assert 'summary' in result

    def test_recall_combined_ranking(self):
        """Test that combined results are properly ranked."""
        result = recall("deployment strategy", limit=5)

        combined = result.get('combined', [])
        if combined:
            # Results should have combined_score
            for item in combined:
                assert 'combined_score' in item
                assert 0 <= item['combined_score'] <= 1

            # Results should be sorted by combined_score descending
            scores = [item['combined_score'] for item in combined]
            assert scores == sorted(scores, reverse=True)

    def test_recall_multiple_sources(self):
        """Test recall with multiple sources."""
        result = recall(
            "deployment",
            limit=3,
            memory_sources=["semantic", "reflexion", "topics"]
        )

        results = result.get('results', {})
        # At least some sources should have results or be tried
        assert isinstance(results, dict)

    def test_recall_with_context(self):
        """Test recall with project/department context."""
        result = recall(
            "deployment",
            limit=3,
            context={"project": "openclaw", "department": "engineering"}
        )

        assert result['context']['project'] == "openclaw"
        assert result['context']['department'] == "engineering"

    def test_recall_by_topic(self):
        """Test recall_by_topic() function."""
        result = recall_by_topic("deployment", limit=5)

        assert isinstance(result, dict)
        assert 'query' in result
        assert 'results' in result

    def test_recall_recent(self):
        """Test recall_recent() function."""
        result = recall_recent(days=7, limit=10)

        assert isinstance(result, list)
        # Should return list of memory items
        for item in result:
            assert 'content' in item
            assert 'timestamp' in item

    def test_inject_recalled_memory(self):
        """Test inject_recalled_memory() for prompt enhancement."""
        prompt = "Deploy the application to production"
        context = {
            "task": "Deploy the application",
            "project": "openclaw"
        }

        enhanced = inject_recalled_memory(prompt, context=context, limit=2)

        assert len(enhanced) >= len(prompt)
        # Either has memory context or returns original prompt
        assert "Recalled Context" in enhanced or enhanced == prompt

    def test_inject_recalled_memory_with_query(self):
        """Test inject_recalled_memory with explicit query."""
        prompt = "Deploy the application to production"

        enhanced = inject_recalled_memory(
            prompt,
            query="deployment strategy",
            limit=2
        )

        assert isinstance(enhanced, str)
        assert len(enhanced) > 0


class TestMemorySourceIntegration:
    """Test integration of all memory sources."""

    def test_semantic_memory_source(self):
        """Verify semantic memory search works."""
        result = recall(
            "deployment",
            limit=3,
            memory_sources=["semantic"]
        )

        semantic_results = result.get('results', {}).get('semantic', [])
        # May be empty if no semantic memories, but shouldn't error
        assert isinstance(semantic_results, list)

    def test_topics_memory_source(self):
        """Verify topic file search works."""
        result = recall(
            "memory",
            limit=3,
            memory_sources=["topics"]
        )

        topic_results = result.get('results', {}).get('topics', [])
        # May be empty, but should be a list
        assert isinstance(topic_results, list)

    def test_combined_ranking_weighted(self):
        """Verify combined ranking uses proper weighting."""
        result = recall(
            "deployment",
            limit=5,
            memory_sources=["semantic", "reflexion", "topics", "supabase"]
        )

        combined = result.get('combined', [])
        if combined:
            # Each item should have:
            # - importance (0-10)
            # - score (0-1 relevance)
            # - combined_score = (score * 0.6) + (importance/10 * 0.4)
            for item in combined:
                if 'importance' in item and 'score' in item:
                    importance_norm = item['importance'] / 10.0
                    expected = (item['score'] * 0.6) + (importance_norm * 0.4)
                    actual = item['combined_score']
                    # Allow small floating point error
                    assert abs(expected - actual) < 0.01


class TestErrorHandling:
    """Test error handling in memory system."""

    def test_empty_query_handling(self):
        """Test recall with empty query."""
        result = recall("", limit=3)
        # Should not crash, may return empty results
        assert 'results' in result

    def test_invalid_source(self):
        """Test recall with invalid source."""
        result = recall(
            "deployment",
            limit=3,
            memory_sources=["invalid_source"]
        )
        # Should handle gracefully
        assert 'results' in result

    def test_missing_memory_modules(self):
        """Test graceful degradation if memory modules unavailable."""
        # This is handled by try/except in memory_recall.py
        # Just verify it doesn't crash the tool
        result = execute_tool("recall_memory", {"query": "test"})
        assert isinstance(result, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
