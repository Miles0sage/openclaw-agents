"""
OpenClaw DAG (Directed Acyclic Graph) Workflow Executor
=========================================================
Executes independent subtasks in parallel using topological sorting.
When a job decomposes into multiple independent steps, DAG executor
runs them concurrently instead of sequentially — 2-3x faster.

Usage:
    dag = DAGWorkflow("deploy_feature")
    dag.add_node("lint", task="Run linter", agent="coder_agent")
    dag.add_node("test", task="Run tests", agent="test_agent")
    dag.add_node("review", task="Code review", agent="reviewer_agent", depends_on=["lint", "test"])
    dag.add_node("deploy", task="Deploy to prod", agent="coder_agent", depends_on=["review"])

    executor = DAGExecutor(max_concurrent=3)
    results = await executor.execute(dag, run_node_fn)

Architecture:
    - DAGWorkflow: graph definition (nodes + edges)
    - DAGExecutor: async execution engine with topological sort
    - Kahn's algorithm for topological ordering
    - asyncio.Semaphore for concurrency control
    - Per-node result tracking with error propagation
"""

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

logger = logging.getLogger("openclaw.dag")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"       # Skipped due to upstream failure


@dataclass
class DAGNode:
    """A single task node in the workflow graph."""
    node_id: str
    task: str                            # Human-readable task description
    agent_key: str = ""                  # Which agent should execute this
    depends_on: List[str] = field(default_factory=list)
    status: NodeStatus = NodeStatus.PENDING
    result: Any = None
    error: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0
    cost_usd: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "task": self.task,
            "agent_key": self.agent_key,
            "depends_on": self.depends_on,
            "status": self.status.value,
            "result": str(self.result)[:500] if self.result else None,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
        }


@dataclass
class DAGResult:
    """Result of executing an entire DAG workflow."""
    workflow_id: str
    status: str = "completed"   # completed, partial_failure, failed
    total_nodes: int = 0
    completed_nodes: int = 0
    failed_nodes: int = 0
    skipped_nodes: int = 0
    total_duration_ms: float = 0.0
    total_cost_usd: float = 0.0
    node_results: Dict[str, dict] = field(default_factory=dict)
    execution_order: List[List[str]] = field(default_factory=list)  # Layers of parallel execution
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# DAG Workflow Definition
# ---------------------------------------------------------------------------

class DAGWorkflow:
    """Defines a workflow as a Directed Acyclic Graph of tasks.

    Nodes are tasks, edges are dependencies.
    """

    def __init__(self, workflow_id: str, name: str = ""):
        self.workflow_id = workflow_id
        self.name = name or workflow_id
        self._nodes: Dict[str, DAGNode] = {}
        self._adjacency: Dict[str, List[str]] = defaultdict(list)  # node -> dependents

    def add_node(self, node_id: str, task: str, agent_key: str = "",
                 depends_on: Optional[List[str]] = None, **metadata) -> 'DAGWorkflow':
        """Add a task node to the workflow.

        Args:
            node_id: Unique identifier for this node.
            task: Task description for the agent.
            agent_key: Which agent should handle this.
            depends_on: List of node IDs that must complete first.
            **metadata: Additional key-value data.

        Returns:
            self (for chaining)
        """
        deps = depends_on or []
        node = DAGNode(
            node_id=node_id,
            task=task,
            agent_key=agent_key,
            depends_on=deps,
            metadata=metadata,
        )
        self._nodes[node_id] = node

        # Build reverse adjacency (dependency -> dependent)
        for dep in deps:
            self._adjacency[dep].append(node_id)

        return self

    def validate(self) -> List[str]:
        """Validate the DAG structure. Returns list of error messages."""
        errors = []

        # Check all dependencies exist
        for node in self._nodes.values():
            for dep in node.depends_on:
                if dep not in self._nodes:
                    errors.append(f"Node '{node.node_id}' depends on unknown node '{dep}'")

        # Check for cycles using DFS
        if not errors:
            visited = set()
            rec_stack = set()

            def _has_cycle(node_id: str) -> bool:
                visited.add(node_id)
                rec_stack.add(node_id)
                for dependent in self._adjacency.get(node_id, []):
                    if dependent not in visited:
                        if _has_cycle(dependent):
                            return True
                    elif dependent in rec_stack:
                        errors.append(f"Cycle detected involving node '{dependent}'")
                        return True
                rec_stack.discard(node_id)
                return False

            for nid in self._nodes:
                if nid not in visited:
                    _has_cycle(nid)

        return errors

    def topological_layers(self) -> List[List[str]]:
        """Compute execution layers using Kahn's algorithm.

        Returns list of layers, where each layer contains nodes
        that can execute in parallel (all dependencies satisfied).

        Example:
            [[lint, test], [review], [deploy]]
            Layer 0: lint + test run in parallel
            Layer 1: review (after lint + test)
            Layer 2: deploy (after review)
        """
        # Compute in-degrees
        in_degree = {nid: 0 for nid in self._nodes}
        for node in self._nodes.values():
            for dep in node.depends_on:
                if dep in in_degree:  # Guard against missing nodes
                    pass
            # Count how many nodes depend on each node
        for nid, node in self._nodes.items():
            in_degree[nid] = len(node.depends_on)

        # Start with zero-dependency nodes
        layers = []
        remaining = dict(in_degree)

        while remaining:
            # Find all nodes with zero in-degree
            layer = [nid for nid, deg in remaining.items() if deg == 0]
            if not layer:
                # Cycle detected (shouldn't happen after validate())
                logger.error("Cycle detected in DAG during topological sort")
                break

            layers.append(layer)

            # Remove this layer and update in-degrees
            for nid in layer:
                del remaining[nid]
                for dependent in self._adjacency.get(nid, []):
                    if dependent in remaining:
                        remaining[dependent] -= 1

        return layers

    @property
    def nodes(self) -> Dict[str, DAGNode]:
        return self._nodes

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    def to_dict(self) -> dict:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "nodes": {nid: n.to_dict() for nid, n in self._nodes.items()},
            "layers": self.topological_layers(),
        }


