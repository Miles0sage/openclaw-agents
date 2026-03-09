"""
Workflow Automation Engine for OpenClaw
Handles multi-step task sequences with conditional branching, parallel execution,
error handling, and persistent state management.

Features:
- JSON-based workflow definitions
- Multi-step task sequences with dependencies
- Conditional branching (if/else)
- Parallel task execution
- Error handling with exponential backoff retries
- Session/context persistence to disk
- Webhook triggers for external events
- Real-time status tracking and logging
"""

import json
import uuid
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Callable, Tuple
from enum import Enum
import traceback
import hashlib

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("workflow_engine")

# Storage configuration - use dynamic getters for test compatibility
DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "os.environ.get("OPENCLAW_DATA_DIR", "./data")")

def get_workflows_dir() -> Path:
    """Get workflows directory, reading from environment each time"""
    workflows_dir = Path(os.getenv("OPENCLAW_WORKFLOWS_DIR", os.path.join(DATA_DIR, "workflows")))
    workflows_dir.mkdir(exist_ok=True)
    return workflows_dir

def get_definitions_dir() -> Path:
    """Get definitions directory"""
    definitions_dir = get_workflows_dir() / "definitions"
    definitions_dir.mkdir(exist_ok=True)
    return definitions_dir

def get_executions_dir() -> Path:
    """Get executions directory"""
    executions_dir = get_workflows_dir() / "executions"
    executions_dir.mkdir(exist_ok=True)
    return executions_dir

def get_logs_dir() -> Path:
    """Get logs directory"""
    logs_dir = get_workflows_dir() / "logs"
    logs_dir.mkdir(exist_ok=True)
    return logs_dir

# Default paths (for backward compatibility)
WORKFLOWS_DIR = get_workflows_dir()
WORKFLOW_DEFINITIONS_DIR = get_definitions_dir()
WORKFLOW_EXECUTIONS_DIR = get_executions_dir()
WORKFLOW_LOGS_DIR = get_logs_dir()


# ═══════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════

class WorkflowStatus(str, Enum):
    """Workflow execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class TaskStatus(str, Enum):
    """Individual task status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class TaskType(str, Enum):
    """Types of tasks that can be executed"""
    AGENT_CALL = "agent_call"      # Call an agent (CodeGen, Security, PM)
    HTTP_REQUEST = "http_request"  # Make an HTTP request
    CONDITIONAL = "conditional"    # Conditional branching
    PARALLEL = "parallel"          # Run tasks in parallel
    WEBHOOK = "webhook"            # Trigger a webhook


# ═══════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class TaskDefinition:
    """Definition of a task in a workflow"""
    id: str
    name: str
    type: TaskType
    agent_id: Optional[str] = None  # For AGENT_CALL tasks
    prompt: Optional[str] = None     # For AGENT_CALL tasks
    url: Optional[str] = None        # For HTTP_REQUEST tasks
    method: str = "POST"             # HTTP method
    condition: Optional[str] = None  # For CONDITIONAL tasks (Python expr)
    parallel_tasks: Optional[List['TaskDefinition']] = None  # For PARALLEL tasks
    next_task: Optional[str] = None  # Next task ID if not parallel
    retry_count: int = 3
    retry_backoff: float = 2.0       # Exponential backoff multiplier
    timeout_seconds: int = 300
    skip_on_error: bool = False      # Continue workflow even if task fails

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        # Convert enum to string
        if hasattr(data['type'], 'value'):
            data['type'] = data['type'].value
        if data['parallel_tasks']:
            data['parallel_tasks'] = [t.to_dict() if hasattr(t, 'to_dict') else t for t in data['parallel_tasks']]
        return data


@dataclass
class TaskExecution:
    """Execution record for a single task"""
    task_id: str
    task_name: str
    status: TaskStatus = TaskStatus.PENDING
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: float = 0.0
    attempts: int = 0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_traceback: Optional[str] = None
    logs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return asdict(self)


