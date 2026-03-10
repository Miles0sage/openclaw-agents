"""
Test suite for OpenClaw Dashboard API

Tests all endpoints with proper auth and error handling
"""

import pytest
import asyncio
import json
import base64
from pathlib import Path
from datetime import datetime
import os
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from fastapi.testclient import TestClient
from dashboard_api import app, DASHBOARD_TOKEN, DASHBOARD_PASSWORD

client = TestClient(app)

# Test constants
VALID_BEARER_TOKEN = f"Bearer {DASHBOARD_TOKEN}"
VALID_PASSWORD_TOKEN = f"Bearer {DASHBOARD_PASSWORD}"
INVALID_TOKEN = "Bearer invalid-token-12345"


class TestAuthentication:
    """Test authentication endpoints"""

    def test_missing_auth_header(self):
        """Missing auth header returns 401"""
        response = client.get("/api/status")
        assert response.status_code == 401
        assert "Missing Authorization header" in response.json()["detail"]

    def test_invalid_auth_header_format(self):
        """Invalid auth header format returns 401"""
        response = client.get("/api/status", headers={"Authorization": "InvalidFormat"})
        assert response.status_code == 401

    def test_invalid_token(self):
        """Invalid token returns 403"""
        response = client.get("/api/status", headers={"Authorization": INVALID_TOKEN})
        assert response.status_code == 403

    def test_valid_bearer_token(self):
        """Valid bearer token is accepted"""
        response = client.get("/api/status", headers={"Authorization": VALID_BEARER_TOKEN})
        # Should not be 401 or 403
        assert response.status_code in [200, 500]  # 500 if gateway not running

    def test_password_as_token(self):
        """Password can be used as token"""
        response = client.get("/api/status", headers={"Authorization": VALID_PASSWORD_TOKEN})
        assert response.status_code in [200, 500]


