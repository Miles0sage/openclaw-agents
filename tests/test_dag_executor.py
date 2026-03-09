"""Tests for dag_executor.py — DAG parallel workflow execution."""
import asyncio
import pytest
from dag_executor import (
    DAGNode, DAGWorkflow, DAGExecutor, DAGResult, NodeStatus,
    workflow_from_plan, parallel_workflow,
)


class TestDAGWorkflow:
    def test_add_node(self):
        dag = DAGWorkflow("test")
        dag.add_node("a", task="Task A")
        dag.add_node("b", task="Task B", depends_on=["a"])
        assert dag.node_count == 2
        assert dag.nodes["b"].depends_on == ["a"]

    def test_validate_valid(self):
        dag = DAGWorkflow("test")
        dag.add_node("a", task="A")
        dag.add_node("b", task="B", depends_on=["a"])
        errors = dag.validate()
        assert errors == []

    def test_validate_missing_dep(self):
        dag = DAGWorkflow("test")
        dag.add_node("a", task="A", depends_on=["nonexistent"])
        errors = dag.validate()
        assert len(errors) == 1
        assert "nonexistent" in errors[0]

    def test_validate_cycle(self):
        dag = DAGWorkflow("test")
        dag.add_node("a", task="A", depends_on=["b"])
        dag.add_node("b", task="B", depends_on=["a"])
        errors = dag.validate()
        assert any("ycle" in e for e in errors)

    def test_topological_layers_linear(self):
        dag = DAGWorkflow("test")
        dag.add_node("a", task="A")
        dag.add_node("b", task="B", depends_on=["a"])
        dag.add_node("c", task="C", depends_on=["b"])
        layers = dag.topological_layers()
        assert layers == [["a"], ["b"], ["c"]]

    def test_topological_layers_parallel(self):
        dag = DAGWorkflow("test")
        dag.add_node("a", task="A")
        dag.add_node("b", task="B")
        dag.add_node("c", task="C", depends_on=["a", "b"])
        layers = dag.topological_layers()
        assert len(layers) == 2
        assert set(layers[0]) == {"a", "b"}
        assert layers[1] == ["c"]

    def test_to_dict(self):
        dag = DAGWorkflow("test", name="Test Workflow")
        dag.add_node("a", task="A")
        d = dag.to_dict()
        assert d["workflow_id"] == "test"
        assert "a" in d["nodes"]


class TestDAGExecutor:
    @pytest.mark.asyncio
    async def test_simple_execution(self):
        dag = DAGWorkflow("test")
        dag.add_node("a", task="A")
        dag.add_node("b", task="B", depends_on=["a"])

        async def run_node(node: DAGNode):
            return f"Result of {node.node_id}"

        executor = DAGExecutor(max_concurrent=2)
        result = await executor.execute(dag, run_node)
        assert result.status == "completed"
        assert result.completed_nodes == 2
        assert result.failed_nodes == 0

    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        dag = DAGWorkflow("test")
        dag.add_node("a", task="A")
        dag.add_node("b", task="B")
        dag.add_node("c", task="C", depends_on=["a", "b"])

        execution_order = []

        async def run_node(node: DAGNode):
            execution_order.append(node.node_id)
            return f"Done {node.node_id}"

        executor = DAGExecutor(max_concurrent=3)
        result = await executor.execute(dag, run_node)
        assert result.completed_nodes == 3
        # c must come after a and b
        assert execution_order.index("c") > execution_order.index("a")
        assert execution_order.index("c") > execution_order.index("b")

    @pytest.mark.asyncio
    async def test_failure_propagation(self):
        dag = DAGWorkflow("test")
        dag.add_node("a", task="A")
        dag.add_node("b", task="B", depends_on=["a"])

        async def run_node(node: DAGNode):
            if node.node_id == "a":
                raise RuntimeError("Boom")
            return "ok"

        executor = DAGExecutor(max_concurrent=2)
        result = await executor.execute(dag, run_node)
        assert result.failed_nodes == 1
        assert result.skipped_nodes == 1
        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_fail_fast(self):
        dag = DAGWorkflow("test")
        dag.add_node("a", task="A")
        dag.add_node("b", task="B")
        dag.add_node("c", task="C", depends_on=["a", "b"])

        async def run_node(node: DAGNode):
            if node.node_id == "a":
                raise RuntimeError("Fail")
            return "ok"

        executor = DAGExecutor(max_concurrent=3)
        result = await executor.execute(dag, run_node, fail_fast=True)
        assert result.failed_nodes >= 1

    @pytest.mark.asyncio
    async def test_validation_error(self):
        dag = DAGWorkflow("test")
        dag.add_node("a", task="A", depends_on=["missing"])

        async def run_node(node: DAGNode):
            return "ok"

        executor = DAGExecutor()
        result = await executor.execute(dag, run_node)
        assert result.status == "failed"


class TestWorkflowBuilders:
    def test_workflow_from_plan(self):
        steps = [
            {"id": "s1", "task": "Step 1"},
            {"id": "s2", "task": "Step 2"},
            {"id": "s3", "task": "Step 3"},
        ]
        dag = workflow_from_plan("test", steps)
        assert dag.node_count == 3
        # Sequential by default
        layers = dag.topological_layers()
        assert len(layers) == 3

    def test_parallel_workflow(self):
        tasks = [
            {"id": "lint", "task": "Run linter"},
            {"id": "test", "task": "Run tests"},
        ]
        final = {"id": "deploy", "task": "Deploy"}
        dag = parallel_workflow("test", tasks, final_step=final)
        layers = dag.topological_layers()
        assert len(layers) == 2
        assert set(layers[0]) == {"lint", "test"}
        assert layers[1] == ["deploy"]
