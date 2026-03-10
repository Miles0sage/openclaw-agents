"""Verify that new v4.2 modules are importable and singletons work correctly."""
import os
import pytest
import asyncio
import json


# ============================================================================
# Streaming Module Tests
# ============================================================================

class TestStreamingWiring:
    """Tests for streaming.py singleton and initialization."""

    def test_streaming_import(self):
        """Verify streaming module can be imported."""
        from streaming import StreamManager, StreamEvent, get_stream_manager, init_stream_manager
        assert StreamManager is not None
        assert StreamEvent is not None
        assert get_stream_manager is not None
        assert init_stream_manager is not None

    def test_streaming_singleton(self):
        """Verify get_stream_manager returns a singleton."""
        from streaming import get_stream_manager, StreamManager
        sm1 = get_stream_manager()
        sm2 = get_stream_manager()
        assert sm1 is sm2
        assert isinstance(sm1, StreamManager)

    def test_streaming_init_singleton(self):
        """Verify init_stream_manager initializes and returns singleton."""
        from streaming import init_stream_manager, get_stream_manager
        sm = init_stream_manager()
        assert sm is not None
        assert sm is get_stream_manager()

    def test_streaming_push_event(self):
        """Verify push_event works and retrieves events."""
        from streaming import get_stream_manager, StreamEvent
        sm = get_stream_manager()
        job_id = "test_job_123"
        event = StreamEvent(
            event_type="phase_change",
            job_id=job_id,
            phase="EXECUTE"
        )
        sm.push_event(job_id, event)
        buf = sm.get_buffer(job_id)
        assert buf is not None
        events = buf.get_since(0)
        assert len(events) > 0

    def test_streaming_emit_phase_change(self):
        """Verify emit_phase_change creates proper event."""
        from streaming import get_stream_manager
        sm = get_stream_manager()
        job_id = "test_job_phase"
        sm.emit_phase_change(job_id, "PLAN", agent="coder_agent")
        buf = sm.get_buffer(job_id)
        events = buf.get_since(0)
        assert len(events) > 0
        assert events[-1][1].event_type == "phase_change"

    def test_streaming_sse_format(self):
        """Verify StreamEvent.to_sse() produces valid SSE format."""
        from streaming import StreamEvent
        event = StreamEvent(
            event_type="progress",
            job_id="job_123",
            message="Running",
            progress_pct=0.5
        )
        sse_str = event.to_sse()
        assert "event: progress" in sse_str
        assert "data:" in sse_str
        assert "job_123" in sse_str


# ============================================================================
# Tracer Module Tests
# ============================================================================

class TestTracerWiring:
    """Tests for otel_tracer.py singleton and initialization."""

    def test_tracer_import(self):
        """Verify tracer module can be imported."""
        from otel_tracer import Tracer, Span, get_tracer, init_tracer
        assert Tracer is not None
        assert Span is not None
        assert get_tracer is not None
        assert init_tracer is not None

    def test_tracer_singleton(self):
        """Verify get_tracer returns a singleton."""
        from otel_tracer import get_tracer, Tracer
        t1 = get_tracer()
        t2 = get_tracer()
        assert t1 is t2
        assert isinstance(t1, Tracer)

    def test_tracer_init_custom_path(self):
        """Verify init_tracer with custom export path."""
        path = os.path.join("/tmp", "test_tracer_%s.jsonl" % os.getpid())
        try:
            from otel_tracer import init_tracer
            tracer = init_tracer(export_path=path)
            assert tracer is not None
            assert tracer._export_path == path
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_tracer_span_context_manager(self):
        """Verify tracer span works as context manager."""
        path = os.path.join("/tmp", "test_span_ctx_%s.jsonl" % os.getpid())
        try:
            from otel_tracer import init_tracer
            tracer = init_tracer(export_path=path)

            with tracer.span("test_operation", trace_id="test_trace_123") as span:
                span.set_attribute("key", "value")
                assert span.span_id is not None

            # Verify span was written
            assert os.path.exists(path)
            with open(path, "r") as f:
                line = f.readline()
                assert "test_trace_123" in line
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_tracer_get_trace(self):
        """Verify get_trace retrieves recorded spans."""
        path = os.path.join("/tmp", "test_get_trace_%s.jsonl" % os.getpid())
        try:
            from otel_tracer import init_tracer
            tracer = init_tracer(export_path=path)
            trace_id = "test_trace_456"

            with tracer.span("op1", trace_id=trace_id):
                pass

            traces = tracer.get_trace(trace_id)
            assert len(traces) > 0
            assert traces[0]["trace_id"] == trace_id
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_tracer_span_attributes(self):
        """Verify span attributes are stored."""
        path = os.path.join("/tmp", "test_span_attrs_%s.jsonl" % os.getpid())
        try:
            from otel_tracer import init_tracer
            tracer = init_tracer(export_path=path)

            with tracer.span("test_op", trace_id="test_attrs") as span:
                span.set_attribute("agent", "coder_agent")
                span.set_attribute("tool_count", 5)

            traces = tracer.get_trace("test_attrs")
            assert len(traces) > 0
            assert "agent" in traces[0]["attributes"]
        finally:
            if os.path.exists(path):
                os.unlink(path)


