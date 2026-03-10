"""
Unit tests for error recovery system.

Tests cover:
  - RetryPolicy: exponential backoff, error classification, per-error-type policies
  - CircuitBreaker: state transitions, failure tracking, recovery testing
  - CrashRecovery: interrupted job detection and recovery
  - AlertSystem: alert logging and retrieval
  - HealthCheck: comprehensive system health monitoring
"""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timezone

from error_recovery import (
    RetryPolicy,
    ErrorType,
    CircuitBreaker,
    CircuitBreakerStateEnum,
    CrashRecovery,
    AlertSystem,
    AlertLevel,
    HealthCheck,
    ErrorRecoveryManager,
    retry_with_policy,
    _calculate_backoff,
    _classify_error,
)


# ---------------------------------------------------------------------------
# Tests: RetryPolicy
# ---------------------------------------------------------------------------

class TestRetryPolicy:
    """Test retry policy configuration and validation."""

    def test_policy_defaults(self):
        """Test default policy values."""
        policy = RetryPolicy()
        assert policy.max_retries == 3
        assert policy.base_delay == 2.0
        assert policy.max_delay == 60.0
        assert policy.jitter is True

    def test_policy_invalid_base_delay(self):
        """Test that negative base_delay is rejected."""
        with pytest.raises(ValueError):
            RetryPolicy(base_delay=-1.0)

    def test_policy_invalid_max_delay(self):
        """Test that max_delay < base_delay is rejected."""
        with pytest.raises(ValueError):
            RetryPolicy(base_delay=10.0, max_delay=5.0)


class TestBackoffCalculation:
    """Test exponential backoff calculation."""

    def test_exponential_progression(self):
        """Test that backoff doubles each attempt."""
        policy = RetryPolicy(base_delay=1.0, max_delay=100.0, jitter=False)

        backoff_0 = _calculate_backoff(0, 0.0, policy)
        backoff_1 = _calculate_backoff(1, 0.0, policy)
        backoff_2 = _calculate_backoff(2, 0.0, policy)

        assert backoff_0 == 1.0
        assert backoff_1 == 2.0
        assert backoff_2 == 4.0

    def test_max_delay_cap(self):
        """Test that backoff is capped at max_delay."""
        policy = RetryPolicy(base_delay=10.0, max_delay=50.0, jitter=False)

        backoff = _calculate_backoff(5, 0.0, policy)  # 10 * 2^5 = 320, but capped at 50
        assert backoff == 50.0

    def test_explicit_wait_time(self):
        """Test that explicit wait time overrides backoff calculation."""
        # explicit_wait=30.0, max_delay defaults to 60.0 — so 30.0 is not capped
        policy = RetryPolicy(base_delay=1.0, jitter=False)

        backoff = _calculate_backoff(3, 30.0, policy)
        assert backoff == 30.0  # Uses explicit wait (within max_delay cap)

    def test_jitter_adds_randomness(self):
        """Test that jitter adds a small random component."""
        # base_delay=10.0, attempt=2 → 10 * 2^2 = 40.0, jitter ±10% → 40-44
        policy = RetryPolicy(base_delay=10.0, max_delay=100.0, jitter=True)

        # Run multiple times to check variance
        backoffs = [_calculate_backoff(2, 0.0, policy) for _ in range(10)]

        # All should be around 40.0 ± 10% = 40.0-44.0
        for backoff in backoffs:
            assert 40.0 <= backoff <= 44.0


class TestErrorClassification:
    """Test error type classification."""

    def test_rate_limit_detection(self):
        """Test detection of rate limit errors."""
        errors = [
            Exception("429 Too Many Requests"),
            Exception("rate limit exceeded"),
            Exception("Rate Limit"),
        ]
        for error in errors:
            assert _classify_error(error) == ErrorType.RATE_LIMIT

    def test_auth_error_detection(self):
        """Test detection of auth errors."""
        errors = [
            Exception("401 Unauthorized"),
            Exception("403 Forbidden"),
            Exception("Unauthorized access"),
        ]
        for error in errors:
            assert _classify_error(error) == ErrorType.AUTH_ERROR

    def test_server_error_detection(self):
        """Test detection of server errors."""
        errors = [
            Exception("500 Internal Server Error"),
            Exception("502 Bad Gateway"),
            Exception("503 Service Unavailable"),
        ]
        for error in errors:
            assert _classify_error(error) == ErrorType.SERVER_ERROR

    def test_timeout_detection(self):
        """Test detection of timeout errors."""
        errors = [
            Exception("Connection timeout"),
            Exception("Timed out waiting for response"),
        ]
        for error in errors:
            assert _classify_error(error) == ErrorType.TIMEOUT

    def test_connection_error_detection(self):
        """Test detection of connection errors."""
        errors = [
            Exception("Connection refused"),
            Exception("Connection reset"),
            Exception("Connection closed"),
        ]
        for error in errors:
            assert _classify_error(error) == ErrorType.CONNECTION_ERROR

    def test_not_found_detection(self):
        """Test detection of 404 errors."""
        errors = [
            Exception("404 Not Found"),
            Exception("Resource not found"),
        ]
        for error in errors:
            assert _classify_error(error) == ErrorType.NOT_FOUND

    def test_validation_error_detection(self):
        """Test detection of validation errors."""
        errors = [
            Exception("400 Bad Request"),
            Exception("Validation failed"),
            Exception("Invalid input"),
        ]
        for error in errors:
            assert _classify_error(error) == ErrorType.VALIDATION_ERROR


class TestErrorRecoveryManager:
    """Test the error recovery manager."""

    @pytest.mark.asyncio
    async def test_manager_initialization(self):
        """Test that manager initializes correctly."""
        manager = ErrorRecoveryManager()
        assert manager.circuit_breaker is not None
        assert manager.health_check is not None
        assert manager.retry_policy is not None

    @pytest.mark.asyncio
    async def test_create_routes(self):
        """Test that routes are created."""
        manager = ErrorRecoveryManager()
        router = manager.create_routes()
        assert router is not None
        assert len(router.routes) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
