"""
Personal Assistant Approval Client

Handles all communication with the personal assistant Worker:
- Pre-execution approval requests
- Constraint application
- Abort signal listening
- Execution summary reporting
- Fallback mode handling
"""

import httpx
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple
from enum import Enum
from dataclasses import dataclass, asdict
import time

logger = logging.getLogger("approval_client")


class ApprovalStatus(Enum):
    """Task approval statuses"""
    PENDING = "pending"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    APPROVED_WITH_CONSTRAINTS = "approved_with_constraints"
    REJECTED = "rejected"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ApprovalConstraint:
    """Constraint applied to task execution"""
    type: str  # "cost_limit", "time_limit", "resource_limit", "scope_limit"
    value: Any
    reason: str

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ApprovalResponse:
    """Response from personal assistant"""
    approved: bool
    reason: str
    constraints: Optional[list] = None  # List of ApprovalConstraint
    retry_after_seconds: Optional[int] = None  # If temporarily unavailable

    def to_dict(self) -> Dict:
        return {
            "approved": self.approved,
            "reason": self.reason,
            "constraints": [c.to_dict() if isinstance(c, ApprovalConstraint) else c for c in (self.constraints or [])],
            "retry_after_seconds": self.retry_after_seconds
        }


@dataclass
class ExecutionSummary:
    """Summary of task execution for reporting"""
    task_id: str
    status: str  # "completed", "failed", "aborted"
    result: Optional[str] = None
    actual_cost: Optional[float] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    logs: Optional[str] = None
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None

    def to_dict(self) -> Dict:
        return asdict(self)


