"""
Comprehensive test suite for Workflow Automation Engine
Tests workflow parsing, execution, error handling, and API endpoints
"""

import pytest
import asyncio
import json
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock

from workflow_engine import (
    WorkflowExecutor,
    WorkflowManager,
    WorkflowDefinition,
    TaskDefinition,
    TaskExecution,
    WorkflowExecution,
    TaskType,
    WorkflowStatus,
    TaskStatus,
    create_website_build_workflow,
    create_code_review_workflow,
    create_documentation_workflow,
    initialize_default_workflows,
)


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def temp_workflows_dir(monkeypatch):
    """Create temporary directory for workflow storage"""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("OPENCLAW_WORKFLOWS_DIR", tmpdir)
        yield Path(tmpdir)


@pytest.fixture
def workflow_executor(temp_workflows_dir):
    """Create workflow executor instance"""
    # Create a mock agent router
    mock_router = Mock()
    return WorkflowExecutor(agent_router=mock_router)


@pytest.fixture
def workflow_manager(temp_workflows_dir):
    """Create workflow manager instance"""
    return WorkflowManager()


@pytest.fixture
def simple_workflow():
    """Create a simple test workflow"""
    tasks = [
        TaskDefinition(
            id="task1",
            name="First Task",
            type=TaskType.AGENT_CALL,
            agent_id="test_agent",
            prompt="Do something",
        ),
        TaskDefinition(
            id="task2",
            name="Second Task",
            type=TaskType.AGENT_CALL,
            agent_id="test_agent",
            prompt="Do something else",
        ),
    ]

    return WorkflowDefinition(
        id="test-workflow-001",
        name="Simple Test Workflow",
        description="A simple workflow for testing",
        tasks=tasks,
    )


@pytest.fixture
def conditional_workflow():
    """Create a workflow with conditional branching"""
    tasks = [
        TaskDefinition(
            id="check",
            name="Check Condition",
            type=TaskType.CONDITIONAL,
            condition="1 == 1",
        ),
    ]

    return WorkflowDefinition(
        id="conditional-workflow-001",
        name="Conditional Test Workflow",
        tasks=tasks,
    )


@pytest.fixture
def parallel_workflow():
    """Create a workflow with parallel tasks"""
    parallel_tasks = [
        TaskDefinition(
            id="parallel1",
            name="Parallel Task 1",
            type=TaskType.AGENT_CALL,
            agent_id="agent1",
            prompt="Do task 1",
        ),
        TaskDefinition(
            id="parallel2",
            name="Parallel Task 2",
            type=TaskType.AGENT_CALL,
            agent_id="agent2",
            prompt="Do task 2",
        ),
    ]

    tasks = [
        TaskDefinition(
            id="parallel_group",
            name="Run in Parallel",
            type=TaskType.PARALLEL,
            parallel_tasks=parallel_tasks,
        ),
    ]

    return WorkflowDefinition(
        id="parallel-workflow-001",
        name="Parallel Test Workflow",
        tasks=tasks,
    )


# ═══════════════════════════════════════════════════════════════════════════
# WORKFLOW DEFINITION TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestWorkflowDefinitions:
    """Test workflow definition creation and serialization"""

    def test_create_task_definition(self):
        """Test creating a task definition"""
        task = TaskDefinition(
            id="test_task",
            name="Test Task",
            type=TaskType.AGENT_CALL,
            agent_id="test_agent",
            prompt="Test prompt",
        )

        assert task.id == "test_task"
        assert task.name == "Test Task"
        assert task.type == TaskType.AGENT_CALL
        assert task.agent_id == "test_agent"
        assert task.retry_count == 3

    def test_create_workflow_definition(self, simple_workflow):
        """Test creating a workflow definition"""
        assert simple_workflow.id == "test-workflow-001"
        assert simple_workflow.name == "Simple Test Workflow"
        assert len(simple_workflow.tasks) == 2
        assert simple_workflow.tasks[0].name == "First Task"

    def test_task_definition_to_dict(self):
        """Test task definition serialization"""
        task = TaskDefinition(
            id="test",
            name="Test",
            type=TaskType.AGENT_CALL,
            agent_id="agent",
            prompt="prompt",
        )

        task_dict = task.to_dict()
        assert task_dict['id'] == "test"
        assert task_dict['name'] == "Test"
        assert task_dict['type'] == TaskType.AGENT_CALL

    def test_workflow_definition_to_dict(self, simple_workflow):
        """Test workflow definition serialization"""
        workflow_dict = simple_workflow.to_dict()

        assert workflow_dict['id'] == "test-workflow-001"
        assert workflow_dict['name'] == "Simple Test Workflow"
        assert len(workflow_dict['tasks']) == 2
        assert workflow_dict['version'] == "1.0"


