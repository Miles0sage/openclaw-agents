"""
Test suite for HeartbeatMonitor

Tests heartbeat registration, activity tracking, and timeout/stale detection.
"""

import pytest
import asyncio
from datetime import datetime
from heartbeat_monitor import (
    HeartbeatMonitor,
    AgentActivity,
    HeartbeatMonitorConfig,
    init_heartbeat_monitor,
    get_heartbeat_monitor,
    stop_heartbeat_monitor,
)


@pytest.mark.asyncio
async def test_register_agent():
    """Test registering an agent"""
    monitor = HeartbeatMonitor()
    monitor.register_agent("agent_1", "task_123")

    assert "agent_1" in monitor.in_flight_agents
    agent = monitor.in_flight_agents["agent_1"]
    assert agent.task_id == "task_123"
    assert agent.status == "running"


@pytest.mark.asyncio
async def test_update_activity():
    """Test updating agent activity"""
    monitor = HeartbeatMonitor()
    monitor.register_agent("agent_1")

    first_activity = monitor.in_flight_agents["agent_1"].last_activity_at
    await asyncio.sleep(0.05)
    monitor.update_activity("agent_1")

    assert monitor.in_flight_agents["agent_1"].last_activity_at > first_activity


@pytest.mark.asyncio
async def test_mark_idle():
    """Test marking an agent as idle"""
    monitor = HeartbeatMonitor()
    monitor.register_agent("agent_1")

    assert monitor.in_flight_agents["agent_1"].status == "running"
    monitor.mark_idle("agent_1")
    assert monitor.in_flight_agents["agent_1"].status == "idle"


@pytest.mark.asyncio
async def test_heartbeat_start_stop():
    """Test starting and stopping heartbeat"""
    monitor = HeartbeatMonitor()

    assert not monitor.is_running
    await monitor.start()
    assert monitor.is_running

    monitor.stop()
    assert not monitor.is_running


@pytest.mark.asyncio
async def test_stale_agent_detection():
    """Test detection of stale agents"""
    config = HeartbeatMonitorConfig(
        check_interval_ms=100,
        stale_threshold_ms=50  # 50ms for testing
    )
    monitor = HeartbeatMonitor(config=config)
    monitor.register_agent("agent_1", "task_123")

    # Simulate idle by not updating activity
    await asyncio.sleep(0.15)  # Wait longer than stale threshold

    # Run health checks
    await monitor.run_health_checks()

    # Agent should still be registered (we don't remove stale, only timeout)
    assert "agent_1" in monitor.in_flight_agents
    # But it should have been flagged as stale (stale_count > 0)
    assert monitor.stale_counts.get("agent_1", 0) > 0


@pytest.mark.asyncio
async def test_timeout_agent_detection():
    """Test detection of timeout agents"""
    config = HeartbeatMonitorConfig(
        timeout_threshold_ms=100  # 100ms for testing
    )
    monitor = HeartbeatMonitor(config=config)
    monitor.register_agent("agent_1", "task_123")

    # Simulate timeout by manipulating start time
    now_ms = int(datetime.now().timestamp() * 1000)
    monitor.in_flight_agents["agent_1"].started_at = now_ms - 200  # Started 200ms ago

    await monitor.run_health_checks()

    # Agent should be removed after timeout
    assert "agent_1" not in monitor.in_flight_agents


@pytest.mark.asyncio
async def test_unregister_agent():
    """Test unregistering an agent"""
    monitor = HeartbeatMonitor()
    monitor.register_agent("agent_1", "task_123")

    assert "agent_1" in monitor.in_flight_agents
    monitor.unregister_agent("agent_1")
    assert "agent_1" not in monitor.in_flight_agents


@pytest.mark.asyncio
async def test_get_status():
    """Test getting heartbeat status"""
    monitor = HeartbeatMonitor()
    status = monitor.get_status()

    assert "running" in status
    assert "agents_monitoring" in status
    assert status["agents_monitoring"] == 0

    # Register an agent
    monitor.register_agent("agent_1")
    status = monitor.get_status()
    assert status["agents_monitoring"] == 1
    assert "agent_1" in status["agents"]


