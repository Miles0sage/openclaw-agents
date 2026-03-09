"""Tests for kg_engine.py — knowledge graph engine."""
import os
import tempfile
import pytest
from kg_engine import KGEngine, ToolChainRecommendation, AgentPerformance


@pytest.fixture
def kg():
    """Fresh KG engine with temp database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = KGEngine(db_path=path)
    yield engine
    os.unlink(path)


class TestKGEngine:
    def test_record_execution(self, kg):
        kg.record_execution(
            job_id="j1", agent_key="coder", tools_used=["file_read", "file_edit"],
            success=True, task_type="bug_fix", cost_usd=0.01, duration_ms=5000,
        )
        summary = kg.get_graph_summary()
        assert summary["total_jobs"] == 1
        assert summary["total_tools"] == 2

    def test_tool_edges(self, kg):
        kg.record_execution(
            job_id="j1", agent_key="coder", tools_used=["file_read", "file_edit", "shell_execute"],
            success=True,
        )
        pairs = kg.get_tool_pairs(min_count=1)
        assert len(pairs) >= 1

    def test_recommend_tools(self, kg):
        # Record several successful executions with same tool chain
        for i in range(5):
            kg.record_execution(
                job_id=f"j{i}", agent_key="coder",
                tools_used=["file_read", "grep_search", "file_edit"],
                success=True, task_type="bug_fix",
            )
        recs = kg.recommend_tools(agent_key="coder", task_type="bug_fix")
        assert len(recs) >= 1
        assert recs[0].usage_count == 5
        assert recs[0].success_rate == 1.0

    def test_recommend_tools_empty(self, kg):
        recs = kg.recommend_tools(agent_key="nonexistent")
        assert recs == []

    def test_agent_performance(self, kg):
        kg.record_execution(job_id="j1", agent_key="coder", tools_used=["file_read"], success=True, cost_usd=0.01)
        kg.record_execution(job_id="j2", agent_key="coder", tools_used=["file_edit"], success=False, cost_usd=0.02)

        perf = kg.get_agent_performance("coder")
        assert perf is not None
        assert perf.total_jobs == 2
        assert perf.success_rate == 0.5

    def test_agent_performance_nonexistent(self, kg):
        perf = kg.get_agent_performance("ghost")
        assert perf is None

    def test_tool_stats(self, kg):
        kg.record_execution(job_id="j1", agent_key="coder", tools_used=["file_read", "file_read"], success=True)
        stats = kg.get_tool_stats()
        assert len(stats) >= 1
        # file_read should have at least 1 use
        fr = [s for s in stats if s["tool_name"] == "file_read"]
        assert len(fr) == 1

    def test_graph_summary(self, kg):
        summary = kg.get_graph_summary()
        assert summary["total_jobs"] == 0
        assert summary["total_tools"] == 0

    def test_multiple_agents(self, kg):
        kg.record_execution(job_id="j1", agent_key="coder", tools_used=["file_read"], success=True)
        kg.record_execution(job_id="j2", agent_key="tester", tools_used=["shell_execute"], success=True)

        summary = kg.get_graph_summary()
        assert summary["total_jobs"] == 2
        assert len(summary["agents"]) == 2


class TestDataclasses:
    def test_tool_chain_recommendation_to_dict(self):
        r = ToolChainRecommendation(
            tools=["a", "b"], success_rate=0.95, usage_count=10,
            avg_duration_ms=1234.5, agent_key="coder",
        )
        d = r.to_dict()
        assert d["success_rate"] == 0.95
        assert d["tools"] == ["a", "b"]

    def test_agent_performance_to_dict(self):
        p = AgentPerformance(
            agent_key="coder", task_type="bug_fix", total_jobs=10,
            success_rate=0.9, avg_cost_usd=0.015, avg_duration_ms=3000,
            favorite_tools=["file_read", "file_edit"],
        )
        d = p.to_dict()
        assert d["total_jobs"] == 10
        assert len(d["favorite_tools"]) == 2