# ---------------------------------------------------------------------------
# DAG Executor
# ---------------------------------------------------------------------------

class DAGExecutor:
    """Executes a DAG workflow with parallel task execution.

    Uses asyncio.Semaphore to limit concurrency and topological sorting
    to determine execution order.
    """

    def __init__(self, max_concurrent: int = 3):
        """
        Args:
            max_concurrent: Maximum number of nodes executing in parallel.
        """
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        logger.info(f"DAGExecutor initialized (max_concurrent={max_concurrent})")

    async def execute(self, workflow: DAGWorkflow,
                      run_node_fn: Callable[[DAGNode], Coroutine],
                      on_node_complete: Optional[Callable] = None,
                      fail_fast: bool = False) -> DAGResult:
        """Execute a DAG workflow.

        Args:
            workflow: The DAG to execute.
            run_node_fn: Async function(DAGNode) -> Any that executes a single node.
                        Should return the result and raise on failure.
            on_node_complete: Optional callback(node_id, status, result) for progress updates.
            fail_fast: If True, cancel remaining nodes on first failure.

        Returns:
            DAGResult with all node outcomes.
        """
        # Validate first
        errors = workflow.validate()
        if errors:
            return DAGResult(
                workflow_id=workflow.workflow_id,
                status="failed",
                total_nodes=workflow.node_count,
                node_results={"validation_errors": errors},
            )

        layers = workflow.topological_layers()
        start_time = time.perf_counter()
        failed_nodes: Set[str] = set()

        logger.info(f"Executing DAG '{workflow.workflow_id}' with {workflow.node_count} nodes in {len(layers)} layers")

        for layer_idx, layer in enumerate(layers):
            logger.info(f"  Layer {layer_idx}: {layer}")

            # Skip nodes whose dependencies failed
            nodes_to_run = []
            for nid in layer:
                node = workflow.nodes[nid]
                failed_deps = [d for d in node.depends_on if d in failed_nodes]
                if failed_deps:
                    node.status = NodeStatus.SKIPPED
                    node.error = f"Skipped: upstream failures in {failed_deps}"
                    failed_nodes.add(nid)
                    if on_node_complete:
                        on_node_complete(nid, "skipped", None)
                else:
                    nodes_to_run.append(node)

            if not nodes_to_run:
                continue

            # Execute all nodes in this layer concurrently
            tasks = [
                self._execute_node(node, run_node_fn, on_node_complete)
                for node in nodes_to_run
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            for node, result in zip(nodes_to_run, results):
                if isinstance(result, Exception):
                    node.status = NodeStatus.FAILED
                    node.error = str(result)
                    failed_nodes.add(node.node_id)
                    if fail_fast:
                        logger.warning(f"Fail-fast: stopping DAG after node '{node.node_id}' failed")
                        # Mark remaining as skipped
                        for remaining_layer in layers[layer_idx + 1:]:
                            for nid in remaining_layer:
                                workflow.nodes[nid].status = NodeStatus.SKIPPED
                                workflow.nodes[nid].error = "Skipped: fail-fast triggered"
                        break

            if fail_fast and failed_nodes:
                break

        # Build result
        total_duration = round((time.perf_counter() - start_time) * 1000, 2)
        completed = sum(1 for n in workflow.nodes.values() if n.status == NodeStatus.COMPLETED)
        failed = sum(1 for n in workflow.nodes.values() if n.status == NodeStatus.FAILED)
        skipped = sum(1 for n in workflow.nodes.values() if n.status == NodeStatus.SKIPPED)
        total_cost = sum(n.cost_usd for n in workflow.nodes.values())

        if failed == 0:
            status = "completed"
        elif completed > 0:
            status = "partial_failure"
        else:
            status = "failed"

        return DAGResult(
            workflow_id=workflow.workflow_id,
            status=status,
            total_nodes=workflow.node_count,
            completed_nodes=completed,
            failed_nodes=failed,
            skipped_nodes=skipped,
            total_duration_ms=total_duration,
            total_cost_usd=total_cost,
            node_results={nid: n.to_dict() for nid, n in workflow.nodes.items()},
            execution_order=layers,
        )

    async def _execute_node(self, node: DAGNode,
                            run_node_fn: Callable,
                            on_node_complete: Optional[Callable] = None):
        """Execute a single node with semaphore-based concurrency control."""
        async with self._semaphore:
            node.status = NodeStatus.RUNNING
            node.start_time = time.perf_counter()

            try:
                result = await run_node_fn(node)
                node.status = NodeStatus.COMPLETED
                node.result = result
                node.end_time = time.perf_counter()
                node.duration_ms = round((node.end_time - node.start_time) * 1000, 2)

                logger.info(f"  Node '{node.node_id}' completed in {node.duration_ms}ms")
                if on_node_complete:
                    on_node_complete(node.node_id, "completed", result)

                return result

            except Exception as e:
                node.status = NodeStatus.FAILED
                node.error = str(e)
                node.end_time = time.perf_counter()
                node.duration_ms = round((node.end_time - node.start_time) * 1000, 2)

                logger.error(f"  Node '{node.node_id}' failed: {e}")
                if on_node_complete:
                    on_node_complete(node.node_id, "failed", str(e))

                raise


# ---------------------------------------------------------------------------
# Workflow Builder Helpers
# ---------------------------------------------------------------------------

def workflow_from_plan(workflow_id: str, plan_steps: List[dict]) -> DAGWorkflow:
    """Build a DAG from a plan (list of steps with optional dependencies).

    Each step dict should have:
        - id: str
        - task: str
        - agent: str (optional)
        - depends_on: List[str] (optional)

    If no dependencies are specified, steps are assumed sequential.
    """
    dag = DAGWorkflow(workflow_id)

    for i, step in enumerate(plan_steps):
        step_id = step.get("id", f"step_{i}")
        deps = step.get("depends_on", [])

        # Default: sequential if no deps specified
        if not deps and i > 0 and "parallel" not in step.get("mode", ""):
            deps = [plan_steps[i - 1].get("id", f"step_{i - 1}")]

        dag.add_node(
            node_id=step_id,
            task=step.get("task", step.get("description", "")),
            agent_key=step.get("agent", step.get("agent_key", "")),
            depends_on=deps,
        )

    return dag


def parallel_workflow(workflow_id: str, tasks: List[dict],
                      final_step: Optional[dict] = None) -> DAGWorkflow:
    """Build a workflow where all tasks run in parallel, with optional final step.

    Useful for: "run lint, test, and type-check, then deploy if all pass"
    """
    dag = DAGWorkflow(workflow_id)
    task_ids = []

    for i, task in enumerate(tasks):
        task_id = task.get("id", f"parallel_{i}")
        task_ids.append(task_id)
        dag.add_node(
            node_id=task_id,
            task=task.get("task", ""),
            agent_key=task.get("agent", ""),
            depends_on=[],  # All parallel
        )

    if final_step:
        dag.add_node(
            node_id=final_step.get("id", "final"),
            task=final_step.get("task", ""),
            agent_key=final_step.get("agent", ""),
            depends_on=task_ids,  # Depends on all parallel tasks
        )

    return dag