class ApprovalClient:
    """
    Client for interacting with personal assistant approval system

    Handles:
    - Approval requests before task execution
    - Constraint enforcement
    - Abort signal listening
    - Result reporting
    - Fallback when assistant unavailable
    """

    def __init__(
        self,
        assistant_url: str = "http://localhost:8000",
        api_key: str = "",
        timeout: float = 10.0,
        fallback_strict: bool = True,
        enable_retries: bool = True,
        max_retries: int = 3,
        retry_backoff: float = 1.0
    ):
        """
        Initialize approval client

        Args:
            assistant_url: Base URL of personal assistant Worker
            api_key: API key for authentication
            timeout: Request timeout in seconds
            fallback_strict: If True, enforce strict restrictions when assistant unavailable
            enable_retries: Enable automatic retry on failures
            max_retries: Maximum retry attempts
            retry_backoff: Backoff multiplier for retries
        """
        self.assistant_url = assistant_url.rstrip('/')
        self.api_key = api_key
        self.timeout = timeout
        self.fallback_strict = fallback_strict
        self.enable_retries = enable_retries
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.fallback_mode = False
        self.fallback_retry_count = 0
        self.fallback_retry_interval = 60  # seconds
        self.health_check_interval = 300  # 5 minutes
        self.last_health_check = 0

    async def request_approval(
        self,
        task_id: str,
        task_type: str,
        description: str,
        estimated_cost: Optional[float] = None,
        estimated_duration_ms: Optional[int] = None,
        context: Optional[Dict] = None,
        retry_on_failure: bool = True
    ) -> Tuple[ApprovalResponse, bool]:
        """
        Request approval from personal assistant before executing task

        Args:
            task_id: Unique task identifier
            task_type: Type of task (chat, workflow, batch, etc.)
            description: Human-readable task description
            estimated_cost: Estimated API cost in USD
            estimated_duration_ms: Estimated execution time in milliseconds
            context: Additional context about the task
            retry_on_failure: Whether to retry on failure

        Returns:
            (ApprovalResponse, in_fallback_mode)
        """
        logger.info(f"🔐 Requesting approval for task {task_id}")

        payload = {
            "task_id": task_id,
            "task_type": task_type,
            "description": description,
            "estimated_cost": estimated_cost,
            "estimated_duration_ms": estimated_duration_ms,
            "context": context or {},
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
        }

        if self.fallback_mode:
            logger.warning(f"⚠️ Running in FALLBACK MODE - returning strict constraints")
            return self._get_fallback_approval(task_id, estimated_cost), True

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.assistant_url}/api/approve",
                    json=payload,
                    headers=self._get_headers()
                )

                if response.status_code == 200:
                    data = response.json()
                    approval = ApprovalResponse(
                        approved=data.get("approved", False),
                        reason=data.get("reason", ""),
                        constraints=[ApprovalConstraint(**c) if isinstance(c, dict) else c
                                   for c in data.get("constraints", [])],
                        retry_after_seconds=data.get("retry_after_seconds")
                    )
                    logger.info(f"✅ Approval decision: {'APPROVED' if approval.approved else 'REJECTED'} - {approval.reason}")

                    # Reset fallback state on success
                    if self.fallback_mode:
                        self.fallback_mode = False
                        self.fallback_retry_count = 0
                        logger.info("🔄 Recovering from fallback mode - assistant is back online")

                    return approval, False

                elif response.status_code == 503:
                    # Service temporarily unavailable
                    data = response.json()
                    logger.warning(f"⚠️ Assistant unavailable (503): {data.get('message')}")
                    if not self.fallback_mode:
                        self.fallback_mode = True
                        logger.warning(f"🔴 Entering FALLBACK MODE with strict constraints")
                    return self._get_fallback_approval(task_id, estimated_cost), True

                else:
                    logger.error(f"❌ Approval request failed: {response.status_code} - {response.text[:200]}")
                    raise Exception(f"Approval server error: {response.status_code}")

        except httpx.TimeoutException:
            logger.error(f"⏱️ Approval request timed out after {self.timeout}s")
            if not self.fallback_mode:
                self.fallback_mode = True
                logger.warning("🔴 Entering FALLBACK MODE due to timeout")
            return self._get_fallback_approval(task_id, estimated_cost), True

        except Exception as e:
            logger.error(f"❌ Error requesting approval: {e}")
            if retry_on_failure and self.enable_retries:
                logger.info(f"🔄 Retrying approval request...")
                await asyncio.sleep(1)
                return await self.request_approval(
                    task_id, task_type, description,
                    estimated_cost, estimated_duration_ms, context,
                    retry_on_failure=False
                )

            if not self.fallback_mode:
                self.fallback_mode = True
                logger.warning("🔴 Entering FALLBACK MODE due to error")
            return self._get_fallback_approval(task_id, estimated_cost), True

    async def listen_for_abort(
        self,
        task_id: str,
        check_interval: float = 5.0,
        timeout: Optional[float] = None
    ) -> bool:
        """
        Listen for abort signal from personal assistant

        Args:
            task_id: Task to monitor
            check_interval: How often to check (seconds)
            timeout: Maximum time to listen (seconds)

        Returns:
            True if abort signal received, False if timeout
        """
        start_time = time.time()

        while True:
            if timeout and (time.time() - start_time) > timeout:
                return False

            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.get(
                        f"{self.assistant_url}/api/abort-signal/{task_id}",
                        headers=self._get_headers()
                    )

                    if response.status_code == 200:
                        data = response.json()
                        if data.get("should_abort", False):
                            logger.warning(f"🛑 ABORT signal received for task {task_id}: {data.get('reason')}")
                            return True

            except Exception as e:
                logger.debug(f"Error checking abort signal: {e}")

            await asyncio.sleep(check_interval)

    async def report_execution(
        self,
        summary: ExecutionSummary
    ) -> bool:
        """
        Report task execution result back to personal assistant

        Args:
            summary: ExecutionSummary with task details

        Returns:
            True if report sent successfully
        """
        logger.info(f"📤 Reporting execution for task {summary.task_id}")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.assistant_url}/api/execution-report",
                    json=summary.to_dict(),
                    headers=self._get_headers()
                )

                if response.status_code == 200:
                    logger.info(f"✅ Execution report sent for task {summary.task_id}")
                    return True
                else:
                    logger.warning(f"⚠️ Failed to send report: {response.status_code}")
                    return False

        except Exception as e:
            logger.warning(f"⚠️ Error sending execution report: {e}")
            return False

    async def get_health(self) -> bool:
        """
        Check if personal assistant is healthy

        Returns:
            True if assistant is responding, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(
                    f"{self.assistant_url}/health",
                    headers=self._get_headers()
                )
                return response.status_code == 200
        except Exception:
            return False

    async def periodic_health_check(self):
        """
        Periodically check assistant health and recover from fallback mode

        Should be run as a background task
        """
        while True:
            try:
                await asyncio.sleep(self.health_check_interval)

                if self.fallback_mode:
                    logger.info("🔍 Checking if personal assistant is back online...")
                    if await self.get_health():
                        self.fallback_mode = False
                        self.fallback_retry_count = 0
                        logger.info("✅ Personal assistant is back online - recovering from fallback mode")

            except Exception as e:
                logger.error(f"Error in health check: {e}")

    def _get_fallback_approval(
        self,
        task_id: str,
        estimated_cost: Optional[float] = None
    ) -> ApprovalResponse:
        """
        Generate fallback approval with strict constraints when assistant unavailable

        Args:
            task_id: Task being approved
            estimated_cost: Estimated cost of task

        Returns:
            ApprovalResponse with strict constraints
        """
        constraints = [
            ApprovalConstraint(
                type="cost_limit",
                value=min(estimated_cost or 1.0, 5.0),
                reason="Fallback mode: strict cost limit due to assistant unavailability"
            ),
            ApprovalConstraint(
                type="time_limit",
                value=300000,  # 5 minutes in ms
                reason="Fallback mode: strict time limit due to assistant unavailability"
            ),
            ApprovalConstraint(
                type="resource_limit",
                value=0.5,
                reason="Fallback mode: reduced resource allocation due to assistant unavailability"
            )
        ]

        log_msg = f"📝 Fallback approval for {task_id} with constraints: cost<${constraints[0].value}, time<{constraints[1].value}ms"
        logger.warning(log_msg)

        return ApprovalResponse(
            approved=True,
            reason="Approved in fallback mode with strict constraints",
            constraints=constraints,
            retry_after_seconds=self.fallback_retry_interval
        )

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers"""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "OpenClaw-Gateway/1.0"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def apply_constraints(
        self,
        task_config: Dict,
        constraints: Optional[list] = None
    ) -> Dict:
        """
        Apply approval constraints to task execution config

        Args:
            task_config: Original task configuration
            constraints: List of ApprovalConstraint objects

        Returns:
            Modified task configuration with constraints applied
        """
        if not constraints:
            return task_config

        modified_config = task_config.copy()

        for constraint in constraints:
            if isinstance(constraint, dict):
                constraint_type = constraint.get("type")
                value = constraint.get("value")
            else:
                constraint_type = constraint.type
                value = constraint.value

            if constraint_type == "cost_limit":
                modified_config["max_cost"] = value
                logger.info(f"💰 Applied cost limit: ${value}")

            elif constraint_type == "time_limit":
                modified_config["max_duration_ms"] = value
                logger.info(f"⏱️ Applied time limit: {value}ms")

            elif constraint_type == "resource_limit":
                modified_config["resource_multiplier"] = value
                logger.info(f"🔧 Applied resource limit: {value}x")

            elif constraint_type == "scope_limit":
                modified_config["scope_limit"] = value
                logger.info(f"📏 Applied scope limit: {value}")

        return modified_config