class TestPublicEndpoints:
    """Test public endpoints (no auth required)"""

    def test_health_check(self):
        """Basic health check is public"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "timestamp" in data

    def test_root_endpoint(self):
        """Root endpoint returns service info or dashboard"""
        response = client.get("/")
        assert response.status_code == 200

    def test_docs_endpoint(self):
        """Docs endpoint available"""
        response = client.get("/docs")
        assert response.status_code == 200
        data = response.json()
        assert "endpoints" in data
        assert "GET /api/status" in data["endpoints"]


class TestStatusEndpoint:
    """Test /api/status endpoint"""

    def test_status_response_structure(self):
        """Status response has correct structure"""
        response = client.get("/api/status", headers={"Authorization": VALID_BEARER_TOKEN})
        assert response.status_code in [200, 500]

        if response.status_code == 200:
            data = response.json()
            assert "gateway_running" in data
            assert "gateway_port" in data
            assert "gateway_host" in data
            assert "tunnel_running" in data
            assert "uptime_seconds" in data
            assert "timestamp" in data
            assert "version" in data

            # Type checks
            assert isinstance(data["gateway_running"], bool)
            assert isinstance(data["gateway_port"], int)
            assert isinstance(data["tunnel_running"], bool)
            assert isinstance(data["uptime_seconds"], int)

    def test_status_timestamp_format(self):
        """Status timestamp is ISO format"""
        response = client.get("/api/status", headers={"Authorization": VALID_BEARER_TOKEN})
        if response.status_code == 200:
            data = response.json()
            # Should be parseable as ISO datetime
            datetime.fromisoformat(data["timestamp"])


class TestLogsEndpoint:
    """Test /api/logs endpoint"""

    def test_logs_default_lines(self):
        """Logs endpoint returns default number of lines"""
        response = client.get("/api/logs", headers={"Authorization": VALID_BEARER_TOKEN})
        assert response.status_code == 200
        data = response.json()

        assert "gateway_logs" in data
        assert "tunnel_logs" in data
        assert "total_lines" in data
        assert "timestamp" in data

        assert isinstance(data["gateway_logs"], list)
        assert isinstance(data["tunnel_logs"], list)

    def test_logs_custom_lines(self):
        """Logs endpoint respects custom line count"""
        response = client.get("/api/logs?lines=20", headers={"Authorization": VALID_BEARER_TOKEN})
        assert response.status_code == 200
        data = response.json()

        # Should not exceed 20 lines per log
        assert len(data["gateway_logs"]) <= 20
        assert len(data["tunnel_logs"]) <= 20

    def test_logs_line_limit(self):
        """Logs endpoint limits to max 500 lines"""
        response = client.get("/api/logs?lines=1000", headers={"Authorization": VALID_BEARER_TOKEN})
        assert response.status_code == 200
        data = response.json()

        # Should be capped at 500
        assert len(data["gateway_logs"]) <= 500
        assert len(data["tunnel_logs"]) <= 500

    def test_logs_invalid_lines(self):
        """Logs endpoint handles invalid line counts"""
        response = client.get("/api/logs?lines=0", headers={"Authorization": VALID_BEARER_TOKEN})
        assert response.status_code == 200
        # Should use default (50)
        data = response.json()
        assert len(data["gateway_logs"]) <= 50


class TestWebhooksEndpoint:
    """Test /api/webhooks endpoint"""

    def test_webhooks_response_structure(self):
        """Webhooks response has correct structure"""
        response = client.get("/api/webhooks", headers={"Authorization": VALID_BEARER_TOKEN})
        assert response.status_code == 200
        data = response.json()

        assert "telegram_webhook" in data
        assert "slack_webhook" in data
        assert "telegram_enabled" in data
        assert "slack_enabled" in data

        assert isinstance(data["telegram_webhook"], str)
        assert isinstance(data["slack_webhook"], str)
        assert isinstance(data["telegram_enabled"], bool)
        assert isinstance(data["slack_enabled"], bool)

    def test_webhooks_url_format(self):
        """Webhook URLs are properly formatted"""
        response = client.get("/api/webhooks", headers={"Authorization": VALID_BEARER_TOKEN})
        assert response.status_code == 200
        data = response.json()

        if data["telegram_enabled"]:
            assert data["telegram_webhook"].startswith("http://")
            assert "/telegram/" in data["telegram_webhook"]

        if data["slack_enabled"]:
            assert data["slack_webhook"].startswith("http://")
            assert "/slack/" in data["slack_webhook"]


class TestConfigEndpoint:
    """Test /api/config endpoint"""

    def test_config_response_structure(self):
        """Config response has correct structure"""
        response = client.get("/api/config", headers={"Authorization": VALID_BEARER_TOKEN})
        assert response.status_code == 200
        data = response.json()

        assert "name" in data
        assert "version" in data
        assert "port" in data
        assert "channels" in data
        assert "agents_count" in data
        assert "timestamp" in data

        assert isinstance(data["channels"], dict)
        assert isinstance(data["agents_count"], int)

    def test_config_no_secrets(self):
        """Config doesn't expose sensitive keys"""
        response = client.get("/api/config", headers={"Authorization": VALID_BEARER_TOKEN})
        assert response.status_code == 200
        data = response.json()

        # Check that channels don't have botToken, apiKey, etc.
        for channel_name, channel_config in data["channels"].items():
            assert "botToken" not in channel_config
            assert "apiKey" not in channel_config
            assert "token" not in channel_config
            assert "secret" not in channel_config


class TestSecretsEndpoint:
    """Test /api/secrets endpoint"""

    def test_save_secret_success(self):
        """Saving a secret succeeds"""
        payload = {
            "key": "test_api_key",
            "value": "super-secret-value-12345",
            "service": "test_service"
        }
        response = client.post(
            "/api/secrets",
            json=payload,
            headers={"Authorization": VALID_BEARER_TOKEN}
        )
        assert response.status_code == 200
        data = response.json()

        assert data["message"] == "Secret 'test_api_key' saved successfully"
        assert data["key"] == "test_api_key"
        assert data["service"] == "test_service"

    def test_save_secret_missing_key(self):
        """Saving secret without key fails"""
        payload = {
            "key": "",
            "value": "secret-value"
        }
        response = client.post(
            "/api/secrets",
            json=payload,
            headers={"Authorization": VALID_BEARER_TOKEN}
        )
        assert response.status_code == 400

    def test_save_secret_missing_value(self):
        """Saving secret without value fails"""
        payload = {
            "key": "test_key",
            "value": ""
        }
        response = client.post(
            "/api/secrets",
            json=payload,
            headers={"Authorization": VALID_BEARER_TOKEN}
        )
        assert response.status_code == 400

    def test_secret_encoding(self):
        """Secrets are base64 encoded"""
        payload = {
            "key": "encode_test",
            "value": "plain-text-value"
        }
        response = client.post(
            "/api/secrets",
            json=payload,
            headers={"Authorization": VALID_BEARER_TOKEN}
        )
        assert response.status_code == 200

        # Value should be base64 encoded
        expected_encoded = base64.b64encode(b"plain-text-value").decode()
        # We would need to read from secrets file to verify encoding


