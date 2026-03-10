"""
Heartbeat Monitor for Agent Health Checks

Detects stale and timeout agents, sends alerts, and auto-recovers.
Python port of src/monitoring/heartbeat.ts with async/await patterns.
"""

from dataclasses import dataclass, field
from datetime import datetime
import asyncio
import logging
import os
import requests
from typing import Dict, Optional

try:
    from event_engine import emit_event
    _HAS_EVENT_ENGINE = True
except ImportError:
    _HAS_EVENT_ENGINE = False

try:
    from job_manager import update_job_status, create_job
    _HAS_JOB_MANAGER = True
except ImportError:
    _HAS_JOB_MANAGER = False

logger = logging.getLogger("heartbeat")


@dataclass
class AgentActivity:
    """Tracks activity of an in-flight agent"""
    agent_id: str
    started_at: float  # timestamp in ms
    last_activity_at: float  # timestamp in ms
    task_id: Optional[str] = None
    status: str = "running"  # "running" or "idle"


@dataclass
class HeartbeatMonitorConfig:
    """Configuration for heartbeat monitoring"""
    check_interval_ms: int = 30_000  # 30 seconds
    stale_threshold_ms: int = 5 * 60 * 1000  # 5 minutes
    timeout_threshold_ms: int = 30 * 60 * 1000  # 30 minutes
    stale_warning_only_once: bool = True


