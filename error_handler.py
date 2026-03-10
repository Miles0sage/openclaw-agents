"""
Comprehensive Error Handling for OpenClaw
==========================================

Multi-layered error handling with:
1. Fallback chains for code generation (Kimi 2.5 → Reasoner → Opus → error)
2. Exponential backoff retry logic (1s, 2s, 4s, 8s) with max 3 retries
3. 30-second timeout handling with graceful degradation
4. Agent health tracking and automatic failover
5. Detailed error tracking and logging

Usage:
    from error_handler import (
        CodeGenerationFallback,
        execute_with_retry,
        execute_with_timeout,
        track_agent_error,
        get_error_summary
    )

    # Code generation with automatic fallback chain
    result = CodeGenerationFallback().execute(prompt)

    # Retry with exponential backoff
    response = execute_with_retry(fn, max_retries=3)

    # Timeout protection
    result = execute_with_timeout(fn, timeout_seconds=30)

    # Track agent failures
    track_agent_error("deepseek-chat", error_type="timeout")
"""

import asyncio
import logging
import time
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable, List, Tuple
from enum import Enum
from functools import wraps
import traceback

logger = logging.getLogger("openclaw_errors")


# ═══════════════════════════════════════════════════════════════════════════
# ERROR TYPES & ENUMS
# ═══════════════════════════════════════════════════════════════════════════

class ErrorType(Enum):
    """Error classification types"""
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    NETWORK = "network"
    AUTHENTICATION = "auth"
    MODEL_ERROR = "model_error"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class ModelProvider(Enum):
    """Available model providers with fallback chain"""
    KIMI_25 = "deepseek-chat"  # Kimi 2.5
    KIMI_REASONER = "deepseek-reasoner"  # Kimi Reasoner (slower, better thinking)
    CLAUDE_OPUS = "claude-opus-4-6"  # Claude Opus (most capable)
    CLAUDE_SONNET = "claude-sonnet-4-20250514"  # Claude Sonnet (balanced)
    CLAUDE_HAIKU = "claude-haiku-4-5-20251001"  # Claude Haiku (cheapest)


@dataclass
class ErrorMetrics:
    """Metrics for a specific error type"""
    error_type: ErrorType
    count: int = 0
    last_occurred_at: Optional[datetime] = None
    first_occurred_at: Optional[datetime] = None
    total_duration_ms: float = 0.0  # Total time spent retrying
    avg_retry_count: float = 0.0

    def record_error(self, retry_count: int = 0, duration_ms: float = 0.0):
        """Record a new error occurrence"""
        now = datetime.now()
        if self.first_occurred_at is None:
            self.first_occurred_at = now
        self.last_occurred_at = now
        self.count += 1
        self.total_duration_ms += duration_ms
        self.avg_retry_count = (self.avg_retry_count * (self.count - 1) + retry_count) / self.count

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "error_type": self.error_type.value,
            "count": self.count,
            "last_occurred_at": self.last_occurred_at.isoformat() if self.last_occurred_at else None,
            "first_occurred_at": self.first_occurred_at.isoformat() if self.first_occurred_at else None,
            "total_duration_ms": self.total_duration_ms,
            "avg_retry_count": round(self.avg_retry_count, 2)
        }