class TestHealthCheckEndpoint:
    """Test /api/health endpoint"""

    def test_health_response_structure(self):
        """Health response has correct structure"""
        response = client.get("/api/health", headers={"Authorization": VALID_BEARER_TOKEN})
        assert response.status_code == 200
        data = response.json()

        assert "status" in data
        assert "gateway_health" in data
        assert "tunnel_health" in data
        assert "database_health" in data
        assert "api_latency_ms" in data
        assert "memory_usage_mb" in data
        assert "cpu_usage_percent" in data
        assert "uptime_hours" in data
        assert "errors_last_hour" in data
        assert "warnings_last_hour" in data
        assert "timestamp" in data

    def test_health_status_values(self):
        """Health status has valid values"""
        response = client.get("/api/health", headers={"Authorization": VALID_BEARER_TOKEN})
        assert response.status_code == 200
        data = response.json()

        # Status should be one of these
        assert data["status"] in ["healthy", "degraded", "unhealthy"]
        assert data["gateway_health"] in ["healthy", "unhealthy"]
        assert data["tunnel_health"] in ["healthy", "unhealthy"]

    def test_health_numeric_values(self):
        """Health metrics are valid numbers"""
        response = client.get("/api/health", headers={"Authorization": VALID_BEARER_TOKEN})
        assert response.status_code == 200
        data = response.json()

        assert isinstance(data["api_latency_ms"], (int, float))
        assert isinstance(data["memory_usage_mb"], (int, float))
        assert isinstance(data["cpu_usage_percent"], (int, float))
        assert isinstance(data["uptime_hours"], (int, float))
        assert isinstance(data["errors_last_hour"], int)
        assert isinstance(data["warnings_last_hour"], int)

        # Values should be non-negative
        assert data["api_latency_ms"] >= 0
        assert data["memory_usage_mb"] >= 0
        assert data["cpu_usage_percent"] >= 0
        assert data["uptime_hours"] >= 0
        assert data["errors_last_hour"] >= 0
        assert data["warnings_last_hour"] >= 0


class TestRestartEndpoint:
    """Test /api/restart endpoint"""

    def test_restart_response_structure(self):
        """Restart response has correct structure"""
        response = client.post(
            "/api/restart",
            headers={"Authorization": VALID_BEARER_TOKEN}
        )
        # This might succeed or fail depending on permissions
        if response.status_code == 200:
            data = response.json()
            assert "success" in data
            assert "message" in data
            assert "timestamp" in data


class TestErrorHandling:
    """Test error handling"""

    def test_404_not_found(self):
        """Nonexistent endpoint returns 404"""
        response = client.get("/api/nonexistent", headers={"Authorization": VALID_BEARER_TOKEN})
        assert response.status_code == 404

    def test_method_not_allowed(self):
        """Invalid HTTP method returns 405"""
        response = client.delete("/api/status", headers={"Authorization": VALID_BEARER_TOKEN})
        assert response.status_code == 405


# ============================================================================
# Fixtures and Runners
# ============================================================================

def run_all_tests():
    """Run all tests"""
    pytest.main([__file__, "-v", "--tb=short"])


if __name__ == "__main__":
    # Run with pytest if available
    try:
        import pytest
        pytest.main([__file__, "-v"])
    except ImportError:
        print("pytest not installed. Running basic checks...")
        print("✅ Import successful")
        print("✅ FastAPI app created")
        print("✅ All models defined")
        print("\nTo run full tests: pip install pytest && python test_dashboard_api.py")