class HeartbeatMonitor:
    """Monitor agent health and detect stale/timeout conditions"""

    def __init__(self, alert_manager=None, config: HeartbeatMonitorConfig = None):
        """
        Initialize heartbeat monitor

        Args:
            alert_manager: AlertManager instance for sending alerts
            config: HeartbeatMonitorConfig with thresholds and intervals
        """
        self.in_flight_agents: Dict[str, AgentActivity] = {}
        self.alert_manager = alert_manager
        self.config = config or HeartbeatMonitorConfig()
        self.stale_counts: Dict[str, int] = {}
        self.is_running = False
        self.check_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the background health check loop"""
        if self.is_running:
            logger.warning("HeartbeatMonitor: already running")
            return

        self.is_running = True
        if self.alert_manager:
            await self.alert_manager.init()
        logger.info(
            f"⏱️ HeartbeatMonitor: started (check interval: {self.config.check_interval_ms}ms)"
        )

        # Run checks immediately, then on interval
        await self.run_health_checks()

        # Create background task for continuous checks
        self.check_task = asyncio.create_task(self._check_loop())

    async def _check_loop(self) -> None:
        """Background loop for health checks"""
        while self.is_running:
            try:
                await asyncio.sleep(self.config.check_interval_ms / 1000)
                await self.run_health_checks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"HeartbeatMonitor: error in health check loop: {e}")

    def stop(self) -> None:
        """Stop the background health check loop"""
        self.is_running = False
        if self.check_task:
            self.check_task.cancel()
        logger.info("⏱️ HeartbeatMonitor: stopped")

    def register_agent(self, agent_id: str, task_id: Optional[str] = None) -> None:
        """
        Register an in-flight agent task

        Args:
            agent_id: Unique identifier for the agent
            task_id: Optional task identifier being processed
        """
        now_ms = int(datetime.now().timestamp() * 1000)
        self.in_flight_agents[agent_id] = AgentActivity(
            agent_id=agent_id,
            started_at=now_ms,
            last_activity_at=now_ms,
            task_id=task_id,
            status="running",
        )
        self.stale_counts.pop(agent_id, None)  # Reset stale count on new task

    def update_activity(self, agent_id: str) -> None:
        """
        Update last activity timestamp for an agent

        Args:
            agent_id: Unique identifier for the agent
        """
        agent = self.in_flight_agents.get(agent_id)
        if agent:
            agent.last_activity_at = int(datetime.now().timestamp() * 1000)
            agent.status = "running"

    def mark_idle(self, agent_id: str) -> None:
        """
        Mark an agent as idle (waiting for something)

        Args:
            agent_id: Unique identifier for the agent
        """
        agent = self.in_flight_agents.get(agent_id)
        if agent:
            agent.status = "idle"

    def unregister_agent(self, agent_id: str) -> None:
        """
        Unregister an agent (task completed or failed)

        Args:
            agent_id: Unique identifier for the agent
        """
        self.in_flight_agents.pop(agent_id, None)
        self.stale_counts.pop(agent_id, None)

    def get_in_flight_agents(self) -> list:
        """Get all in-flight agents"""
        return list(self.in_flight_agents.values())

    async def run_health_checks(self) -> None:
        """Check health of all in-flight agents"""
        now_ms = int(datetime.now().timestamp() * 1000)
        agents_to_remove = []

        for agent_id, agent in list(self.in_flight_agents.items()):
            try:
                elapsed_ms = now_ms - agent.started_at
                idle_ms = now_ms - agent.last_activity_at

                # Check for timeout: task running >30min
                if elapsed_ms > self.config.timeout_threshold_ms:
                    await self._handle_timeout(agent_id, agent, elapsed_ms)
                    agents_to_remove.append(agent_id)
                    continue  # Don't also alert on stale

                # Check for stale: idle >5min but still <30min
                if (
                    idle_ms > self.config.stale_threshold_ms
                    and elapsed_ms < self.config.timeout_threshold_ms
                ):
                    await self._handle_stale(agent_id, agent, idle_ms)

            except Exception as e:
                logger.error(f"HeartbeatMonitor: error checking agent {agent_id}: {e}")

        # Clean up removed agents
        for agent_id in agents_to_remove:
            self.unregister_agent(agent_id)

    async def _handle_stale(self, agent_id: str, agent: AgentActivity, idle_ms: int) -> None:
        """
        Handle stale agent detection

        Args:
            agent_id: Unique identifier for the agent
            agent: AgentActivity object
            idle_ms: Milliseconds idle
        """
        stale_count = self.stale_counts.get(agent_id, 0)

        # Only alert once per stale agent if configured
        if self.config.stale_warning_only_once and stale_count > 0:
            return

        idle_seconds = idle_ms // 1000
        message = f"⚠️ Stale agent detected: {agent_id} idle for {idle_seconds}s"

        logger.warning(message)

        if self.alert_manager:
            await self.alert_manager.create_alert(
                "warning",
                message,
                {
                    "agent_id": agent_id,
                    "idle_ms": idle_ms,
                    "idle_seconds": idle_seconds,
                    "task_id": agent.task_id,
                    "elapsed_ms": int(datetime.now().timestamp() * 1000) - agent.started_at,
                    "source": "heartbeat-monitor",
                },
            )

        self.stale_counts[agent_id] = stale_count + 1

        # Slack notification for stale warning
        try:
            gateway_token = os.environ.get("GATEWAY_AUTH_TOKEN", "")
            requests.post(
                "http://localhost:18789/slack/report/send",
                json={"text": message, "channel": "C0AFE4QHKH7"},
                headers={"X-Auth-Token": gateway_token},
                timeout=5,
            )
        except Exception as e:
            logger.warning(f"HeartbeatMonitor: failed to send Slack stale notification: {e}")

        # Emit agent.stale event
        if _HAS_EVENT_ENGINE:
            try:
                emit_event("agent.stale", {
                    "agent_id": agent_id,
                    "idle_ms": idle_ms,
                    "task_id": agent.task_id,
                })
            except Exception as e:
                logger.warning(f"HeartbeatMonitor: failed to emit agent.stale event: {e}")

    async def _handle_timeout(
        self, agent_id: str, agent: AgentActivity, elapsed_ms: int
    ) -> None:
        """
        Handle timeout agent detection and recovery

        Args:
            agent_id: Unique identifier for the agent
            agent: AgentActivity object
            elapsed_ms: Milliseconds running
        """
        elapsed_seconds = elapsed_ms // 1000
        elapsed_minutes = elapsed_ms // 60000
        message = f"❌ Timeout: agent {agent_id} running for {elapsed_minutes}min (task: {agent.task_id or 'unknown'})"

        logger.error(message)

        # Create error alert
        if self.alert_manager:
            await self.alert_manager.create_alert(
                "error",
                message,
                {
                    "agent_id": agent_id,
                    "task_id": agent.task_id,
                    "elapsed_ms": elapsed_ms,
                    "elapsed_seconds": elapsed_seconds,
                    "elapsed_minutes": elapsed_minutes,
                    "source": "heartbeat-monitor",
                },
            )

        # Auto-recover: unregister the stale task
        self.in_flight_agents.pop(agent_id, None)
        self.stale_counts.pop(agent_id, None)

        logger.info(f"   ✅ Recovered: agent {agent_id} removed from in-flight, ready for next task")

        # Mark the agent's task as failed if it has a task_id
        if agent.task_id and _HAS_JOB_MANAGER:
            try:
                update_job_status(agent.task_id, "failed", {
                    "error": "Timeout",
                    "agent": agent_id,
                    "elapsed_ms": elapsed_ms,
                })
                logger.info(f"   Job {agent.task_id} marked as failed due to timeout")
            except Exception as e:
                logger.warning(f"HeartbeatMonitor: failed to update job status: {e}")

        # Slack notification for timeout
        try:
            gateway_token = os.environ.get("GATEWAY_AUTH_TOKEN", "")
            requests.post(
                "http://localhost:18789/slack/report/send",
                json={"text": message, "channel": "C0AFE4QHKH7"},
                headers={"X-Auth-Token": gateway_token},
                timeout=5,
            )
        except Exception as e:
            logger.warning(f"HeartbeatMonitor: failed to send Slack timeout notification: {e}")

        # Emit agent.timeout event
        if _HAS_EVENT_ENGINE:
            try:
                emit_event("agent.timeout", {
                    "agent_id": agent_id,
                    "task_id": agent.task_id,
                    "elapsed_ms": elapsed_ms,
                })
            except Exception as e:
                logger.warning(f"HeartbeatMonitor: failed to emit agent.timeout event: {e}")

    async def recover_stale_task(self, agent_id: str) -> None:
        """
        Recover a stale/timeout task by marking it failed and available for retry

        Args:
            agent_id: Unique identifier for the agent

        Note:
            When integrated with a task queue, this would:
            - Mark task as failed with {"error": "Timeout", "agent": agent_id}
            - Add task to retry queue with retryOf: task_id
        """
        agent = self.in_flight_agents.get(agent_id)
        if not agent or not agent.task_id:
            return

        logger.info(f"🔄 Recovering task {agent.task_id} from timeout agent {agent_id}")

        # TODO: If you have a task queue, implement:
        # await task_queue.updateStatus(agent.task_id, "failed", {
        #     "error": "Timeout",
        #     "agent": agent_id
        # })
        # await task_queue.addTask({
        #     "title": f"Retry: {agent.task_id}",
        #     "description": "Auto-retry from heartbeat recovery",
        #     "retryOf": agent.task_id
        # })

    def recover_and_requeue(self, agent_id: str) -> None:
        """
        Recover a timed-out agent's task, mark it failed, and re-queue
        with bumped priority (P1->P0, P2->P1, etc.).

        Args:
            agent_id: Unique identifier for the agent
        """
        agent = self.in_flight_agents.get(agent_id)
        if not agent or not agent.task_id:
            logger.warning(f"HeartbeatMonitor: cannot requeue — no task for agent {agent_id}")
            return

        task_id = agent.task_id

        # Mark the current job as failed
        if _HAS_JOB_MANAGER:
            try:
                update_job_status(task_id, "failed", {
                    "error": "Timeout — auto-requeued",
                    "agent": agent_id,
                })
            except Exception as e:
                logger.warning(f"HeartbeatMonitor: failed to mark job {task_id} as failed: {e}")

            # Create a new job with bumped priority
            try:
                priority_map = {"P1": "P0", "P2": "P1", "P3": "P2", "P4": "P3"}
                current_priority = getattr(agent, "priority", "P2")
                bumped_priority = priority_map.get(current_priority, "P0")

                new_job = create_job({
                    "title": f"Retry: {task_id}",
                    "description": f"Auto-retry from heartbeat recovery (agent {agent_id} timed out)",
                    "priority": bumped_priority,
                    "retry_of": task_id,
                })
                new_job_id = new_job.get("id", "unknown") if isinstance(new_job, dict) else "unknown"
                logger.info(
                    f"   Re-queued task {task_id} as new job {new_job_id} "
                    f"with priority {bumped_priority} (was {current_priority})"
                )
            except Exception as e:
                logger.warning(f"HeartbeatMonitor: failed to create requeue job: {e}")
        else:
            logger.warning("HeartbeatMonitor: job_manager not available, cannot requeue")

        # Notify Slack about the re-queue
        requeue_msg = (
            f"🔄 Re-queued: agent {agent_id} task {task_id} failed due to timeout. "
            f"New job created with bumped priority."
        )
        try:
            gateway_token = os.environ.get("GATEWAY_AUTH_TOKEN", "")
            requests.post(
                "http://localhost:18789/slack/report/send",
                json={"text": requeue_msg, "channel": "C0AFE4QHKH7"},
                headers={"X-Auth-Token": gateway_token},
                timeout=5,
            )
        except Exception as e:
            logger.warning(f"HeartbeatMonitor: failed to send Slack requeue notification: {e}")

        # Clean up the agent
        self.unregister_agent(agent_id)

    def get_status(self) -> Dict:
        """Get current heartbeat status"""
        return {
            "running": self.is_running,
            "agents_monitoring": len(self.in_flight_agents),
            "agents": list(self.in_flight_agents.keys()),
            "config": {
                "check_interval_ms": self.config.check_interval_ms,
                "stale_threshold_ms": self.config.stale_threshold_ms,
                "timeout_threshold_ms": self.config.timeout_threshold_ms,
            },
        }


# Global heartbeat monitor instance
_heartbeat_monitor: Optional[HeartbeatMonitor] = None


async def init_heartbeat_monitor(
    alert_manager=None, config: HeartbeatMonitorConfig = None
) -> HeartbeatMonitor:
    """
    Initialize and start the global heartbeat monitor

    Args:
        alert_manager: AlertManager instance for sending alerts
        config: HeartbeatMonitorConfig with thresholds and intervals

    Returns:
        HeartbeatMonitor instance
    """
    global _heartbeat_monitor
    if _heartbeat_monitor:
        logger.warning("HeartbeatMonitor: already initialized")
        return _heartbeat_monitor

    _heartbeat_monitor = HeartbeatMonitor(alert_manager, config)
    await _heartbeat_monitor.start()
    return _heartbeat_monitor


def get_heartbeat_monitor() -> Optional[HeartbeatMonitor]:
    """Get the global heartbeat monitor instance"""
    return _heartbeat_monitor


def stop_heartbeat_monitor() -> None:
    """Stop the global heartbeat monitor"""
    global _heartbeat_monitor
    if _heartbeat_monitor:
        _heartbeat_monitor.stop()
        _heartbeat_monitor = None