@dataclass
class AgentHealthStatus:
    """Health status of a remote agent/model"""
    agent_id: str
    status: str = "healthy"  # "healthy", "degraded", "unhealthy", "unreachable"
    last_check_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    consecutive_failures: int = 0
    total_failures: int = 0
    total_requests: int = 0
    error_history: List[Tuple[datetime, ErrorType]] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Success rate as percentage"""
        if self.total_requests == 0:
            return 100.0
        return 100.0 * (self.total_requests - self.total_failures) / self.total_requests

    @property
    def is_unhealthy(self) -> bool:
        """Check if agent should be marked unhealthy"""
        return self.consecutive_failures >= 3 or self.success_rate < 50.0

    def record_success(self):
        """Record successful request"""
        self.last_success_at = datetime.now()
        self.last_check_at = datetime.now()
        self.consecutive_failures = 0
        self.total_requests += 1

    def record_failure(self, error_type: ErrorType):
        """Record failed request"""
        self.last_check_at = datetime.now()
        self.consecutive_failures += 1
        self.total_failures += 1
        self.total_requests += 1
        self.error_history.append((datetime.now(), error_type))

        # Keep only last 10 errors for memory efficiency
        if len(self.error_history) > 10:
            self.error_history = self.error_history[-10:]

        # Update status
        if self.is_unhealthy:
            self.status = "unhealthy"
        elif self.consecutive_failures >= 1:
            self.status = "degraded"
        else:
            self.status = "healthy"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "agent_id": self.agent_id,
            "status": self.status,
            "last_check_at": self.last_check_at.isoformat() if self.last_check_at else None,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "consecutive_failures": self.consecutive_failures,
            "total_failures": self.total_failures,
            "total_requests": self.total_requests,
            "success_rate": round(self.success_rate, 2),
            "is_unhealthy": self.is_unhealthy
        }


# ═══════════════════════════════════════════════════════════════════════════
# RETRY LOGIC
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class RetryConfig:
    """Configuration for exponential backoff retry"""
    max_retries: int = 3
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 8.0
    backoff_multiplier: float = 2.0
    jitter: bool = True  # Add random jitter to avoid thundering herd


def calculate_backoff_delay(
    retry_count: int,
    config: RetryConfig
) -> float:
    """
    Calculate exponential backoff delay with optional jitter

    Args:
        retry_count: Current retry attempt (0-indexed)
        config: Retry configuration

    Returns:
        Delay in seconds (1, 2, 4, or 8 for standard config)
    """
    if retry_count == 0:
        return 0.0

    # Exponential backoff: initial_delay * (multiplier ^ (retry_count - 1))
    delay = config.initial_delay_seconds * (config.backoff_multiplier ** (retry_count - 1))
    delay = min(delay, config.max_delay_seconds)

    # Add jitter (±10%)
    if config.jitter:
        import random
        jitter = delay * 0.1 * (2 * random.random() - 1)
        delay = max(0.1, delay + jitter)

    return delay


def execute_with_retry(
    fn: Callable,
    *args,
    max_retries: int = 3,
    config: Optional[RetryConfig] = None,
    on_retry: Optional[Callable] = None,
    **kwargs
) -> Any:
    """
    Execute function with exponential backoff retry logic

    Args:
        fn: Function to execute
        max_retries: Maximum retry attempts (default 3)
        config: RetryConfig (uses defaults if None)
        on_retry: Optional callback(retry_count, delay, error) on retry
        *args, **kwargs: Arguments to pass to fn

    Returns:
        Result from successful fn call

    Raises:
        Exception: Original exception if all retries exhausted
    """
    if config is None:
        config = RetryConfig(max_retries=max_retries)
    else:
        config.max_retries = max_retries

    last_exception = None
    retry_times = []

    for attempt in range(config.max_retries + 1):
        try:
            result = fn(*args, **kwargs)
            return result
        except Exception as e:
            last_exception = e
            error_type = classify_error(e)

            if attempt < config.max_retries:
                delay = calculate_backoff_delay(attempt, config)
                retry_times.append(delay)

                msg = f"Retry {attempt + 1}/{config.max_retries}: {type(e).__name__}: {str(e)[:60]}... (waiting {delay:.1f}s)"
                logger.warning(msg)

                if on_retry:
                    on_retry(attempt + 1, delay, e)

                time.sleep(delay)
            else:
                msg = f"All retries exhausted after {config.max_retries} attempts"
                logger.error(msg)

    # All retries failed
    raise last_exception


async def execute_with_retry_async(
    fn: Callable,
    *args,
    max_retries: int = 3,
    config: Optional[RetryConfig] = None,
    on_retry: Optional[Callable] = None,
    **kwargs
) -> Any:
    """
    Execute async function with exponential backoff retry logic

    Args:
        fn: Async function to execute
        max_retries: Maximum retry attempts (default 3)
        config: RetryConfig (uses defaults if None)
        on_retry: Optional async callback(retry_count, delay, error)
        *args, **kwargs: Arguments to pass to fn

    Returns:
        Result from successful fn call

    Raises:
        Exception: Original exception if all retries exhausted
    """
    if config is None:
        config = RetryConfig(max_retries=max_retries)
    else:
        config.max_retries = max_retries

    last_exception = None

    for attempt in range(config.max_retries + 1):
        try:
            result = await fn(*args, **kwargs)
            return result
        except Exception as e:
            last_exception = e
            error_type = classify_error(e)

            if attempt < config.max_retries:
                delay = calculate_backoff_delay(attempt, config)

                msg = f"Async retry {attempt + 1}/{config.max_retries}: {type(e).__name__}: {str(e)[:60]}... (waiting {delay:.1f}s)"
                logger.warning(msg)

                if on_retry:
                    await on_retry(attempt + 1, delay, e)

                await asyncio.sleep(delay)
            else:
                msg = f"Async retries exhausted after {config.max_retries} attempts"
                logger.error(msg)

    raise last_exception


# ═══════════════════════════════════════════════════════════════════════════
# TIMEOUT HANDLING
# ═══════════════════════════════════════════════════════════════════════════

class TimeoutException(Exception):
    """Custom timeout exception"""
    pass


def execute_with_timeout(
    fn: Callable,
    timeout_seconds: float = 30.0,
    *args,
    on_timeout: Optional[Callable] = None,
    **kwargs
) -> Any:
    """
    Execute function with timeout (synchronous)

    Args:
        fn: Function to execute
        timeout_seconds: Timeout in seconds (default 30)
        on_timeout: Optional callback() when timeout occurs
        *args, **kwargs: Arguments to pass to fn

    Returns:
        Result from fn if completed within timeout

    Raises:
        TimeoutException: If function exceeds timeout
    """
    import signal

    def timeout_handler(signum, frame):
        if on_timeout:
            on_timeout()
        raise TimeoutException(f"Function timed out after {timeout_seconds}s")

    # Set signal handler (Unix only)
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(int(timeout_seconds) + 1)

    try:
        result = fn(*args, **kwargs)
        signal.alarm(0)  # Cancel alarm
        return result
    except TimeoutException:
        logger.error(f"Function exceeded {timeout_seconds}s timeout")
        raise
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


async def execute_with_timeout_async(
    fn: Callable,
    timeout_seconds: float = 30.0,
    *args,
    on_timeout: Optional[Callable] = None,
    **kwargs
) -> Any:
    """
    Execute async function with timeout

    Args:
        fn: Async function to execute
        timeout_seconds: Timeout in seconds (default 30)
        on_timeout: Optional async callback() when timeout occurs
        *args, **kwargs: Arguments to pass to fn

    Returns:
        Result from fn if completed within timeout

    Raises:
        TimeoutException: If function exceeds timeout
    """
    try:
        result = await asyncio.wait_for(
            fn(*args, **kwargs),
            timeout=timeout_seconds
        )
        return result
    except asyncio.TimeoutError:
        if on_timeout:
            if asyncio.iscoroutinefunction(on_timeout):
                await on_timeout()
            else:
                on_timeout()
        msg = f"Async function exceeded {timeout_seconds}s timeout"
        logger.error(msg)
        raise TimeoutException(msg)


# ═══════════════════════════════════════════════════════════════════════════
# ERROR CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════════

def classify_error(exception: Exception) -> ErrorType:
    """
    Classify exception into error type category

    Args:
        exception: Exception to classify

    Returns:
        ErrorType enum value
    """
    error_str = str(exception).lower()
    error_type_name = type(exception).__name__.lower()

    # Timeout errors
    if "timeout" in error_str or "timed out" in error_str:
        return ErrorType.TIMEOUT
    if isinstance(exception, (asyncio.TimeoutError, TimeoutException)):
        return ErrorType.TIMEOUT

    # Rate limit errors
    if "429" in error_str or "rate limit" in error_str or "too many requests" in error_str:
        return ErrorType.RATE_LIMIT

    # Network errors
    if any(x in error_type_name for x in ["connection", "network", "refused"]):
        return ErrorType.NETWORK
    if any(x in error_str for x in ["connection refused", "connection reset", "no route"]):
        return ErrorType.NETWORK

    # Authentication errors
    if "401" in error_str or "unauthorized" in error_str or "authentication" in error_str:
        return ErrorType.AUTHENTICATION
    if "403" in error_str or "forbidden" in error_str:
        return ErrorType.AUTHENTICATION

    # Model errors
    if any(x in error_str for x in ["model not found", "invalid model", "model error"]):
        return ErrorType.MODEL_ERROR

    # Internal errors
    if "500" in error_str or "internal" in error_str:
        return ErrorType.INTERNAL

    return ErrorType.UNKNOWN


# ═══════════════════════════════════════════════════════════════════════════
# FALLBACK CHAIN FOR CODE GENERATION
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class CodeGenerationResult:
    """Result from code generation with fallback info"""
    code: str
    model_used: str
    attempt_number: int
    total_attempts: int
    errors_encountered: List[Dict[str, Any]] = field(default_factory=list)
    duration_ms: float = 0.0
    success: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "code": self.code,
            "model_used": self.model_used,
            "attempt_number": self.attempt_number,
            "total_attempts": self.total_attempts,
            "errors_encountered": len(self.errors_encountered),
            "duration_ms": round(self.duration_ms, 2),
            "success": self.success
        }


class CodeGenerationFallback:
    """
    Code generation with automatic fallback chain:
    1. Kimi 2.5 (deepseek-chat) - fastest, good quality
    2. Kimi Reasoner (deepseek-reasoner) - slower, better reasoning
    3. Claude Opus (claude-opus-4-6) - most capable, most expensive
    4. Claude Sonnet (claude-sonnet-4-20250514) - balanced
    5. Return error message if all fail
    """

    # Fallback chain order (best→worst)
    FALLBACK_CHAIN = [
        ModelProvider.KIMI_25,
        ModelProvider.KIMI_REASONER,
        ModelProvider.CLAUDE_OPUS,
        ModelProvider.CLAUDE_SONNET,
    ]

    def __init__(self, model_clients: Dict[str, Any] = None):
        """
        Initialize code generation with optional model clients

        Args:
            model_clients: Dict of {model_name: client_instance}
        """
        self.model_clients = model_clients or {}
        self.errors: List[Dict[str, Any]] = []

    def execute(
        self,
        prompt: str,
        timeout_seconds: float = 30.0,
        max_retries_per_model: int = 2
    ) -> CodeGenerationResult:
        """
        Execute code generation with fallback chain

        Args:
            prompt: Code generation prompt
            timeout_seconds: Max time per attempt (default 30s)
            max_retries_per_model: Retries per model in chain

        Returns:
            CodeGenerationResult with code or error message
        """
        start_time = time.time()
        self.errors = []

        for attempt_idx, model_provider in enumerate(self.FALLBACK_CHAIN, 1):
            model_name = model_provider.value
            logger.info(f"🔄 Code generation attempt {attempt_idx}/{len(self.FALLBACK_CHAIN)}: {model_name}")

            try:
                # Try model with retries and timeout
                code = self._call_model_with_retry(
                    model_name,
                    prompt,
                    timeout_seconds=timeout_seconds,
                    max_retries=max_retries_per_model
                )

                duration_ms = (time.time() - start_time) * 1000
                logger.info(f"✅ Code generation succeeded with {model_name} in {duration_ms:.0f}ms")

                return CodeGenerationResult(
                    code=code,
                    model_used=model_name,
                    attempt_number=attempt_idx,
                    total_attempts=len(self.FALLBACK_CHAIN),
                    errors_encountered=self.errors[:attempt_idx - 1],
                    duration_ms=duration_ms,
                    success=True
                )

            except Exception as e:
                error_info = {
                    "model": model_name,
                    "attempt": attempt_idx,
                    "error": str(e),
                    "error_type": classify_error(e).value,
                    "timestamp": datetime.now().isoformat()
                }
                self.errors.append(error_info)
                logger.warning(f"⚠️  Model {model_name} failed: {error_info['error_type']}: {str(e)[:60]}...")

        # All models exhausted
        duration_ms = (time.time() - start_time) * 1000
        error_msg = self._format_error_message()

        logger.error(f"❌ Code generation failed after all {len(self.FALLBACK_CHAIN)} fallbacks")

        return CodeGenerationResult(
            code=error_msg,
            model_used="none",
            attempt_number=len(self.FALLBACK_CHAIN),
            total_attempts=len(self.FALLBACK_CHAIN),
            errors_encountered=self.errors,
            duration_ms=duration_ms,
            success=False
        )

    def _call_model_with_retry(
        self,
        model_name: str,
        prompt: str,
        timeout_seconds: float = 30.0,
        max_retries: int = 2
    ) -> str:
        """
        Call model with retry and timeout

        Args:
            model_name: Model identifier
            prompt: Input prompt
            timeout_seconds: Timeout per attempt
            max_retries: Max retries

        Returns:
            Generated code

        Raises:
            Exception: If model unavailable or all retries exhausted
        """
        if model_name not in self.model_clients:
            raise RuntimeError(f"Model client not available: {model_name}")

        client = self.model_clients[model_name]

        def call_fn():
            return execute_with_timeout(
                lambda: client.generate(prompt),
                timeout_seconds=timeout_seconds
            )

        return execute_with_retry(
            call_fn,
            max_retries=max_retries
        )

    def _format_error_message(self) -> str:
        """Format comprehensive error message"""
        lines = [
            "ERROR: Code generation failed after all fallback chains exhausted",
            f"Total attempts: {len(self.errors)}",
            "",
            "Attempted models:"
        ]

        error_by_model = {}
        for error in self.errors:
            model = error["model"]
            if model not in error_by_model:
                error_by_model[model] = []
            error_by_model[model].append(error)

        for model, errors in error_by_model.items():
            error_types = set(e["error_type"] for e in errors)
            last_error = errors[-1]["error"]
            lines.append(f"  - {model}: {', '.join(error_types)}")
            lines.append(f"    Last error: {last_error[:80]}...")

        lines.extend([
            "",
            "Action: Check API keys, network connectivity, and model availability",
            "Time: " + datetime.now().isoformat()
        ])

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# AGENT HEALTH TRACKING
# ═══════════════════════════════════════════════════════════════════════════

class AgentHealthTracker:
    """Track and manage health of remote agents/models"""

    def __init__(self):
        """Initialize health tracker"""
        self.agents: Dict[str, AgentHealthStatus] = {}
        self.error_metrics: Dict[ErrorType, ErrorMetrics] = {
            error_type: ErrorMetrics(error_type=error_type)
            for error_type in ErrorType
        }

    def register_agent(self, agent_id: str) -> AgentHealthStatus:
        """Register a new agent"""
        if agent_id not in self.agents:
            self.agents[agent_id] = AgentHealthStatus(agent_id=agent_id)
            logger.info(f"📋 Registered agent: {agent_id}")
        return self.agents[agent_id]

    def record_agent_success(self, agent_id: str):
        """Record successful agent request"""
        agent = self.register_agent(agent_id)
        agent.record_success()
        logger.debug(f"✅ Agent {agent_id}: success (rate: {agent.success_rate:.1f}%)")

    def record_agent_failure(self, agent_id: str, error: Exception):
        """Record failed agent request"""
        agent = self.register_agent(agent_id)
        error_type = classify_error(error)
        agent.record_failure(error_type)

        # Update error metrics
        self.error_metrics[error_type].record_error()

        logger.warning(
            f"❌ Agent {agent_id}: {error_type.value} (failures: {agent.consecutive_failures})"
        )

    def is_agent_healthy(self, agent_id: str) -> bool:
        """Check if agent is healthy"""
        agent = self.agents.get(agent_id)
        if not agent:
            return True  # Unknown agent assumed healthy
        return agent.status == "healthy"

    def is_agent_unreachable(self, agent_id: str) -> bool:
        """Check if agent is unreachable (too many failures)"""
        agent = self.agents.get(agent_id)
        if not agent:
            return False
        return agent.status == "unreachable" or agent.consecutive_failures >= 5

    def get_healthy_agents(self, agent_ids: List[str]) -> List[str]:
        """Filter list of agents to only healthy ones"""
        return [
            agent_id for agent_id in agent_ids
            if self.is_agent_healthy(agent_id)
        ]

    def get_agent_status(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get agent status"""
        agent = self.agents.get(agent_id)
        return agent.to_dict() if agent else None

    def get_all_agent_statuses(self) -> Dict[str, Dict[str, Any]]:
        """Get all agent statuses"""
        return {
            agent_id: agent.to_dict()
            for agent_id, agent in self.agents.items()
        }

    def get_error_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get error metrics"""
        return {
            error_type.value: metrics.to_dict()
            for error_type, metrics in self.error_metrics.items()
        }

    def get_summary(self) -> Dict[str, Any]:
        """Get health tracker summary"""
        return {
            "total_agents": len(self.agents),
            "healthy_agents": sum(1 for a in self.agents.values() if a.status == "healthy"),
            "degraded_agents": sum(1 for a in self.agents.values() if a.status == "degraded"),
            "unhealthy_agents": sum(1 for a in self.agents.values() if a.status == "unhealthy"),
            "unreachable_agents": sum(1 for a in self.agents.values() if a.status == "unreachable"),
            "total_requests": sum(a.total_requests for a in self.agents.values()),
            "total_failures": sum(a.total_failures for a in self.agents.values()),
            "error_metrics": {
                error_type.value: metrics.count
                for error_type, metrics in self.error_metrics.items()
                if metrics.count > 0
            }
        }


# ═══════════════════════════════════════════════════════════════════════════
# GLOBAL SINGLETON INSTANCES
# ═══════════════════════════════════════════════════════════════════════════

_health_tracker: Optional[AgentHealthTracker] = None


def get_health_tracker() -> AgentHealthTracker:
    """Get or create global health tracker"""
    global _health_tracker
    if _health_tracker is None:
        _health_tracker = AgentHealthTracker()
    return _health_tracker


def track_agent_success(agent_id: str):
    """Track successful agent request"""
    get_health_tracker().record_agent_success(agent_id)


def track_agent_error(agent_id: str, error: Exception):
    """Track failed agent request"""
    get_health_tracker().record_agent_failure(agent_id, error)


def get_error_summary() -> Dict[str, Any]:
    """Get comprehensive error summary"""
    tracker = get_health_tracker()
    return {
        "health_summary": tracker.get_summary(),
        "agent_statuses": tracker.get_all_agent_statuses(),
        "error_metrics": tracker.get_error_metrics(),
        "timestamp": datetime.now().isoformat()
    }


# ═══════════════════════════════════════════════════════════════════════════
# VPS AGENT FAILOVER
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class VPSAgentConfig:
    """Configuration for VPS agent failover"""
    vps_endpoint: str = "http://localhost:8000"
    cloudflare_endpoint: str = "http://localhost:18789"
    health_check_timeout: float = 5.0
    fallback_to_cloudflare: bool = True


class VPSAgentFailover:
    """Handle VPS agent failures with automatic Cloudflare fallback"""

    def __init__(self, config: VPSAgentConfig = None):
        """Initialize VPS failover"""
        self.config = config or VPSAgentConfig()
        self.vps_healthy = True
        self.last_vps_check = datetime.now()

    async def check_vps_health(self) -> bool:
        """Check if VPS agent is reachable"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=self.config.health_check_timeout) as client:
                response = await client.get(f"{self.config.vps_endpoint}/health")
                self.vps_healthy = response.status_code == 200
                self.last_vps_check = datetime.now()
                logger.info(f"🏥 VPS health check: {'✅ healthy' if self.vps_healthy else '❌ unhealthy'}")
                return self.vps_healthy
        except Exception as e:
            self.vps_healthy = False
            self.last_vps_check = datetime.now()
            logger.warning(f"🏥 VPS health check failed: {str(e)[:60]}...")
            return False

    async def execute_with_fallback(
        self,
        fn: Callable,
        *args,
        agent_id: str = "vps_agent",
        **kwargs
    ) -> Any:
        """
        Execute function with VPS fallback to Cloudflare

        Args:
            fn: Async function to execute
            agent_id: Agent identifier for tracking
            *args, **kwargs: Arguments to pass to fn

        Returns:
            Result from successful execution

        Raises:
            Exception: If both VPS and Cloudflare fail
        """
        # Check VPS health if not checked recently
        if (datetime.now() - self.last_vps_check).total_seconds() > 60:
            await self.check_vps_health()

        if self.vps_healthy:
            try:
                logger.info(f"📡 Attempting VPS agent: {agent_id}")
                result = await execute_with_timeout_async(
                    fn, timeout_seconds=30.0, *args, **kwargs
                )
                track_agent_success(agent_id)
                return result
            except Exception as e:
                logger.error(f"⚠️  VPS agent failed: {classify_error(e).value}")
                track_agent_error(agent_id, e)
                self.vps_healthy = False

        # Fallback to Cloudflare
        if self.config.fallback_to_cloudflare:
            logger.info(f"🌐 Falling back to Cloudflare gateway (VPS unavailable)")
            track_agent_error(agent_id, Exception("VPS unreachable, using Cloudflare fallback"))
            # In production, this would call the Cloudflare gateway
            # For now, return error message
            return {
                "error": "VPS agent unreachable, Cloudflare fallback would be used",
                "fallback_endpoint": self.config.cloudflare_endpoint
            }

        raise Exception(f"Both VPS and Cloudflare unavailable for {agent_id}")

    def get_status(self) -> Dict[str, Any]:
        """Get current failover status"""
        return {
            "vps_healthy": self.vps_healthy,
            "last_vps_check": self.last_vps_check.isoformat(),
            "fallback_enabled": self.config.fallback_to_cloudflare,
            "vps_endpoint": self.config.vps_endpoint,
            "cloudflare_endpoint": self.config.cloudflare_endpoint
        }