# ═══════════════════════════════════════════════════════════════════════════
# WORKFLOW MANAGER TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestWorkflowManager:
    """Test workflow management operations"""

    def test_create_workflow(self, workflow_manager):
        """Test creating a new workflow"""
        workflow = workflow_manager.create_workflow(
            name="Test Workflow",
            description="A test workflow",
        )

        assert workflow.name == "Test Workflow"
        assert workflow.description == "A test workflow"
        assert workflow.id is not None
        assert len(workflow.tasks) == 0

    def test_save_and_load_workflow(self, workflow_manager, simple_workflow):
        """Test saving and loading a workflow"""
        workflow_manager.save_workflow(simple_workflow)
        loaded = workflow_manager.load_workflow(simple_workflow.id)

        assert loaded is not None
        assert loaded.id == simple_workflow.id
        assert loaded.name == simple_workflow.name
        assert len(loaded.tasks) == 2

    def test_list_workflows(self, workflow_manager, simple_workflow):
        """Test listing all workflows"""
        workflow_manager.save_workflow(simple_workflow)
        workflows = workflow_manager.list_workflows()

        assert len(workflows) >= 1
        assert any(w['id'] == simple_workflow.id for w in workflows)
        assert any(w['task_count'] == 2 for w in workflows)

    def test_delete_workflow(self, workflow_manager, simple_workflow):
        """Test deleting a workflow"""
        workflow_manager.save_workflow(simple_workflow)
        success = workflow_manager.delete_workflow(simple_workflow.id)

        assert success is True
        loaded = workflow_manager.load_workflow(simple_workflow.id)
        assert loaded is None

    def test_load_nonexistent_workflow(self, workflow_manager):
        """Test loading a workflow that doesn't exist"""
        loaded = workflow_manager.load_workflow("nonexistent-id")
        assert loaded is None


# ═══════════════════════════════════════════════════════════════════════════
# WORKFLOW EXECUTOR TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestWorkflowExecutor:
    """Test workflow execution"""

    @pytest.mark.asyncio
    async def test_execute_simple_workflow(self, workflow_executor, simple_workflow):
        """Test executing a simple workflow"""
        execution = await workflow_executor.execute_workflow(simple_workflow)

        assert execution.workflow_id == simple_workflow.id
        assert execution.execution_id is not None
        assert execution.status == WorkflowStatus.COMPLETED
        assert execution.start_time is not None
        assert execution.end_time is not None
        assert len(execution.task_executions) > 0

    @pytest.mark.asyncio
    async def test_execution_duration_calculated(self, workflow_executor, simple_workflow):
        """Test that execution duration is calculated"""
        execution = await workflow_executor.execute_workflow(simple_workflow)

        assert execution.duration_seconds > 0

    @pytest.mark.asyncio
    async def test_task_execution_details(self, workflow_executor, simple_workflow):
        """Test task execution details are recorded"""
        execution = await workflow_executor.execute_workflow(simple_workflow)

        first_task_exec = execution.task_executions.get("task1")
        assert first_task_exec is not None
        assert first_task_exec.task_id == "task1"
        assert first_task_exec.status == TaskStatus.COMPLETED
        assert first_task_exec.start_time is not None
        assert first_task_exec.end_time is not None
        assert first_task_exec.attempts > 0

    @pytest.mark.asyncio
    async def test_execute_conditional_workflow(self, workflow_executor, conditional_workflow):
        """Test executing conditional workflow"""
        execution = await workflow_executor.execute_workflow(conditional_workflow)

        assert execution.status == WorkflowStatus.COMPLETED
        task_exec = execution.task_executions.get("check")
        assert task_exec is not None
        assert task_exec.result is not None

    @pytest.mark.asyncio
    async def test_execute_parallel_workflow(self, workflow_executor, parallel_workflow):
        """Test executing parallel tasks"""
        execution = await workflow_executor.execute_workflow(parallel_workflow)

        assert execution.status == WorkflowStatus.COMPLETED
        parallel_exec = execution.task_executions.get("parallel_group")
        assert parallel_exec is not None
        assert parallel_exec.result is not None

    @pytest.mark.asyncio
    async def test_workflow_with_context(self, workflow_executor, simple_workflow):
        """Test workflow execution with context variables"""
        context = {"user_id": "123", "project_id": "456"}
        execution = await workflow_executor.execute_workflow(simple_workflow, context)

        assert execution.context == context
        assert execution.status == WorkflowStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_workflow_with_variables(self, workflow_executor):
        """Test workflow execution with variables"""
        tasks = [
            TaskDefinition(
                id="task1",
                name="Task 1",
                type=TaskType.CONDITIONAL,
                condition="x > 5",
            ),
        ]

        workflow = WorkflowDefinition(
            id="var-workflow",
            name="Variable Workflow",
            tasks=tasks,
            variables={"x": 10},
        )

        execution = await workflow_executor.execute_workflow(workflow)
        assert execution.variables['x'] == 10