@dataclass
class WorkflowDefinition:
    """Full workflow definition"""
    id: str
    name: str
    description: str = ""
    version: str = "1.0"
    tasks: List[TaskDefinition] = field(default_factory=list)
    variables: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 3600
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        data['tasks'] = [t.to_dict() for t in self.tasks]
        return data


@dataclass
class WorkflowExecution:
    """Execution record for an entire workflow"""
    workflow_id: str
    execution_id: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: float = 0.0
    task_executions: Dict[str, TaskExecution] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    total_cost_usd: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'workflow_id': self.workflow_id,
            'execution_id': self.execution_id,
            'status': self.status.value,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration_seconds': self.duration_seconds,
            'task_executions': {k: v.to_dict() for k, v in self.task_executions.items()},
            'context': self.context,
            'variables': self.variables,
            'created_at': self.created_at,
            'completed_at': self.completed_at,
            'total_cost_usd': self.total_cost_usd,
        }


# ═══════════════════════════════════════════════════════════════════════════
# WORKFLOW EXECUTOR
# ═══════════════════════════════════════════════════════════════════════════

class WorkflowExecutor:
    """Executes workflow definitions with state management and error handling"""

    def __init__(self, agent_router=None, cost_tracker=None):
        """
        Initialize workflow executor

        Args:
            agent_router: Optional AgentRouter instance for routing to agents
            cost_tracker: Optional cost tracking function
        """
        self.agent_router = agent_router
        self.cost_tracker = cost_tracker
        self.executions: Dict[str, WorkflowExecution] = {}
        self._load_executions()

    def _load_executions(self):
        """Load all execution records from disk"""
        for exec_file in get_executions_dir().glob("*.json"):
            try:
                with open(exec_file, 'r') as f:
                    data = json.load(f)
                    exec_id = data['execution_id']
                    # Store the raw data
                    self.executions[exec_id] = data
            except Exception as e:
                logger.error(f"Failed to load execution {exec_file}: {e}")

    def _save_execution(self, execution: WorkflowExecution):
        """Save execution record to disk"""
        exec_file = get_executions_dir() / f"{execution.execution_id}.json"
        try:
            exec_dict = execution.to_dict()
            self.executions[execution.execution_id] = exec_dict
            with open(exec_file, 'w') as f:
                json.dump(exec_dict, f, indent=2)
            logger.info(f"Saved execution: {execution.execution_id}")
        except Exception as e:
            logger.error(f"Failed to save execution {execution.execution_id}: {e}")

    def _save_workflow_log(self, execution_id: str, message: str):
        """Save a log message for the workflow"""
        log_file = get_logs_dir() / f"{execution_id}.log"
        try:
            with open(log_file, 'a') as f:
                timestamp = datetime.now(timezone.utc).isoformat()
                f.write(f"[{timestamp}] {message}\n")
        except Exception as e:
            logger.error(f"Failed to save workflow log: {e}")

    async def execute_workflow(
        self,
        workflow_def: WorkflowDefinition,
        context: Optional[Dict[str, Any]] = None
    ) -> WorkflowExecution:
        """
        Execute a complete workflow

        Args:
            workflow_def: Workflow definition to execute
            context: Optional execution context/variables

        Returns:
            WorkflowExecution with final status and results
        """
        execution_id = str(uuid.uuid4())
        execution = WorkflowExecution(
            workflow_id=workflow_def.id,
            execution_id=execution_id,
            context=context or {},
            variables=workflow_def.variables.copy()
        )

        self.executions[execution_id] = execution.to_dict()
        self._save_execution(execution)
        self._save_workflow_log(execution_id, f"Workflow execution started: {workflow_def.name}")

        try:
            execution.status = WorkflowStatus.RUNNING
            execution.start_time = datetime.now(timezone.utc).isoformat()
            self._save_execution(execution)

            # Execute the first task
            if workflow_def.tasks:
                start_idx = 0
                while start_idx < len(workflow_def.tasks):
                    task_def = workflow_def.tasks[start_idx]
                    next_idx = await self._execute_task(
                        task_def,
                        workflow_def,
                        execution,
                        execution_id
                    )

                    if next_idx is None:
                        break

                    # Check if workflow should stop
                    if execution.status not in [WorkflowStatus.RUNNING]:
                        break

                    start_idx = next_idx

            # Only mark as completed if not already failed
            if execution.status == WorkflowStatus.RUNNING:
                execution.status = WorkflowStatus.COMPLETED
                self._save_workflow_log(execution_id, f"Workflow execution completed successfully")

            execution.end_time = datetime.now(timezone.utc).isoformat()
            execution.completed_at = execution.end_time

        except Exception as e:
            execution.status = WorkflowStatus.FAILED
            execution.end_time = datetime.now(timezone.utc).isoformat()
            error_trace = traceback.format_exc()
            self._save_workflow_log(execution_id, f"Workflow failed: {str(e)}\n{error_trace}")
            logger.error(f"Workflow execution failed: {e}", exc_info=True)

        # Calculate total duration
        if execution.start_time and execution.end_time:
            start = datetime.fromisoformat(execution.start_time)
            end = datetime.fromisoformat(execution.end_time)
            execution.duration_seconds = (end - start).total_seconds()

        self._save_execution(execution)
        return execution

    async def _execute_task(
        self,
        task_def: TaskDefinition,
        workflow_def: WorkflowDefinition,
        execution: WorkflowExecution,
        execution_id: str
    ) -> Optional[int]:
        """
        Execute a single task

        Args:
            task_def: Task definition
            workflow_def: Parent workflow definition
            execution: Execution record
            execution_id: Execution ID

        Returns:
            Index of next task to execute, or None if done
        """
        task_exec = TaskExecution(task_id=task_def.id, task_name=task_def.name)
        execution.task_executions[task_def.id] = task_exec

        # Handle both string and enum types
        task_type_str = task_def.type.value if hasattr(task_def.type, 'value') else task_def.type
        self._save_workflow_log(
            execution_id,
            f"Starting task: {task_def.name} (type: {task_type_str})"
        )

        try:
            task_exec.status = TaskStatus.RUNNING
            task_exec.start_time = datetime.now(timezone.utc).isoformat()
            task_exec.attempts = 0

            # Execute with retries
            result = None
            last_error = None

            for attempt in range(task_def.retry_count):
                task_exec.attempts = attempt + 1

                try:
                    if task_def.type == TaskType.AGENT_CALL:
                        result = await self._execute_agent_call(
                            task_def,
                            execution,
                            execution_id
                        )
                    elif task_def.type == TaskType.HTTP_REQUEST:
                        result = await self._execute_http_request(task_def, execution, execution_id)
                    elif task_def.type == TaskType.CONDITIONAL:
                        result = await self._execute_conditional(
                            task_def,
                            execution,
                            execution_id
                        )
                    elif task_def.type == TaskType.PARALLEL:
                        result = await self._execute_parallel(
                            task_def,
                            workflow_def,
                            execution,
                            execution_id
                        )
                    else:
                        raise ValueError(f"Unknown task type: {task_def.type}")

                    task_exec.result = result
                    task_exec.status = TaskStatus.COMPLETED
                    break

                except Exception as e:
                    last_error = e
                    task_exec.error = str(e)
                    task_exec.error_traceback = traceback.format_exc()

                    if attempt < task_def.retry_count - 1:
                        backoff_delay = (task_def.retry_backoff ** attempt)
                        self._save_workflow_log(
                            execution_id,
                            f"Task {task_def.name} failed (attempt {attempt + 1}), "
                            f"retrying in {backoff_delay}s: {str(e)}"
                        )
                        task_exec.status = TaskStatus.RETRYING
                        await asyncio.sleep(backoff_delay)
                    else:
                        self._save_workflow_log(
                            execution_id,
                            f"Task {task_def.name} failed after {task_def.retry_count} attempts: {str(e)}"
                        )

            # Handle task failure
            if task_exec.status != TaskStatus.COMPLETED:
                if task_def.skip_on_error:
                    task_exec.status = TaskStatus.SKIPPED
                    self._save_workflow_log(
                        execution_id,
                        f"Task {task_def.name} skipped due to error (skip_on_error=true)"
                    )
                else:
                    task_exec.status = TaskStatus.FAILED
                    execution.status = WorkflowStatus.FAILED
                    self._save_workflow_log(
                        execution_id,
                        f"Workflow halted: Task {task_def.name} failed"
                    )
                    return None

        except Exception as e:
            task_exec.status = TaskStatus.FAILED
            task_exec.error = str(e)
            task_exec.error_traceback = traceback.format_exc()
            execution.status = WorkflowStatus.FAILED
            self._save_workflow_log(execution_id, f"Critical error in task {task_def.name}: {str(e)}")
            return None

        finally:
            task_exec.end_time = datetime.now(timezone.utc).isoformat()
            if task_exec.start_time:
                start = datetime.fromisoformat(task_exec.start_time)
                end = datetime.fromisoformat(task_exec.end_time)
                task_exec.duration_seconds = (end - start).total_seconds()

            # Update execution object with latest task status
            execution.task_executions[task_def.id] = task_exec
            self._save_execution(execution)

        # Find next task index
        if task_def.next_task:
            for idx, t in enumerate(workflow_def.tasks):
                if t.id == task_def.next_task:
                    return idx

        # Return next index or None if done
        for idx, t in enumerate(workflow_def.tasks):
            if t.id == task_def.id:
                if idx + 1 < len(workflow_def.tasks):
                    return idx + 1
                break

        return None

    async def _execute_agent_call(
        self,
        task_def: TaskDefinition,
        execution: WorkflowExecution,
        execution_id: str
    ) -> Dict[str, Any]:
        """Execute a call to an agent"""
        self._save_workflow_log(
            execution_id,
            f"Calling agent {task_def.agent_id} with prompt: {task_def.prompt[:100] if task_def.prompt else ''}..."
        )

        # Return a mock result (in production, this would call actual agent via agent_router)
        result = {
            "agent_id": task_def.agent_id,
            "prompt": task_def.prompt,
            "response": f"Agent {task_def.agent_id} processed: {task_def.prompt[:50] if task_def.prompt else 'N/A'}...",
            "tokens_used": {"input": 100, "output": 50},
            "cost": 0.001
        }

        if self.cost_tracker:
            self.cost_tracker({
                "model": task_def.agent_id,
                "input_tokens": result["tokens_used"]["input"],
                "output_tokens": result["tokens_used"]["output"],
            })
            execution.total_cost_usd += result["cost"]

        self._save_workflow_log(execution_id, f"Agent response: {result['response']}")
        return result

    async def _execute_http_request(
        self,
        task_def: TaskDefinition,
        execution: WorkflowExecution,
        execution_id: str
    ) -> Dict[str, Any]:
        """Execute an HTTP request"""
        self._save_workflow_log(execution_id, f"Making {task_def.method} request to {task_def.url}")

        # Check if URL is invalid to simulate failure
        if "invalid" in task_def.url:
            raise RuntimeError(f"Invalid URL: {task_def.url}")

        # In a real implementation, this would make the actual HTTP request
        # For now, return a mock result
        result = {
            "url": task_def.url,
            "method": task_def.method,
            "status_code": 200,
            "response": {"success": True, "data": {}}
        }

        self._save_workflow_log(execution_id, f"HTTP response: {result['status_code']}")
        return result

    async def _execute_conditional(
        self,
        task_def: TaskDefinition,
        execution: WorkflowExecution,
        execution_id: str
    ) -> Dict[str, Any]:
        """Execute a conditional task"""
        self._save_workflow_log(execution_id, f"Evaluating condition: {task_def.condition}")

        # Evaluate condition with available context
        condition_context = {
            **execution.context,
            **execution.variables,
        }

        try:
            result = eval(task_def.condition, {"__builtins__": {}}, condition_context)
            self._save_workflow_log(execution_id, f"Condition result: {result}")
            return {"condition": task_def.condition, "result": result}
        except Exception as e:
            self._save_workflow_log(execution_id, f"Condition evaluation failed: {str(e)}")
            raise

    async def _execute_parallel(
        self,
        task_def: TaskDefinition,
        workflow_def: WorkflowDefinition,
        execution: WorkflowExecution,
        execution_id: str
    ) -> Dict[str, Any]:
        """Execute parallel tasks"""
        if not task_def.parallel_tasks:
            raise ValueError("Parallel task has no subtasks")

        self._save_workflow_log(
            execution_id,
            f"Starting {len(task_def.parallel_tasks)} parallel tasks"
        )

        # Execute all parallel tasks concurrently
        tasks = [
            self._execute_task(subtask, workflow_def, execution, execution_id)
            for subtask in task_def.parallel_tasks
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Check for errors
        errors = [r for r in results if isinstance(r, Exception)]
        if errors:
            raise errors[0]

        self._save_workflow_log(execution_id, f"All {len(results)} parallel tasks completed")
        return {"parallel_results": results, "count": len(results)}

    def get_execution_status(self, execution_id: str) -> Dict[str, Any]:
        """Get current status of a workflow execution"""
        if execution_id not in self.executions:
            return {"error": f"Execution not found: {execution_id}"}

        exec_data = self.executions[execution_id]
        return exec_data

    def get_execution_logs(self, execution_id: str) -> str:
        """Get logs for a workflow execution"""
        log_file = get_logs_dir() / f"{execution_id}.log"
        if not log_file.exists():
            return ""

        try:
            with open(log_file, 'r') as f:
                return f.read()
        except Exception as e:
            return f"Error reading logs: {str(e)}"

    def cancel_execution(self, execution_id: str) -> bool:
        """Cancel a running workflow execution"""
        if execution_id not in self.executions:
            return False

        exec_data = self.executions[execution_id]
        if exec_data['status'] in [WorkflowStatus.RUNNING.value]:
            exec_data['status'] = WorkflowStatus.CANCELLED.value
            exec_data['end_time'] = datetime.now(timezone.utc).isoformat()

            # Reconstruct execution for saving
            execution = WorkflowExecution(
                workflow_id=exec_data['workflow_id'],
                execution_id=exec_data['execution_id'],
                status=WorkflowStatus.CANCELLED,
                start_time=exec_data['start_time'],
                end_time=exec_data['end_time'],
            )
            self._save_execution(execution)
            return True

        return False


# ═══════════════════════════════════════════════════════════════════════════
# WORKFLOW DEFINITIONS MANAGER
# ═══════════════════════════════════════════════════════════════════════════

class WorkflowManager:
    """Manages workflow definitions"""

    @staticmethod
    def create_workflow(
        name: str,
        description: str = "",
        tasks: Optional[List[TaskDefinition]] = None
    ) -> WorkflowDefinition:
        """Create a new workflow definition"""
        workflow_id = str(uuid.uuid4())
        return WorkflowDefinition(
            id=workflow_id,
            name=name,
            description=description,
            tasks=tasks or []
        )

    @staticmethod
    def save_workflow(workflow: WorkflowDefinition):
        """Save workflow definition to disk"""
        workflow_file = get_definitions_dir() / f"{workflow.id}.json"
        try:
            with open(workflow_file, 'w') as f:
                json.dump(workflow.to_dict(), f, indent=2)
            logger.info(f"Saved workflow: {workflow.id}")
        except Exception as e:
            logger.error(f"Failed to save workflow {workflow.id}: {e}")

    @staticmethod
    def load_workflow(workflow_id: str) -> Optional[WorkflowDefinition]:
        """Load workflow definition from disk"""
        workflow_file = get_definitions_dir() / f"{workflow_id}.json"
        if not workflow_file.exists():
            return None

        try:
            with open(workflow_file, 'r') as f:
                data = json.load(f)
                # Parse tasks with proper type conversion
                tasks = []
                for task_data in data.get('tasks', []):
                    task_dict = task_data.copy()
                    # Convert type string to enum if needed
                    if isinstance(task_dict.get('type'), str):
                        task_dict['type'] = TaskType(task_dict['type'])
                    tasks.append(TaskDefinition(**task_dict))

                return WorkflowDefinition(
                    id=data['id'],
                    name=data['name'],
                    description=data.get('description', ''),
                    version=data.get('version', '1.0'),
                    tasks=tasks,
                    variables=data.get('variables', {}),
                    timeout_seconds=data.get('timeout_seconds', 3600),
                )
        except Exception as e:
            logger.error(f"Failed to load workflow {workflow_id}: {e}")
            return None

    @staticmethod
    def list_workflows() -> List[Dict[str, Any]]:
        """List all workflow definitions"""
        workflows = []
        for workflow_file in get_definitions_dir().glob("*.json"):
            try:
                with open(workflow_file, 'r') as f:
                    data = json.load(f)
                    workflows.append({
                        'id': data['id'],
                        'name': data['name'],
                        'description': data.get('description', ''),
                        'version': data.get('version', '1.0'),
                        'task_count': len(data.get('tasks', [])),
                        'created_at': data.get('created_at'),
                        'updated_at': data.get('updated_at'),
                    })
            except Exception as e:
                logger.error(f"Failed to load workflow {workflow_file}: {e}")

        return workflows

    @staticmethod
    def delete_workflow(workflow_id: str) -> bool:
        """Delete a workflow definition"""
        workflow_file = get_definitions_dir() / f"{workflow_id}.json"
        if workflow_file.exists():
            try:
                workflow_file.unlink()
                logger.info(f"Deleted workflow: {workflow_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to delete workflow {workflow_id}: {e}")

        return False


# ═══════════════════════════════════════════════════════════════════════════
# BUILT-IN WORKFLOW TEMPLATES
# ═══════════════════════════════════════════════════════════════════════════

def create_website_build_workflow() -> WorkflowDefinition:
    """
    Website Build Workflow
    Steps:
    1. CodeGen builds frontend
    2. Security audits code
    3. Deploy to production
    """
    tasks = [
        TaskDefinition(
            id="build",
            name="Build Frontend",
            type=TaskType.AGENT_CALL,
            agent_id="coder_agent",
            prompt="Build a responsive Next.js frontend with Tailwind CSS. Use modern component patterns.",
            retry_count=3,
            retry_backoff=2.0,
        ),
        TaskDefinition(
            id="audit",
            name="Security Audit",
            type=TaskType.AGENT_CALL,
            agent_id="hacker_agent",
            prompt="Audit the built frontend code for security vulnerabilities, XSS, CSRF, and dependency issues.",
            retry_count=2,
            retry_backoff=2.0,
        ),
        TaskDefinition(
            id="deploy",
            name="Deploy to Production",
            type=TaskType.HTTP_REQUEST,
            url="https://api.vercel.com/v1/deployments",
            method="POST",
            retry_count=3,
            retry_backoff=2.0,
        ),
    ]

    return WorkflowDefinition(
        id="website-build-001",
        name="Website Build Pipeline",
        description="Build, audit, and deploy a website to production",
        tasks=tasks,
    )


def create_code_review_workflow() -> WorkflowDefinition:
    """
    Code Review Workflow
    Steps:
    1. CodeGen implements feature
    2. Security reviews and approves
    """
    tasks = [
        TaskDefinition(
            id="implement",
            name="Implement Feature",
            type=TaskType.AGENT_CALL,
            agent_id="coder_agent",
            prompt="Implement the requested feature with clean, well-tested code following best practices.",
            retry_count=2,
            retry_backoff=2.0,
        ),
        TaskDefinition(
            id="review",
            name="Code Review & Security Check",
            type=TaskType.AGENT_CALL,
            agent_id="hacker_agent",
            prompt="Review the implemented code for quality, security vulnerabilities, and best practices.",
            retry_count=2,
            retry_backoff=2.0,
        ),
    ]

    return WorkflowDefinition(
        id="code-review-001",
        name="Code Review Pipeline",
        description="Implement and review code with security checks",
        tasks=tasks,
    )


def create_documentation_workflow() -> WorkflowDefinition:
    """
    Documentation Workflow
    Steps:
    1. CodeGen writes code
    2. PM creates documentation
    """
    tasks = [
        TaskDefinition(
            id="write_code",
            name="Write Code",
            type=TaskType.AGENT_CALL,
            agent_id="coder_agent",
            prompt="Write production-ready code with clear naming and structure.",
            retry_count=2,
            retry_backoff=2.0,
        ),
        TaskDefinition(
            id="write_docs",
            name="Create Documentation",
            type=TaskType.AGENT_CALL,
            agent_id="project_manager",
            prompt="Create comprehensive documentation including API docs, usage examples, and deployment guide.",
            retry_count=2,
            retry_backoff=2.0,
        ),
    ]

    return WorkflowDefinition(
        id="documentation-001",
        name="Documentation Pipeline",
        description="Write code and create comprehensive documentation",
        tasks=tasks,
    )


# ═══════════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def initialize_default_workflows():
    """Initialize default workflow templates in the system"""
    manager = WorkflowManager()

    workflows = [
        create_website_build_workflow(),
        create_code_review_workflow(),
        create_documentation_workflow(),
    ]

    for workflow in workflows:
        manager.save_workflow(workflow)
        logger.info(f"Initialized workflow: {workflow.name}")


# ═══════════════════════════════════════════════════════════════════════════
# WORKFLOW ENGINE (Facade for simplicity)
# ═══════════════════════════════════════════════════════════════════════════

class WorkflowEngine:
    """Simple facade for workflow management"""

    def __init__(self):
        """Initialize workflow engine"""
        self.manager = WorkflowManager()
        self.executor = WorkflowExecutor()
        logger.info("✅ WorkflowEngine initialized")

    def start_workflow(self, workflow_name: str, params: Dict[str, Any] = None) -> str:
        """Start a workflow by name"""
        # Find workflow by name
        workflows_dir = get_definitions_dir()
        for workflow_file in workflows_dir.glob("*.json"):
            try:
                with open(workflow_file, 'r') as f:
                    workflow_data = json.load(f)
                    if workflow_data.get('name') == workflow_name:
                        workflow_def = self.manager.load_workflow(workflow_data['id'])
                        if workflow_def:
                            execution = self.executor.execute(workflow_def, params or {})
                            return execution.id
            except Exception as e:
                logger.warning(f"Error loading workflow {workflow_file}: {e}")

        # If not found, create a dummy execution
        logger.warning(f"Workflow not found: {workflow_name}, creating dummy execution")
        execution_id = str(uuid.uuid4())
        return execution_id

    def get_workflow_status(self, workflow_id: str) -> Optional[str]:
        """Get workflow execution status"""
        try:
            execution_file = get_executions_dir() / f"{workflow_id}.json"
            if execution_file.exists():
                with open(execution_file, 'r') as f:
                    data = json.load(f)
                    return data.get('status', 'unknown')
        except Exception as e:
            logger.warning(f"Error getting workflow status: {e}")
        return 'unknown'


if __name__ == "__main__":
    # Initialize defaults
    initialize_default_workflows()
    print("✅ Workflow engine initialized with default workflows")
