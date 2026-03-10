"""Tests for error classification and recovery logic."""

import pytest
from autonomous_runner import (
    _classify_error,
    _get_error_config,
    ERROR_CATEGORIES,
    TRANSIENT_ERROR_PATTERNS,
    PERMANENT_ERROR_PATTERNS,
)


class TestClassifyError:
    """Test the 6-category error classification system."""

    def test_network_errors(self):
        assert _classify_error("rate limit exceeded") == "network"
        assert _classify_error("429 Too Many Requests") == "network"
        assert _classify_error("Connection reset by peer") == "network"
        assert _classify_error("Request timed out after 30s") == "network"
        assert _classify_error("503 Service Unavailable") == "network"
        assert _classify_error("SSL Error during handshake") == "network"

    def test_auth_errors(self):
        assert _classify_error("401 Unauthorized") == "auth"
        assert _classify_error("403 Forbidden") == "auth"
        assert _classify_error("Invalid API key provided") == "auth"
        assert _classify_error("Expired token received") == "auth"
        assert _classify_error("Access denied for resource") == "auth"

    def test_not_found_errors(self):
        assert _classify_error("FileNotFoundError: /tmp/missing.py") == "not_found"
        assert _classify_error("No such file or directory") == "not_found"
        assert _classify_error("404 Not Found") == "not_found"

    def test_code_errors(self):
        assert _classify_error("SyntaxError: invalid syntax") == "code_error"
        assert _classify_error("ImportError: No module named 'foo'") == "code_error"
        assert _classify_error("NameError: name 'x' is not defined") == "code_error"
        assert _classify_error("TypeError: 'int' object is not callable") == "code_error"
        assert _classify_error("AttributeError: has no attribute 'bar'") == "code_error"
        assert _classify_error("KeyError: 'missing_key'") == "code_error"

    def test_permission_errors(self):
        assert _classify_error("PermissionError: [Errno 13]") == "permission"
        assert _classify_error("Permission denied") == "permission"
        assert _classify_error("Read-only file system") == "permission"

    def test_resource_errors(self):
        assert _classify_error("Out of memory") == "resource"
        assert _classify_error("No space left on device") == "resource"
        assert _classify_error("Disk full") == "resource"

    def test_unknown_errors(self):
        assert _classify_error("Something completely unexpected happened") == "unknown"
        assert _classify_error("") == "unknown"

    def test_case_insensitive(self):
        assert _classify_error("RATE LIMIT EXCEEDED") == "network"
        assert _classify_error("UNAUTHORIZED") == "auth"

    def test_priority_ordering(self):
        # Auth takes priority over network (both could match "forbidden")
        assert _classify_error("403 forbidden") == "auth"


class TestErrorConfig:
    """Test error recovery configuration."""

    def test_known_categories(self):
        for cat in ["network", "auth", "not_found", "code_error", "permission", "resource"]:
            config = _get_error_config(cat)
            assert "max_retries" in config
            assert "backoff" in config
            assert "action" in config

    def test_unknown_category_defaults(self):
        config = _get_error_config("nonexistent")
        assert config["max_retries"] == 2
        assert config["action"] == "diagnose_and_rewrite"

    def test_auth_no_retry(self):
        config = _get_error_config("auth")
        assert config["max_retries"] == 0
        assert config["action"] == "escalate"

    def test_network_retries(self):
        config = _get_error_config("network")
        assert config["max_retries"] == 3
        assert config["backoff"] == "exponential"

    def test_permission_skip(self):
        config = _get_error_config("permission")
        assert config["max_retries"] == 0
        assert config["action"] == "skip"


class TestErrorPatterns:
    """Test backward-compat pattern lists."""

    def test_transient_patterns_are_network(self):
        assert TRANSIENT_ERROR_PATTERNS == ERROR_CATEGORIES["network"]["patterns"]

    def test_permanent_patterns_are_auth_plus_permission(self):
        expected = ERROR_CATEGORIES["auth"]["patterns"] + ERROR_CATEGORIES["permission"]["patterns"]
        assert PERMANENT_ERROR_PATTERNS == expected