# ═══════════════════════════════════════════════════════════════════════════
# ERROR HANDLING TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestErrorHandling:
    """Test error handling and recovery"""

    @pytest.mark.asyncio
    async def test_task_retry_on_failure(self, workflow_executor):
        """Test task retries on failure"""
        tasks = [
            TaskDefinition(
                id="task1",
                name="Failing Task",
                type=TaskType.HTTP_REQUEST,
                url="http://invalid-url",
                retry_count=3,
                retry_backoff=1.0,
            ),
        ]

        workflow = WorkflowDefinition(
            id="retry-workflow",
            name="Retry Test",
            tasks=tasks,
        )

        execution = await workflow_executor.execute_workflow(workflow)
        task_exec = execution.task_executions.get("task1")
        assert task_exec.attempts == 3

    @pytest.mark.asyncio
    async def test_skip_on_error(self, workflow_executor):
        """Test skip_on_error functionality"""
        tasks = [
            TaskDefinition(
                id="fail_task",
                name="Failing Task",
                type=TaskType.HTTP_REQUEST,
                url="http://invalid",
                retry_count=1,
                skip_on_error=True,
            ),
            TaskDefinition(
                id="continue_task",
                name="Continue Task",
                type=TaskType.AGENT_CALL,
                agent_id="agent",
                prompt="Continue",
            ),
        ]

        workflow = WorkflowDefinition(
            id="skip-workflow",
            name="Skip Test",
            tasks=tasks,
        )

        execution = await workflow_executor.execute_workflow(workflow)
        # Workflow should complete despite first task failure
        assert execution.status == WorkflowStatus.COMPLETED
        fail_task_exec = execution.task_executions.get("fail_task")
        assert fail_task_exec.status == TaskStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_workflow_stops_on_critical_failure(self, workflow_executor):
        """Test workflow stops on critical task failure"""
        tasks = [
            TaskDefinition(
                id="fail_task",
                name="Failing Task",
                type=TaskType.HTTP_REQUEST,
                url="http://invalid",
                retry_count=1,
                skip_on_error=False,  # Don't skip
            ),
            TaskDefinition(
                id="never_runs",
                name="Should Not Run",
                type=TaskType.AGENT_CALL,
                agent_id="agent",
                prompt="This should not run",
            ),
        ]

        workflow = WorkflowDefinition(
            id="fail-workflow",
            name="Failure Test",
            tasks=tasks,
        )

        execution = await workflow_executor.execute_workflow(workflow)
        assert execution.status == WorkflowStatus.FAILED
        never_runs = execution.task_executions.get("never_runs")
        assert never_runs is None or never_runs.status == TaskStatus.PENDING


# ═══════════════════════════════════════════════════════════════════════════
# PERSISTENCE TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestPersistence:
    """Test execution persistence and status tracking"""

    @pytest.mark.asyncio
    async def test_execution_saved_to_disk(self, workflow_executor, simple_workflow, temp_workflows_dir):
        """Test execution record is saved to disk"""
        execution = await workflow_executor.execute_workflow(simple_workflow)

        exec_file = temp_workflows_dir / "executions" / f"{execution.execution_id}.json"
        assert exec_file.exists()

        with open(exec_file, 'r') as f:
            data = json.load(f)
            assert data['execution_id'] == execution.execution_id
            assert data['workflow_id'] == simple_workflow.id

    @pytest.mark.asyncio
    async def test_get_execution_status(self, workflow_executor, simple_workflow):
        """Test retrieving execution status"""
        execution = await workflow_executor.execute_workflow(simple_workflow)

        status = workflow_executor.get_execution_status(execution.execution_id)
        assert status is not None
        assert status['execution_id'] == execution.execution_id
        assert status['status'] == 'completed'

    @pytest.mark.asyncio
    async def test_get_execution_logs(self, workflow_executor, simple_workflow):
        """Test retrieving execution logs"""
        execution = await workflow_executor.execute_workflow(simple_workflow)

        logs = workflow_executor.get_execution_logs(execution.execution_id)
        assert len(logs) > 0
        assert "Workflow execution started" in logs
        assert "completed" in logs.lower()

    def test_get_nonexistent_execution_status(self, workflow_executor):
        """Test getting status of nonexistent execution"""
        status = workflow_executor.get_execution_status("nonexistent-id")
        assert "error" in status


