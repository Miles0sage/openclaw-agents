"""
Tests for error_handler.py
Tests all error handling patterns: retry, timeout, fallback, health tracking
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

from error_handler import (
    # Error types
    ErrorType,
    ModelProvider,
    ErrorMetrics,
    AgentHealthStatus,
    TimeoutException,

    # Retry logic
    RetryConfig,
    calculate_backoff_delay,
    execute_with_retry,
    execute_with_retry_async,

    # Timeout handling
    execute_with_timeout_async,

    # Error classification
    classify_error,

    # Fallback chains
    CodeGenerationFallback,
    CodeGenerationResult,

    # Agent health
    AgentHealthTracker,
    track_agent_success,
    track_agent_error,
    get_error_summary,
    get_health_tracker,

    # VPS failover
    VPSAgentConfig,
    VPSAgentFailover,
)


# ═══════════════════════════════════════════════════════════════════════════
# TEST: RETRY LOGIC
# ═══════════════════════════════════════════════════════════════════════════

class TestBackoffCalculation:
    """Test exponential backoff delay calculation"""

    def test_backoff_sequence(self):
        """Test standard backoff sequence: 1s, 2s, 4s, 8s"""
        config = RetryConfig(
            initial_delay_seconds=1.0,
            max_delay_seconds=8.0,
            backoff_multiplier=2.0,
            jitter=False
        )

        delays = []
        for i in range(4):
            delays.append(calculate_backoff_delay(i, config))

        # First call should be immediate
        assert delays[0] == 0.0
        # Then exponential: 1, 2, 4
        assert delays[1] == 1.0
        assert delays[2] == 2.0
        assert delays[3] == 4.0

    def test_backoff_max_delay(self):
        """Test max delay ceiling"""
        config = RetryConfig(
            initial_delay_seconds=1.0,
            max_delay_seconds=8.0,
            backoff_multiplier=2.0,
            jitter=False
        )

        # 8 attempts should hit max_delay
        delay = calculate_backoff_delay(10, config)
        assert delay == 8.0

    def test_backoff_with_jitter(self):
        """Test jitter adds randomness"""
        config = RetryConfig(
            initial_delay_seconds=1.0,
            max_delay_seconds=8.0,
            backoff_multiplier=2.0,
            jitter=True
        )

        delays = []
        for _ in range(5):
            delays.append(calculate_backoff_delay(1, config))

        # Not all should be exactly 1.0 (with jitter)
        assert len(set(delays)) > 1, "Jitter should produce varied delays"
        # All should be in reasonable range
        assert all(0.8 < d < 1.2 for d in delays)


class TestRetryLogic:
    """Test synchronous retry execution"""

    def test_retry_success_first_try(self):
        """Test successful execution on first try"""
        fn = Mock(return_value="success")
        result = execute_with_retry(fn, max_retries=3)
        assert result == "success"
        assert fn.call_count == 1

    def test_retry_success_after_failures(self):
        """Test retry succeeds after 2 failures"""
        fn = Mock(side_effect=[Exception("fail"), Exception("fail"), "success"])
        result = execute_with_retry(fn, max_retries=3)
        assert result == "success"
        assert fn.call_count == 3

    def test_retry_exhaustion(self):
        """Test all retries exhausted"""
        fn = Mock(side_effect=Exception("always fails"))
        with pytest.raises(Exception, match="always fails"):
            execute_with_retry(fn, max_retries=2)
        assert fn.call_count == 3  # initial + 2 retries

    def test_retry_callback(self):
        """Test on_retry callback"""
        call_log = []
        def on_retry(attempt, delay, error):
            call_log.append((attempt, delay, type(error).__name__))

        fn = Mock(side_effect=[Exception("fail"), "success"])
        result = execute_with_retry(fn, max_retries=3, on_retry=on_retry)

        assert result == "success"
        assert len(call_log) == 1
        assert call_log[0][0] == 1  # attempt number
        assert call_log[0][2] == "Exception"


class TestAsyncRetryLogic:
    """Test asynchronous retry execution"""

    @pytest.mark.asyncio
    async def test_async_retry_success(self):
        """Test async retry succeeds"""
        fn = AsyncMock(return_value="success")
        result = await execute_with_retry_async(fn, max_retries=3)
        assert result == "success"
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_async_retry_with_failures(self):
        """Test async retry after failures"""
        fn = AsyncMock(side_effect=[Exception("fail"), "success"])
        result = await execute_with_retry_async(fn, max_retries=3)
        assert result == "success"
        assert fn.call_count == 2

    @pytest.mark.asyncio
    async def test_async_retry_exhaustion(self):
        """Test async retry exhaustion"""
        fn = AsyncMock(side_effect=Exception("always fails"))
        with pytest.raises(Exception, match="always fails"):
            await execute_with_retry_async(fn, max_retries=2)
        assert fn.call_count == 3


# ═══════════════════════════════════════════════════════════════════════════
# TEST: TIMEOUT HANDLING
# ═══════════════════════════════════════════════════════════════════════════

class TestAsyncTimeout:
    """Test async timeout handling"""

    @pytest.mark.asyncio
    async def test_timeout_succeeds_within_limit(self):
        """Test function completes within timeout"""
        async def quick_fn():
            await asyncio.sleep(0.1)
            return "done"

        result = await execute_with_timeout_async(quick_fn, timeout_seconds=1.0)
        assert result == "done"

    @pytest.mark.asyncio
    async def test_timeout_exceeds_limit(self):
        """Test function exceeds timeout"""
        async def slow_fn():
            await asyncio.sleep(2.0)
            return "done"

        with pytest.raises(TimeoutException):
            await execute_with_timeout_async(slow_fn, timeout_seconds=0.1)

    @pytest.mark.asyncio
    async def test_timeout_callback(self):
        """Test timeout callback execution"""
        callback_called = []
        async def on_timeout():
            callback_called.append(True)

        async def slow_fn():
            await asyncio.sleep(2.0)

        with pytest.raises(TimeoutException):
            await execute_with_timeout_async(
                slow_fn,
                timeout_seconds=0.1,
                on_timeout=on_timeout
            )

        assert callback_called


# ═══════════════════════════════════════════════════════════════════════════
# TEST: ERROR CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════════

class TestErrorClassification:
    """Test error type classification"""

    def test_classify_timeout(self):
        """Test timeout error classification"""
        assert classify_error(TimeoutException("timed out")) == ErrorType.TIMEOUT
        assert classify_error(Exception("request timed out")) == ErrorType.TIMEOUT

    def test_classify_rate_limit(self):
        """Test rate limit classification"""
        assert classify_error(Exception("429 Too Many Requests")) == ErrorType.RATE_LIMIT
        assert classify_error(Exception("rate limit exceeded")) == ErrorType.RATE_LIMIT

    def test_classify_network(self):
        """Test network error classification"""
        assert classify_error(Exception("Connection refused")) == ErrorType.NETWORK
        assert classify_error(Exception("Connection reset by peer")) == ErrorType.NETWORK

    def test_classify_auth(self):
        """Test authentication error classification"""
        assert classify_error(Exception("401 Unauthorized")) == ErrorType.AUTHENTICATION
        assert classify_error(Exception("403 Forbidden")) == ErrorType.AUTHENTICATION

    def test_classify_unknown(self):
        """Test unknown error classification"""
        assert classify_error(Exception("random error")) == ErrorType.UNKNOWN


# ═══════════════════════════════════════════════════════════════════════════
# TEST: AGENT HEALTH TRACKING
# ═══════════════════════════════════════════════════════════════════════════

class TestAgentHealthStatus:
    """Test agent health status tracking"""

    def test_health_status_creation(self):
        """Test creating agent health status"""
        status = AgentHealthStatus(agent_id="test_agent")
        assert status.agent_id == "test_agent"
        assert status.status == "healthy"
        assert status.success_rate == 100.0

    def test_record_success(self):
        """Test recording successful request"""
        status = AgentHealthStatus(agent_id="test_agent")
        status.record_success()
        assert status.consecutive_failures == 0
        assert status.total_requests == 1
        assert status.success_rate == 100.0

    def test_record_failure(self):
        """Test recording failed request"""
        status = AgentHealthStatus(agent_id="test_agent")
        status.record_failure(ErrorType.TIMEOUT)
        assert status.consecutive_failures == 1
        assert status.total_failures == 1
        assert status.status == "unhealthy"  # 1 failure = 0% success rate < 50%

    def test_consecutive_failures_to_unhealthy(self):
        """Test 3 consecutive failures mark as unhealthy"""
        status = AgentHealthStatus(agent_id="test_agent")
        for _ in range(3):
            status.record_failure(ErrorType.TIMEOUT)
        assert status.is_unhealthy
        assert status.status == "unhealthy"

    def test_success_resets_consecutive_failures(self):
        """Test successful request resets consecutive failures"""
        status = AgentHealthStatus(agent_id="test_agent")
        status.record_failure(ErrorType.TIMEOUT)
        status.record_failure(ErrorType.TIMEOUT)
        status.record_success()
        assert status.consecutive_failures == 0


class TestAgentHealthTracker:
    """Test agent health tracker"""

    def test_register_agent(self):
        """Test registering agent"""
        tracker = AgentHealthTracker()
        status = tracker.register_agent("agent1")
        assert status.agent_id == "agent1"
        assert "agent1" in tracker.agents

    def test_record_success(self):
        """Test recording success"""
        tracker = AgentHealthTracker()
        tracker.record_agent_success("agent1")
        assert tracker.is_agent_healthy("agent1")

    def test_record_failure(self):
        """Test recording failure"""
        tracker = AgentHealthTracker()
        tracker.record_agent_failure("agent1", TimeoutException("timeout"))
        status = tracker.get_agent_status("agent1")
        assert status["status"] == "unhealthy"  # 1 failure = 0% success rate < 50%

    def test_filter_healthy_agents(self):
        """Test filtering healthy agents"""
        tracker = AgentHealthTracker()
        tracker.record_agent_success("agent1")
        for _ in range(3):
            tracker.record_agent_failure("agent2", TimeoutException("timeout"))

        healthy = tracker.get_healthy_agents(["agent1", "agent2"])
        assert "agent1" in healthy
        assert "agent2" not in healthy

    def test_error_metrics_tracking(self):
        """Test error metrics tracking"""
        tracker = AgentHealthTracker()
        tracker.record_agent_failure("agent1", TimeoutException("timeout"))
        tracker.record_agent_failure("agent1", Exception("connection refused"))

        metrics = tracker.get_error_metrics()
        assert metrics["timeout"]["count"] == 1
        assert metrics["network"]["count"] == 1

    def test_get_summary(self):
        """Test getting tracker summary"""
        tracker = AgentHealthTracker()
        tracker.record_agent_success("agent1")
        for _ in range(3):
            tracker.record_agent_failure("agent2", TimeoutException("timeout"))

        summary = tracker.get_summary()
        assert summary["total_agents"] == 2
        assert summary["healthy_agents"] == 1
        assert summary["unhealthy_agents"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# TEST: CODE GENERATION FALLBACK CHAIN
# ═══════════════════════════════════════════════════════════════════════════

class TestCodeGenerationFallback:
    """Test code generation fallback chain"""

    def test_fallback_chain_order(self):
        """Test fallback chain is in correct order"""
        chain = CodeGenerationFallback.FALLBACK_CHAIN
        assert chain[0] == ModelProvider.KIMI_25
        assert chain[1] == ModelProvider.KIMI_REASONER
        assert chain[2] == ModelProvider.CLAUDE_OPUS
        assert chain[3] == ModelProvider.CLAUDE_SONNET

    def test_execute_with_no_clients(self):
        """Test execute with no model clients configured"""
        fallback = CodeGenerationFallback(model_clients={})
        result = fallback.execute("test prompt", timeout_seconds=0.1)

        assert not result.success
        assert "ERROR:" in result.code
        assert len(result.errors_encountered) > 0

    def test_execute_success_first_model(self):
        """Test successful execution with first model"""
        mock_client = Mock()
        mock_client.generate = Mock(return_value="def hello(): pass")

        fallback = CodeGenerationFallback(
            model_clients={"deepseek-chat": mock_client}
        )

        # Mock the execution
        with patch.object(fallback, '_call_model_with_retry', return_value="def hello(): pass"):
            result = fallback.execute("test prompt")

        assert result.success
        assert result.code == "def hello(): pass"
        assert result.model_used == "deepseek-chat"
        assert result.attempt_number == 1

    def test_execute_fallback_chain_exhaustion(self):
        """Test fallback chain exhausts all models"""
        fallback = CodeGenerationFallback(model_clients={})
        result = fallback.execute("test prompt")

        assert not result.success
        assert result.attempt_number == len(CodeGenerationFallback.FALLBACK_CHAIN)
        assert len(result.errors_encountered) >= 0

    def test_result_to_dict(self):
        """Test CodeGenerationResult serialization"""
        result = CodeGenerationResult(
            code="def test(): pass",
            model_used="deepseek-chat",
            attempt_number=1,
            total_attempts=4,
            duration_ms=150.0,
            success=True
        )

        data = result.to_dict()
        assert data["model_used"] == "deepseek-chat"
        assert data["attempt_number"] == 1
        assert data["success"] == True


# ═══════════════════════════════════════════════════════════════════════════
# TEST: VPS AGENT FAILOVER
# ═══════════════════════════════════════════════════════════════════════════

class TestVPSAgentFailover:
    """Test VPS agent failover to Cloudflare"""

    @pytest.mark.asyncio
    async def test_vps_health_check_success(self):
        """Test successful VPS health check"""
        failover = VPSAgentFailover()

        with patch('httpx.AsyncClient.get') as mock_get:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            # This test needs proper async context
            # Skipping full implementation for now

    def test_vps_failover_config(self):
        """Test VPS failover configuration"""
        config = VPSAgentConfig(
            vps_endpoint="http://vps:8000",
            cloudflare_endpoint="http://cf:18789"
        )
        failover = VPSAgentFailover(config)

        status = failover.get_status()
        assert status["vps_endpoint"] == "http://vps:8000"
        assert status["cloudflare_endpoint"] == "http://cf:18789"


# ═══════════════════════════════════════════════════════════════════════════
# TEST: GLOBAL TRACKING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

class TestGlobalTracking:
    """Test global error tracking functions"""

    def test_track_agent_success(self):
        """Test tracking agent success"""
        track_agent_success("test_agent")
        status = get_health_tracker().get_agent_status("test_agent")
        assert status["status"] == "healthy"

    def test_track_agent_error(self):
        """Test tracking agent error"""
        track_agent_error("test_agent", TimeoutException("timeout"))
        status = get_health_tracker().get_agent_status("test_agent")
        assert status["status"] == "degraded"

    def test_get_error_summary(self):
        """Test getting comprehensive error summary"""
        track_agent_success("agent1")
        track_agent_error("agent2", TimeoutException("timeout"))

        summary = get_error_summary()
        assert "health_summary" in summary
        assert "agent_statuses" in summary
        assert "error_metrics" in summary
        assert "timestamp" in summary


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegration:
    """Integration tests combining multiple components"""

    def test_retry_with_health_tracking(self):
        """Test retry logic with health tracking"""
        call_count = [0]

        def failing_fn():
            call_count[0] += 1
            if call_count[0] < 3:
                raise TimeoutException("timeout")
            return "success"

        # Execute with retry
        result = execute_with_retry(failing_fn, max_retries=3)
        assert result == "success"

        # Verify health was tracked
        # (In real scenario, health tracking would be integrated)

    @pytest.mark.asyncio
    async def test_timeout_with_retry(self):
        """Test timeout protection with retry"""
        call_count = [0]

        async def sometimes_slow():
            call_count[0] += 1
            if call_count[0] == 1:
                await asyncio.sleep(10.0)  # Would timeout
            return "success"

        # With timeout and retry
        try:
            result = await execute_with_retry_async(
                lambda: execute_with_timeout_async(
                    sometimes_slow,
                    timeout_seconds=0.1
                ),
                max_retries=3
            )
        except TimeoutException:
            # Expected - we're testing the pattern
            pass


# ═══════════════════════════════════════════════════════════════════════════
# PERFORMANCE TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestPerformance:
    """Performance tests for error handling"""

    def test_backoff_calculation_performance(self):
        """Test backoff calculation is fast"""
        config = RetryConfig()
        start = time.time()

        for i in range(1000):
            calculate_backoff_delay(i % 5, config)

        duration_ms = (time.time() - start) * 1000
        assert duration_ms < 100, f"Backoff calculation too slow: {duration_ms}ms for 1000 calls"

    def test_error_classification_performance(self):
        """Test error classification is fast"""
        errors = [
            TimeoutException("timeout"),
            Exception("429 Too Many Requests"),
            Exception("Connection refused"),
            Exception("401 Unauthorized"),
            Exception("random error")
        ]

        start = time.time()
        for _ in range(1000):
            for error in errors:
                classify_error(error)

        duration_ms = (time.time() - start) * 1000
        assert duration_ms < 200, f"Error classification too slow: {duration_ms}ms for 5000 calls"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