# ============================================================================
# Judge Module Tests
# ============================================================================

class TestJudgeWiring:
    """Tests for llm_judge.py singleton and initialization."""

    def test_judge_import(self):
        """Verify judge module can be imported."""
        from llm_judge import LLMJudge, JudgeResult, get_judge, init_judge
        assert LLMJudge is not None
        assert JudgeResult is not None
        assert get_judge is not None
        assert init_judge is not None

    def test_judge_singleton(self):
        """Verify get_judge returns a singleton."""
        from llm_judge import get_judge, LLMJudge
        j1 = get_judge()
        j2 = get_judge()
        assert j1 is j2
        assert isinstance(j1, LLMJudge)

    def test_judge_init_singleton(self):
        """Verify init_judge initializes singleton."""
        from llm_judge import init_judge, get_judge
        judge = init_judge()
        assert judge is not None
        assert judge is get_judge()

    def test_judge_get_rubric(self):
        """Verify get_rubric returns correct rubrics."""
        from llm_judge import get_judge
        judge = get_judge()

        coder_rubric = judge.get_rubric("coder_agent")
        assert len(coder_rubric) > 0
        assert any(d["dimension"] == "correctness" for d in coder_rubric)

        default_rubric = judge.get_rubric("unknown_agent")
        assert len(default_rubric) > 0

    def test_judge_result_dataclass(self):
        """Verify JudgeResult dataclass works."""
        from llm_judge import JudgeResult, DimensionScore

        dims = [
            DimensionScore(dimension="correctness", score=0.85, reasoning="Good"),
        ]
        result = JudgeResult(
            job_id="job_123",
            agent_key="coder_agent",
            overall_score=0.85,
            confidence=0.8,
            dimensions=dims,
        )
        assert result.job_id == "job_123"
        assert result.passed is True
        assert result.timestamp != ""

    @pytest.mark.asyncio
    async def test_judge_score_output_heuristic(self):
        """Verify score_output with heuristic fallback."""
        from llm_judge import get_judge
        judge = get_judge()

        result = await judge.score_output(
            job_id="test_job",
            agent_key="coder_agent",
            task_description="Write a function to add two numbers",
            agent_output="def add(a, b):\n    return a + b",
        )

        assert result.job_id == "test_job"
        assert result.overall_score >= 0.0
        assert result.overall_score <= 1.0
        assert result.eval_model == "heuristic"  # Falls back to heuristic when no model_fn


# ============================================================================
# Knowledge Graph Module Tests
# ============================================================================

