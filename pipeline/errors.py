"""
Error classification and recovery logic for the OpenClaw pipeline.

6-category system inspired by Devin MCP HTTP matrix:
  network, auth, not_found, code_error, permission, resource
"""

import hashlib
import logging

logger = logging.getLogger("autonomous_runner")

# ---------------------------------------------------------------------------
# 6-Category Error Classification
# Each category has: max_retries, backoff_strategy, recovery_action
# ---------------------------------------------------------------------------

ERROR_CATEGORIES = {
    "network": {
        "max_retries": 3, "backoff": "exponential", "action": "retry_same",
        "patterns": [
            "rate limit", "rate_limit", "429", "too many requests",
            "timeout", "timed out", "deadline exceeded",
            "connection reset", "connection refused", "connection error",
            "temporary failure", "service unavailable", "503",
            "internal server error", "500",
            "network error", "dns resolution",
            "overloaded", "capacity", "try again",
            "econnrefused", "econnreset", "etimedout",
            "ssl error", "handshake", "502", "504",
        ],
    },
    "auth": {
        "max_retries": 0, "backoff": "none", "action": "escalate",
        "patterns": [
            "authentication", "unauthorized", "401", "403",
            "forbidden", "invalid api key", "invalid token",
            "expired token", "access denied",
        ],
    },
    "not_found": {
        "max_retries": 1, "backoff": "none", "action": "diagnose_and_rewrite",
        "patterns": [
            "file not found", "no such file", "filenotfounderror",
            "not found", "404", "does not exist",
            "no such directory", "path not found",
        ],
    },
    "code_error": {
        "max_retries": 2, "backoff": "fixed", "action": "diagnose_and_rewrite",
        "patterns": [
            "syntax error", "syntaxerror", "invalid syntax",
            "import error", "importerror", "modulenotfounderror",
            "name error", "nameerror", "is not defined",
            "type error", "typeerror", "not callable",
            "attribute error", "attributeerror", "has no attribute",
            "value error", "valueerror",
            "key error", "keyerror",
            "index error", "indexerror",
        ],
    },
    "permission": {
        "max_retries": 0, "backoff": "none", "action": "skip",
        "patterns": [
            "permission denied", "permissionerror",
            "read-only file system", "operation not permitted",
        ],
    },
    "resource": {
        "max_retries": 1, "backoff": "exponential", "action": "retry_same",
        "patterns": [
            "out of memory", "oom", "memory error",
            "disk full", "no space left", "quota exceeded",
        ],
    },
}

# Flatten for backward compat
TRANSIENT_ERROR_PATTERNS = ERROR_CATEGORIES["network"]["patterns"]
PERMANENT_ERROR_PATTERNS = (
    ERROR_CATEGORIES["auth"]["patterns"]
    + ERROR_CATEGORIES["permission"]["patterns"]
)

# Loop detection threshold
LOOP_DETECT_THRESHOLD = 3


def classify_error(error_str: str) -> str:
    """Classify an error into one of 6 categories.

    Returns a category key from ERROR_CATEGORIES, or 'unknown'.
    """
    err_lower = error_str.lower()
    for category in ["auth", "permission", "resource", "network", "not_found", "code_error"]:
        cat = ERROR_CATEGORIES[category]
        for pattern in cat["patterns"]:
            if pattern in err_lower:
                return category
    return "unknown"


def get_error_config(error_class: str) -> dict:
    """Get retry/recovery config for an error category."""
    return ERROR_CATEGORIES.get(error_class, {
        "max_retries": 2, "backoff": "fixed", "action": "diagnose_and_rewrite",
    })


def make_call_signature(tool_name: str, tool_input) -> str:
    """Create a deterministic signature for loop detection."""
    if isinstance(tool_input, dict):
        input_str = str(sorted(tool_input.items()))
    else:
        input_str = str(tool_input)
    input_hash = hashlib.md5(input_str.encode()).hexdigest()[:12]
    return f"{tool_name}:{input_hash}"


def check_loop(call_sig: str, counts: dict, job_id: str, phase: str) -> bool:
    """Check if a tool call has been repeated too many times.

    Returns True if loop detected (caller should break).
    """
    counts[call_sig] = counts.get(call_sig, 0) + 1
    if counts[call_sig] >= LOOP_DETECT_THRESHOLD:
        tool_name = call_sig.split(":")[0]
        logger.warning(
            f"Loop detected for {job_id}/{phase}: {tool_name} called {counts[call_sig]}x with same args"
        )
        return True
    return False