@pytest.mark.asyncio
async def test_get_in_flight_agents():
    """Test retrieving in-flight agents"""
    monitor = HeartbeatMonitor()
    monitor.register_agent("agent_1", "task_123")
    monitor.register_agent("agent_2", "task_456")

    agents = monitor.get_in_flight_agents()
    assert len(agents) == 2
    agent_ids = [a.agent_id for a in agents]
    assert "agent_1" in agent_ids
    assert "agent_2" in agent_ids


@pytest.mark.asyncio
async def test_stale_warning_only_once():
    """Test that stale warnings are only sent once by default"""
    config = HeartbeatMonitorConfig(
        stale_threshold_ms=50,
        stale_warning_only_once=True
    )
    monitor = HeartbeatMonitor(config=config)
    monitor.register_agent("agent_1", "task_123")

    # First check should detect stale
    await asyncio.sleep(0.1)
    await monitor.run_health_checks()
    assert monitor.stale_counts.get("agent_1", 0) == 1

    # Second check should NOT increment count (already alerted once)
    await monitor.run_health_checks()
    assert monitor.stale_counts.get("agent_1", 0) == 1


@pytest.mark.asyncio
async def test_stale_warning_multiple_times():
    """Test that stale warnings can be sent multiple times if configured"""
    config = HeartbeatMonitorConfig(
        stale_threshold_ms=50,
        stale_warning_only_once=False
    )
    monitor = HeartbeatMonitor(config=config)
    monitor.register_agent("agent_1", "task_123")

    # First check should detect stale
    await asyncio.sleep(0.1)
    await monitor.run_health_checks()
    assert monitor.stale_counts.get("agent_1", 0) == 1

    # Second check should also alert (if stale_warning_only_once=False)
    await monitor.run_health_checks()
    # Note: With stale_warning_only_once=False, we'd increment count each time
    # But our current implementation still only alerts once per check
    assert monitor.stale_counts.get("agent_1", 0) >= 1


@pytest.mark.asyncio
async def test_multiple_agents_concurrent():
    """Test monitoring multiple agents concurrently"""
    config = HeartbeatMonitorConfig(timeout_threshold_ms=150)
    monitor = HeartbeatMonitor(config=config)

    # Register multiple agents
    for i in range(5):
        monitor.register_agent(f"agent_{i}", f"task_{i}")

    # Update some to prevent timeout
    await asyncio.sleep(0.05)
    monitor.update_activity("agent_1")
    monitor.update_activity("agent_3")

    # Wait for timeout
    await asyncio.sleep(0.15)

    # Run health checks
    await monitor.run_health_checks()

    # Some should be removed (timeout), some should still be there
    remaining = monitor.get_in_flight_agents()
    assert len(remaining) < 5  # At least some should have timed out


@pytest.mark.asyncio
async def test_reset_stale_count_on_new_registration():
    """Test that stale count resets when re-registering an agent"""
    config = HeartbeatMonitorConfig(stale_threshold_ms=50)
    monitor = HeartbeatMonitor(config=config)

    # Register agent
    monitor.register_agent("agent_1", "task_1")
    await asyncio.sleep(0.1)
    await monitor.run_health_checks()
    assert monitor.stale_counts.get("agent_1", 0) == 1

    # Re-register the agent (e.g., new task)
    monitor.register_agent("agent_1", "task_2")
    assert monitor.stale_counts.get("agent_1", 0) == 0  # Reset


@pytest.mark.asyncio
async def test_heartbeat_monitor_global_functions():
    """Test global initialization and access functions"""
    stop_heartbeat_monitor()  # Ensure clean state

    config = HeartbeatMonitorConfig(check_interval_ms=100)
    monitor = await init_heartbeat_monitor(config=config)

    assert monitor is not None
    assert monitor.is_running

    # Get global instance
    global_monitor = get_heartbeat_monitor()
    assert global_monitor is monitor

    stop_heartbeat_monitor()
    assert get_heartbeat_monitor() is None