class TestKGWiring:
    """Tests for kg_engine.py singleton and initialization."""

    def test_kg_import(self):
        """Verify KG engine module can be imported."""
        from kg_engine import KGEngine, get_kg_engine, init_kg_engine
        assert KGEngine is not None
        assert get_kg_engine is not None
        assert init_kg_engine is not None

    def test_kg_singleton(self):
        """Verify get_kg_engine returns a singleton."""
        from kg_engine import get_kg_engine, KGEngine
        kg1 = get_kg_engine()
        kg2 = get_kg_engine()
        assert kg1 is kg2
        assert isinstance(kg1, KGEngine)

    def test_kg_init_custom_path(self):
        """Verify init_kg_engine with custom db path."""
        db_path = os.path.join("/tmp", "test_kg_%s.db" % os.getpid())
        try:
            from kg_engine import init_kg_engine
            kg = init_kg_engine(db_path=db_path)
            assert kg is not None
            assert kg._db_path == db_path
            assert os.path.exists(db_path)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_kg_record_execution(self):
        """Verify record_execution stores job data."""
        db_path = os.path.join("/tmp", "test_kg_exec_%s.db" % os.getpid())
        try:
            from kg_engine import init_kg_engine
            kg = init_kg_engine(db_path=db_path)

            kg.record_execution(
                job_id="job_test_001",
                agent_key="coder_agent",
                tools_used=["file_read", "file_edit"],
                success=True,
                task_type="bug_fix",
                cost_usd=0.50,
                duration_ms=5000.0,
                quality_score=0.85,
            )

            perf = kg.get_agent_performance("coder_agent")
            assert perf is not None
            assert perf.total_jobs == 1
            assert perf.success_rate == 1.0
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_kg_recommend_tools(self):
        """Verify recommend_tools returns suggestions."""
        db_path = os.path.join("/tmp", "test_kg_rec_%s.db" % os.getpid())
        try:
            from kg_engine import init_kg_engine
            kg = init_kg_engine(db_path=db_path)

            # Record some successful jobs
            for i in range(3):
                kg.record_execution(
                    job_id="job_%d" % i,
                    agent_key="coder_agent",
                    tools_used=["file_read", "grep_search", "file_edit"],
                    success=True,
                    cost_usd=0.50,
                    duration_ms=5000.0,
                )

            # Get recommendations
            recs = kg.recommend_tools(agent_key="coder_agent")
            assert len(recs) > 0
            assert recs[0].tools[0] in ["file_read", "grep_search", "file_edit"]
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_kg_get_graph_summary(self):
        """Verify get_graph_summary returns stats."""
        db_path = os.path.join("/tmp", "test_kg_sum_%s.db" % os.getpid())
        try:
            from kg_engine import init_kg_engine
            kg = init_kg_engine(db_path=db_path)

            kg.record_execution(
                job_id="job_summary_test",
                agent_key="coder_agent",
                tools_used=["file_read"],
                success=True,
            )

            summary = kg.get_graph_summary()
            assert summary["total_jobs"] == 1
            assert summary["overall_success_rate"] == 1.0
            assert len(summary["agents"]) > 0
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ============================================================================
# DAG Executor Module Tests
# ============================================================================

