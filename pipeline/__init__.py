"""
OpenClaw Pipeline Package
=========================
Modular components extracted from the monolithic autonomous_runner.py.
Each module is self-contained with minimal cross-dependencies.

Modules:
    models      - Data classes (Phase, PlanStep, ExecutionPlan, JobProgress)
    errors      - Error classification, diagnosis, loop detection
    guardrails  - Job safety limits (cost, iterations, circuit breaker, kill flags)
    context     - Context building, worktree management, project loading
"""

from pipeline.models import Phase, PlanStep, ExecutionPlan, JobProgress
from pipeline.errors import (
    classify_error,
    get_error_config,
    make_call_signature,
    check_loop,
    ERROR_CATEGORIES,
    TRANSIENT_ERROR_PATTERNS,
    PERMANENT_ERROR_PATTERNS,
)
from pipeline.guardrails import (
    JobGuardrails,
    GuardrailViolation,
    BudgetExceededError,
    CreditExhaustedError,
    CancelledError,
    load_kill_flags,
    set_kill_flag,
    clear_kill_flag,
)

__all__ = [
    # Models
    "Phase", "PlanStep", "ExecutionPlan", "JobProgress",
    # Errors
    "classify_error", "get_error_config", "make_call_signature", "check_loop",
    "ERROR_CATEGORIES", "TRANSIENT_ERROR_PATTERNS", "PERMANENT_ERROR_PATTERNS",
    # Guardrails
    "JobGuardrails", "GuardrailViolation", "BudgetExceededError",
    "CreditExhaustedError", "CancelledError",
    "load_kill_flags", "set_kill_flag", "clear_kill_flag",
]