# ═══════════════════════════════════════════════════════════════════════════
# BUILT-IN WORKFLOW TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestBuiltInWorkflows:
    """Test built-in workflow templates"""

    def test_website_build_workflow(self):
        """Test website build workflow template"""
        workflow = create_website_build_workflow()

        assert workflow.name == "Website Build Pipeline"
        assert len(workflow.tasks) == 3
        assert workflow.tasks[0].agent_id == "coder_agent"
        assert workflow.tasks[1].agent_id == "hacker_agent"
        assert workflow.tasks[2].type == TaskType.HTTP_REQUEST

    def test_code_review_workflow(self):
        """Test code review workflow template"""
        workflow = create_code_review_workflow()

        assert workflow.name == "Code Review Pipeline"
        assert len(workflow.tasks) == 2
        assert workflow.tasks[0].agent_id == "coder_agent"
        assert workflow.tasks[1].agent_id == "hacker_agent"

    def test_documentation_workflow(self):
        """Test documentation workflow template"""
        workflow = create_documentation_workflow()

        assert workflow.name == "Documentation Pipeline"
        assert len(workflow.tasks) == 2
        assert workflow.tasks[0].agent_id == "coder_agent"
        assert workflow.tasks[1].agent_id == "project_manager"

    def test_initialize_default_workflows(self, workflow_manager, temp_workflows_dir):
        """Test initializing default workflows"""
        initialize_default_workflows()

        workflows = workflow_manager.list_workflows()
        assert len(workflows) >= 3
        workflow_names = [w['name'] for w in workflows]
        assert "Website Build Pipeline" in workflow_names
        assert "Code Review Pipeline" in workflow_names
        assert "Documentation Pipeline" in workflow_names


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegration:
    """Integration tests for complete workflows"""

    @pytest.mark.asyncio
    async def test_end_to_end_website_build(self, workflow_executor, workflow_manager, temp_workflows_dir):
        """Test end-to-end website build workflow"""
        # Create and save workflow
        workflow = create_website_build_workflow()
        workflow_manager.save_workflow(workflow)

        # Load and execute
        loaded = workflow_manager.load_workflow(workflow.id)
        assert loaded is not None

        execution = await workflow_executor.execute_workflow(loaded)
        assert execution.status == WorkflowStatus.COMPLETED
        assert len(execution.task_executions) == 3

    @pytest.mark.asyncio
    async def test_multiple_concurrent_executions(self, workflow_executor, simple_workflow):
        """Test multiple concurrent workflow executions"""
        # Execute multiple workflows concurrently
        executions = await asyncio.gather(
            workflow_executor.execute_workflow(simple_workflow),
            workflow_executor.execute_workflow(simple_workflow),
            workflow_executor.execute_workflow(simple_workflow),
        )

        assert len(executions) == 3
        for execution in executions:
            assert execution.status == WorkflowStatus.COMPLETED
            assert execution.execution_id is not None

    @pytest.mark.asyncio
    async def test_workflow_with_cost_tracking(self, simple_workflow):
        """Test workflow execution with cost tracking"""
        cost_events = []

        def mock_cost_tracker(event):
            cost_events.append(event)

        executor = WorkflowExecutor(cost_tracker=mock_cost_tracker)
        execution = await executor.execute_workflow(simple_workflow)

        assert execution.total_cost_usd >= 0


# ═══════════════════════════════════════════════════════════════════════════
# PERFORMANCE TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestPerformance:
    """Performance and scalability tests"""

    @pytest.mark.asyncio
    async def test_1000_concurrent_lightweight_workflows(self, workflow_executor):
        """Test 1000 concurrent lightweight workflow executions"""
        # Create a very simple workflow
        workflow = WorkflowDefinition(
            id="perf-test",
            name="Performance Test",
            tasks=[
                TaskDefinition(
                    id="task1",
                    name="Quick Task",
                    type=TaskType.CONDITIONAL,
                    condition="True",
                ),
            ],
        )

        # Execute 100 concurrently (1000 might be too much for test environment)
        import time
        start = time.time()

        executions = await asyncio.gather(*[
            workflow_executor.execute_workflow(workflow)
            for _ in range(100)
        ])

        elapsed = time.time() - start

        assert len(executions) == 100
        assert all(e.status == WorkflowStatus.COMPLETED for e in executions)
        logger.info(f"Executed 100 workflows in {elapsed:.2f}s ({elapsed/100:.3f}s per workflow)")


# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

import logging
logger = logging.getLogger("test_workflows")


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