class TestDAGWiring:
    """Tests for dag_executor.py imports and basic functionality."""

    def test_dag_import(self):
        """Verify DAG executor module can be imported."""
        from dag_executor import (
            DAGWorkflow, DAGNode, DAGExecutor, DAGResult,
            NodeStatus, workflow_from_plan, parallel_workflow
        )
        assert DAGWorkflow is not None
        assert DAGNode is not None
        assert DAGExecutor is not None
        assert DAGResult is not None
        assert NodeStatus is not None

    def test_dag_workflow_creation(self):
        """Verify DAGWorkflow can be created and nodes added."""
        from dag_executor import DAGWorkflow

        dag = DAGWorkflow("test_workflow")
        dag.add_node("step1", task="First task", agent_key="coder_agent")
        dag.add_node("step2", task="Second task", agent_key="test_agent", depends_on=["step1"])

        assert dag.node_count == 2
        assert "step1" in dag.nodes
        assert "step2" in dag.nodes

    def test_dag_validation(self):
        """Verify DAG validation detects errors."""
        from dag_executor import DAGWorkflow

        dag = DAGWorkflow("test_validate")
        dag.add_node("step1", task="Task 1")
        dag.add_node("step2", task="Task 2", depends_on=["nonexistent"])

        errors = dag.validate()
        assert len(errors) > 0
        assert "nonexistent" in errors[0]

    def test_dag_topological_sort(self):
        """Verify topological layer computation."""
        from dag_executor import DAGWorkflow

        dag = DAGWorkflow("test_topo")
        dag.add_node("a", task="Task A")
        dag.add_node("b", task="Task B")
        dag.add_node("c", task="Task C", depends_on=["a", "b"])
        dag.add_node("d", task="Task D", depends_on=["c"])

        layers = dag.topological_layers()
        assert len(layers) == 3
        assert set(layers[0]) == {"a", "b"}  # Both run first
        assert "c" in layers[1]  # Runs after a and b
        assert "d" in layers[2]  # Runs last

    def test_dag_cycle_detection(self):
        """Verify cycles are detected in DAG."""
        from dag_executor import DAGWorkflow

        dag = DAGWorkflow("test_cycle")
        dag.add_node("a", task="Task A", depends_on=["b"])
        dag.add_node("b", task="Task B", depends_on=["a"])  # Cycle!

        errors = dag.validate()
        assert any("Cycle" in e for e in errors)

    @pytest.mark.asyncio
    async def test_dag_executor_execute(self):
        """Verify DAGExecutor can execute a simple workflow."""
        from dag_executor import DAGWorkflow, DAGExecutor, NodeStatus

        dag = DAGWorkflow("test_exec")
        dag.add_node("step1", task="First")
        dag.add_node("step2", task="Second", depends_on=["step1"])

        executor = DAGExecutor(max_concurrent=2)

        async def run_node(node):
            await asyncio.sleep(0.01)
            return "Completed %s" % node.node_id

        result = await executor.execute(dag, run_node)

        assert result.status == "completed"
        assert result.total_nodes == 2
        assert result.completed_nodes == 2
        assert result.failed_nodes == 0

    @pytest.mark.asyncio
    async def test_dag_executor_failure(self):
        """Verify DAGExecutor handles failures."""
        from dag_executor import DAGWorkflow, DAGExecutor, NodeStatus

        dag = DAGWorkflow("test_fail")
        dag.add_node("good", task="Good task")
        dag.add_node("bad", task="Bad task", depends_on=["good"])

        executor = DAGExecutor(max_concurrent=2)

        async def run_node(node):
            if node.node_id == "bad":
                raise ValueError("Intentional failure")
            return "ok"

        result = await executor.execute(dag, run_node)

        assert result.failed_nodes > 0
        assert result.status in ["failed", "partial_failure"]

    def test_workflow_from_plan(self):
        """Verify workflow_from_plan helper."""
        from dag_executor import workflow_from_plan

        plan = [
            {"id": "research", "task": "Research", "agent": "researcher_agent"},
            {"id": "implement", "task": "Implement", "agent": "coder_agent"},
            {"id": "review", "task": "Review", "agent": "reviewer_agent"},
        ]

        dag = workflow_from_plan("plan_test", plan)

        assert dag.node_count == 3
        assert dag.nodes["implement"].depends_on == ["research"]  # Sequential by default
        assert dag.nodes["review"].depends_on == ["implement"]

    def test_parallel_workflow(self):
        """Verify parallel_workflow helper."""
        from dag_executor import parallel_workflow

        tasks = [
            {"id": "lint", "task": "Lint"},
            {"id": "test", "task": "Test"},
            {"id": "type_check", "task": "Type Check"},
        ]
        final = {"id": "deploy", "task": "Deploy"}

        dag = parallel_workflow("parallel_test", tasks, final)

        assert dag.node_count == 4
        assert dag.nodes["lint"].depends_on == []
        assert dag.nodes["test"].depends_on == []
        assert dag.nodes["deploy"].depends_on == ["lint", "test", "type_check"]


# ============================================================================
# Integration Tests
# ============================================================================

class TestAllImports:
    """Test that all v4.2 modules can be imported together."""

    def test_all_imports(self):
        """Verify all v4.2 modules can be imported without conflicts."""
        import streaming
        import otel_tracer
        import llm_judge
        import kg_engine
        import dag_executor

        assert streaming is not None
        assert otel_tracer is not None
        assert llm_judge is not None
        assert kg_engine is not None
        assert dag_executor is not None

    def test_no_import_errors(self):
        """Verify importing all modules doesn't raise exceptions."""
        try:
            from streaming import get_stream_manager
            from otel_tracer import get_tracer
            from llm_judge import get_judge
            from kg_engine import get_kg_engine
            from dag_executor import DAGWorkflow, DAGExecutor
        except ImportError as e:
            pytest.fail("Failed to import v4.2 modules: %s" % e)

    def test_all_singletons_initialized(self):
        """Verify all v4.2 singletons initialize without error."""
        from streaming import get_stream_manager
        from otel_tracer import get_tracer
        from llm_judge import get_judge
        from kg_engine import get_kg_engine

        sm = get_stream_manager()
        tr = get_tracer()
        jd = get_judge()
        kg = get_kg_engine()

        assert sm is not None
        assert tr is not None
        assert jd is not None
        assert kg is not None
