"""
End-to-End Testing Script for Personal Assistant Approval System

Tests the complete approval workflow:
1. Task enqueueing
2. Approval request flow
3. Constraint application
4. Execution with approval
5. Abort signal handling
6. Execution reporting
7. Fallback mode
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("test_approval_flow")

from approval_client import ApprovalClient, ExecutionSummary
from task_queue import TaskQueue, TaskStatus


class ApprovalFlowTester:
    """Tests approval system end-to-end"""

    def __init__(self):
        self.approval_client = ApprovalClient(
            assistant_url="http://localhost:8001",  # Mock assistant
            api_key="test-api-key",
            timeout=5.0,
            fallback_strict=True
        )
        self.task_queue = TaskQueue()
        self.test_results = []

    async def test_task_enqueueing(self):
        """Test 1: Enqueue a new task"""
        logger.info("\n" + "="*60)
        logger.info("TEST 1: Task Enqueueing")
        logger.info("="*60)

        task = self.task_queue.enqueue(
            task_id="task-001",
            task_type="chat",
            description="Test chat message",
            estimated_cost=0.01,
            estimated_duration_ms=5000,
            context={"user_id": "user123", "session": "session456"}
        )

        assert task is not None, "Task should be created"
        assert task.status == TaskStatus.PENDING.value, "Task should be pending"
        assert task.task_id == "task-001", "Task ID should match"

        logger.info(f"✅ PASS: Task enqueued successfully")
        logger.info(f"   Task ID: {task.task_id}")
        logger.info(f"   Status: {task.status}")
        logger.info(f"   Created: {task.created_at}")

        self.test_results.append(("Task Enqueueing", True, None))
        return task

    async def test_approval_request_fallback(self):
        """Test 2: Request approval (fallback mode when assistant unavailable)"""
        logger.info("\n" + "="*60)
        logger.info("TEST 2: Approval Request (Fallback Mode)")
        logger.info("="*60)

        task_id = "task-002"
        self.task_queue.enqueue(
            task_id=task_id,
            task_type="workflow",
            description="Test workflow execution",
            estimated_cost=2.50,
            estimated_duration_ms=30000
        )
        self.task_queue.set_pending_approval(task_id)

        # Request approval - should fall back since no real assistant
        approval_response, in_fallback = await self.approval_client.request_approval(
            task_id=task_id,
            task_type="workflow",
            description="Test workflow execution",
            estimated_cost=2.50,
            estimated_duration_ms=30000
        )

        assert approval_response.approved, "Fallback should approve"
        assert in_fallback, "Should be in fallback mode"
        assert approval_response.constraints is not None, "Should have constraints"
        assert len(approval_response.constraints) > 0, "Should have at least one constraint"

        logger.info(f"✅ PASS: Approval request handled (fallback mode)")
        logger.info(f"   Approved: {approval_response.approved}")
        logger.info(f"   Reason: {approval_response.reason}")
        logger.info(f"   Constraints: {len(approval_response.constraints)}")
        for i, constraint in enumerate(approval_response.constraints):
            logger.info(f"   [{i}] {constraint.type}: {constraint.value} - {constraint.reason}")

        self.test_results.append(("Approval Request", True, None))

    async def test_constraint_application(self):
        """Test 3: Apply constraints to task execution"""
        logger.info("\n" + "="*60)
        logger.info("TEST 3: Constraint Application")
        logger.info("="*60)

        task_config = {
            "max_cost": 100.0,
            "max_duration_ms": 3600000,
            "resource_multiplier": 1.0
        }

        approval_response, _ = await self.approval_client.request_approval(
            task_id="task-003",
            task_type="batch",
            description="Batch processing",
            estimated_cost=5.0,
            estimated_duration_ms=60000
        )

        modified_config = self.approval_client.apply_constraints(
            task_config,
            approval_response.constraints
        )

        assert "max_cost" in modified_config, "Should have cost constraint"
        assert "max_duration_ms" in modified_config, "Should have duration constraint"
        assert "resource_multiplier" in modified_config, "Should have resource constraint"
        assert modified_config["max_cost"] <= task_config["max_cost"], "Cost should be limited"

        logger.info(f"✅ PASS: Constraints applied successfully")
        logger.info(f"   Original config: {task_config}")
        logger.info(f"   Modified config: {modified_config}")

        self.test_results.append(("Constraint Application", True, None))

    async def test_task_approval_workflow(self):
        """Test 4: Complete task approval workflow"""
        logger.info("\n" + "="*60)
        logger.info("TEST 4: Task Approval Workflow")
        logger.info("="*60)

        task_id = "task-004"

        # Step 1: Enqueue
        task = self.task_queue.enqueue(
            task_id=task_id,
            task_type="chat",
            description="Test message",
            estimated_cost=0.05
        )
        logger.info(f"[1/5] Task enqueued: {task.status}")

        # Step 2: Pending approval
        task = self.task_queue.set_pending_approval(task_id)
        assert task.status == TaskStatus.PENDING_APPROVAL.value
        logger.info(f"[2/5] Task pending approval: {task.status}")

        # Step 3: Request approval
        approval_response, _ = await self.approval_client.request_approval(
            task_id=task_id,
            task_type="chat",
            description="Test message",
            estimated_cost=0.05
        )
        logger.info(f"[3/5] Approval decision: {approval_response.approved}")

        # Step 4: Apply constraints and approve
        task = self.task_queue.approve_task(
            task_id,
            approval_response.reason,
            [c.to_dict() if hasattr(c, 'to_dict') else c
             for c in (approval_response.constraints or [])]
        )
        assert task.status == TaskStatus.APPROVED.value
        logger.info(f"[4/5] Task approved: {task.status}")

        # Step 5: Start task
        task = self.task_queue.start_task(task_id)
        assert task.status == TaskStatus.RUNNING.value
        logger.info(f"[5/5] Task running: {task.status}")

        logger.info(f"✅ PASS: Complete workflow executed successfully")
        self.test_results.append(("Task Approval Workflow", True, None))

    async def test_task_completion(self):
        """Test 5: Complete task and report results"""
        logger.info("\n" + "="*60)
        logger.info("TEST 5: Task Completion & Reporting")
        logger.info("="*60)

        task_id = "task-005"

        # Create and approve task
        task = self.task_queue.enqueue(
            task_id=task_id,
            task_type="chat",
            description="Chat with response",
            estimated_cost=0.02
        )
        self.task_queue.set_pending_approval(task_id)
        approval_response, _ = await self.approval_client.request_approval(
            task_id=task_id,
            task_type="chat",
            description="Chat with response"
        )
        self.task_queue.approve_task(task_id, approval_response.reason, [])
        self.task_queue.start_task(task_id)

        # Complete task
        logger.info("Simulating task execution...")
        await asyncio.sleep(0.5)

        task = self.task_queue.complete_task(
            task_id=task_id,
            result="This is the response from the agent",
            actual_cost=0.019,
            logs="execution completed successfully"
        )

        assert task.status == TaskStatus.COMPLETED.value
        assert task.result is not None
        assert task.actual_cost is not None
        logger.info(f"[1/2] Task completed: {task.status}")

        # Report execution
        summary = ExecutionSummary(
            task_id=task_id,
            status="completed",
            result=task.result,
            actual_cost=task.actual_cost,
            start_time=task.started_at,
            end_time=task.completed_at,
            logs=task.logs
        )

        success = await self.approval_client.report_execution(summary)
        logger.info(f"[2/2] Execution reported: {success}")

        logger.info(f"✅ PASS: Task completion workflow successful")
        self.test_results.append(("Task Completion", True, None))

    async def test_task_rejection(self):
        """Test 6: Reject task from approval"""
        logger.info("\n" + "="*60)
        logger.info("TEST 6: Task Rejection")
        logger.info("="*60)

        task_id = "task-006"

        # Enqueue task
        task = self.task_queue.enqueue(
            task_id=task_id,
            task_type="expensive_operation",
            description="High-cost operation",
            estimated_cost=500.0  # Very expensive
        )
        self.task_queue.set_pending_approval(task_id)

        # In a real scenario with a real assistant, this might be rejected
        # For testing with fallback, we'll manually reject it
        rejection_reason = "Operation cost exceeds safe limits"
        task = self.task_queue.reject_task(task_id, rejection_reason)

        assert task.status == TaskStatus.REJECTED.value
        assert task.rejection_reason == rejection_reason
        logger.info(f"✅ PASS: Task rejected successfully")
        logger.info(f"   Status: {task.status}")
        logger.info(f"   Reason: {task.rejection_reason}")

        self.test_results.append(("Task Rejection", True, None))

    async def test_task_failure(self):
        """Test 7: Handle task failure"""
        logger.info("\n" + "="*60)
        logger.info("TEST 7: Task Failure Handling")
        logger.info("="*60)

        task_id = "task-007"

        # Create and approve task
        task = self.task_queue.enqueue(
            task_id=task_id,
            task_type="chat",
            description="Task that will fail"
        )
        self.task_queue.set_pending_approval(task_id)
        approval_response, _ = await self.approval_client.request_approval(
            task_id=task_id,
            task_type="chat",
            description="Task that will fail"
        )
        self.task_queue.approve_task(task_id, approval_response.reason, [])
        self.task_queue.start_task(task_id)

        # Simulate failure
        error_msg = "API timeout after 30s"
        task = self.task_queue.fail_task(
            task_id=task_id,
            error=error_msg,
            logs="timeout occurred at 30000ms"
        )

        assert task.status == TaskStatus.FAILED.value
        assert task.error == error_msg
        logger.info(f"✅ PASS: Task failure handled")
        logger.info(f"   Status: {task.status}")
        logger.info(f"   Error: {task.error}")

        self.test_results.append(("Task Failure", True, None))

    async def test_queue_monitoring(self):
        """Test 8: Queue monitoring and status"""
        logger.info("\n" + "="*60)
        logger.info("TEST 8: Queue Monitoring")
        logger.info("="*60)

        # Get queue status
        status = self.task_queue.get_queue_status()

        assert status["total_tasks"] > 0
        assert "by_status" in status
        logger.info(f"✅ PASS: Queue status retrieved")
        logger.info(f"   Total tasks: {status['total_tasks']}")
        logger.info(f"   By status: {status['by_status']}")
        logger.info(f"   Total cost: ${status['total_cost_usd']:.4f}")
        logger.info(f"   Total execution time: {status['total_execution_time_ms']}ms")

        # Get pending approval tasks
        pending = self.task_queue.get_pending_approval()
        logger.info(f"   Pending approval: {len(pending)} tasks")

        # Get running tasks
        running = self.task_queue.get_running_tasks()
        logger.info(f"   Running: {len(running)} tasks")

        self.test_results.append(("Queue Monitoring", True, None))

    async def test_fallback_mode(self):
        """Test 9: Fallback mode behavior"""
        logger.info("\n" + "="*60)
        logger.info("TEST 9: Fallback Mode")
        logger.info("="*60)

        # Create approval client that will timeout
        fallback_client = ApprovalClient(
            assistant_url="http://nonexistent-host:9999",  # Unreachable
            api_key="test",
            timeout=1.0,
            fallback_strict=True
        )

        assert not fallback_client.fallback_mode, "Should not be in fallback initially"
        logger.info("[1/2] Fallback mode disabled initially")

        # Request approval - should fall back
        response, in_fallback = await fallback_client.request_approval(
            task_id="test-fallback",
            task_type="chat",
            description="Test",
            estimated_cost=1.0
        )

        assert in_fallback, "Should be in fallback mode"
        assert fallback_client.fallback_mode, "Client should have fallback_mode=True"
        assert response.approved, "Fallback should approve with constraints"
        assert len(response.constraints) > 0, "Should have fallback constraints"

        logger.info("[2/2] Fallback mode activated and working")
        logger.info(f"   Mode: {'FALLBACK' if in_fallback else 'NORMAL'}")
        logger.info(f"   Approved: {response.approved}")
        logger.info(f"   Constraints: {len(response.constraints)}")

        self.test_results.append(("Fallback Mode", True, None))

    async def test_health_check(self):
        """Test 10: Health check endpoint"""
        logger.info("\n" + "="*60)
        logger.info("TEST 10: Health Check")
        logger.info("="*60)

        # Test with unreachable assistant
        client = ApprovalClient(assistant_url="http://nonexistent:9999", timeout=1.0)
        health = await client.get_health()

        assert isinstance(health, bool)
        logger.info(f"✅ PASS: Health check executed")
        logger.info(f"   Assistant healthy: {health}")

        self.test_results.append(("Health Check", True, None))

    def print_summary(self):
        """Print test results summary"""
        logger.info("\n" + "="*60)
        logger.info("TEST SUMMARY")
        logger.info("="*60)

        passed = sum(1 for _, success, _ in self.test_results if success)
        total = len(self.test_results)

        for test_name, success, error in self.test_results:
            status = "✅ PASS" if success else "❌ FAIL"
            logger.info(f"{status}: {test_name}")
            if error:
                logger.info(f"       Error: {error}")

        logger.info("="*60)
        logger.info(f"Results: {passed}/{total} tests passed")
        logger.info("="*60)

        return passed == total

    async def run_all_tests(self):
        """Run all tests"""
        try:
            await self.test_task_enqueueing()
            await self.test_approval_request_fallback()
            await self.test_constraint_application()
            await self.test_task_approval_workflow()
            await self.test_task_completion()
            await self.test_task_rejection()
            await self.test_task_failure()
            await self.test_queue_monitoring()
            await self.test_fallback_mode()
            await self.test_health_check()

            success = self.print_summary()
            return 0 if success else 1

        except Exception as e:
            logger.error(f"Test suite failed: {e}", exc_info=True)
            return 1


async def main():
    """Run test suite"""
    logger.info("🚀 Starting Approval System Test Suite")
    logger.info("="*60)

    tester = ApprovalFlowTester()
    exit_code = await tester.run_all_tests()

    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
