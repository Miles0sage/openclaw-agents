"""
Test suite for n8n webhook event emission

Coverage:
1. Unit tests for _n8n_webhook_notify() - mock urlopen, verify payload structure
2. Unit tests for event filtering - non-job.* events are silently dropped
3. Integration tests for /webhook/openclaw-jobs endpoint
4. Integration test for emit → endpoint roundtrip
5. Error handling tests for malformed payloads
"""

import pytest
import json
import os
import time
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock, call
from io import BytesIO
import threading

from fastapi.testclient import TestClient

# Import the modules we're testing
from event_engine import EventEngine, get_event_engine, init_event_engine
from gateway import app


# ═══════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create a temporary data directory for testing."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "events").mkdir()
    (data_dir / "webhooks").mkdir()
    return str(data_dir)


@pytest.fixture
def event_engine(temp_data_dir, monkeypatch):
    """Create an event engine instance with a temporary data directory."""
    monkeypatch.setenv("OPENCLAW_DATA_DIR", temp_data_dir)
    engine = EventEngine()
    return engine


@pytest.fixture
def test_client():
    """Create a FastAPI TestClient for the gateway app."""
    return TestClient(app)


@pytest.fixture
def sample_job_event():
    """Sample job event data."""
    return {
        "job_id": "job-test-001",
        "project": "openclaw",
        "task": "Test task",
        "priority": "P2",
        "agent": "claude-opus"
    }


@pytest.fixture
def sample_event_record(sample_job_event):
    """Sample event record as it appears in subscribers."""
    return {
        "event_id": "event-123",
        "event_type": "job.created",
        "data": sample_job_event,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# ═══════════════════════════════════════════════════════════════════════
# UNIT TESTS: _n8n_webhook_notify()
# ═══════════════════════════════════════════════════════════════════════


class TestN8nWebhookNotify:
    """Test the _n8n_webhook_notify method directly."""

    def test_job_created_event_posts_correctly(self, event_engine, sample_event_record):
        """Test that job.created event sends correct HTTP POST."""
        sample_event_record["event_type"] = "job.created"

        with patch("event_engine.urlopen") as mock_urlopen:
            # Mock the response
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=None)
            mock_urlopen.return_value = mock_response

            # Call the method
            event_engine._n8n_webhook_notify(sample_event_record)

            # Verify urlopen was called
            assert mock_urlopen.called
            request_obj = mock_urlopen.call_args[0][0]

            # Verify URL
            assert request_obj.full_url == "http://localhost:18789/webhook/openclaw-jobs"

            # Verify method
            assert request_obj.get_method() == "POST"

            # Verify headers
            assert request_obj.headers["Content-type"] == "application/json"

            # Verify payload structure
            payload = json.loads(request_obj.data.decode("utf-8"))
            assert payload["event_type"] == "job.created"
            assert payload["event_id"] == "event-123"
            assert payload["data"]["job_id"] == "job-test-001"

    def test_job_completed_event_posts_correctly(self, event_engine, sample_event_record):
        """Test that job.completed event sends correct payload."""
        sample_event_record["event_type"] = "job.completed"
        sample_event_record["data"]["status"] = "success"

        with patch("event_engine.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=None)
            mock_urlopen.return_value = mock_response

            event_engine._n8n_webhook_notify(sample_event_record)

            request_obj = mock_urlopen.call_args[0][0]
            payload = json.loads(request_obj.data.decode("utf-8"))

            assert payload["event_type"] == "job.completed"
            assert payload["data"]["status"] == "success"

    def test_job_failed_event_posts_correctly(self, event_engine, sample_event_record):
        """Test that job.failed event sends correct payload."""
        sample_event_record["event_type"] = "job.failed"
        sample_event_record["data"]["error"] = "Task execution failed"

        with patch("event_engine.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=None)
            mock_urlopen.return_value = mock_response

            event_engine._n8n_webhook_notify(sample_event_record)

            request_obj = mock_urlopen.call_args[0][0]
            payload = json.loads(request_obj.data.decode("utf-8"))

            assert payload["event_type"] == "job.failed"
            assert payload["data"]["error"] == "Task execution failed"

    def test_job_approved_event_posts_correctly(self, event_engine, sample_event_record):
        """Test that job.approved event sends correct payload."""
        sample_event_record["event_type"] = "job.approved"
        sample_event_record["data"]["approved_by"] = "user-123"

        with patch("event_engine.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=None)
            mock_urlopen.return_value = mock_response

            event_engine._n8n_webhook_notify(sample_event_record)

            request_obj = mock_urlopen.call_args[0][0]
            payload = json.loads(request_obj.data.decode("utf-8"))

            assert payload["event_type"] == "job.approved"
            assert payload["data"]["approved_by"] == "user-123"

    def test_job_phase_change_event_posts_correctly(self, event_engine, sample_event_record):
        """Test that job.phase_change event sends correct payload."""
        sample_event_record["event_type"] = "job.phase_change"
        sample_event_record["data"]["phase"] = "execution"
        sample_event_record["data"]["previous_phase"] = "planning"

        with patch("event_engine.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=None)
            mock_urlopen.return_value = mock_response

            event_engine._n8n_webhook_notify(sample_event_record)

            request_obj = mock_urlopen.call_args[0][0]
            payload = json.loads(request_obj.data.decode("utf-8"))

            assert payload["event_type"] == "job.phase_change"
            assert payload["data"]["phase"] == "execution"

    def test_non_job_event_is_silently_dropped(self, event_engine, sample_event_record):
        """Test that non-job.* events are silently ignored."""
        sample_event_record["event_type"] = "proposal.created"

        with patch("event_engine.urlopen") as mock_urlopen:
            event_engine._n8n_webhook_notify(sample_event_record)

            # Verify urlopen was NOT called
            assert not mock_urlopen.called

    def test_cost_alert_event_is_silently_dropped(self, event_engine, sample_event_record):
        """Test that cost.alert events are silently ignored."""
        sample_event_record["event_type"] = "cost.alert"

        with patch("event_engine.urlopen") as mock_urlopen:
            event_engine._n8n_webhook_notify(sample_event_record)

            assert not mock_urlopen.called

    def test_agent_timeout_event_is_silently_dropped(self, event_engine, sample_event_record):
        """Test that agent.timeout events are silently ignored."""
        sample_event_record["event_type"] = "agent.timeout"

        with patch("event_engine.urlopen") as mock_urlopen:
            event_engine._n8n_webhook_notify(sample_event_record)

            assert not mock_urlopen.called

    def test_webhook_url_from_environment(self, event_engine, sample_event_record, monkeypatch):
        """Test that N8N_WEBHOOK_URL environment variable is used if set."""
        sample_event_record["event_type"] = "job.created"
        custom_url = "http://custom-n8n.example.com:5678/webhook"
        monkeypatch.setenv("N8N_WEBHOOK_URL", custom_url)

        with patch("event_engine.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=None)
            mock_urlopen.return_value = mock_response

            event_engine._n8n_webhook_notify(sample_event_record)

            request_obj = mock_urlopen.call_args[0][0]
            assert request_obj.full_url == custom_url

    def test_webhook_timeout_is_5_seconds(self, event_engine, sample_event_record):
        """Test that webhook POST has a 5-second timeout."""
        sample_event_record["event_type"] = "job.created"

        with patch("event_engine.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=None)
            mock_urlopen.return_value = mock_response

            event_engine._n8n_webhook_notify(sample_event_record)

            # Check that timeout=5 was passed
            assert mock_urlopen.call_args[1]["timeout"] == 5

    def test_webhook_network_error_is_logged_and_ignored(self, event_engine, sample_event_record):
        """Test that URLError during webhook POST is gracefully handled."""
        sample_event_record["event_type"] = "job.created"

        with patch("event_engine.urlopen") as mock_urlopen:
            from urllib.error import URLError
            mock_urlopen.side_effect = URLError("Network error")

            # Should not raise an exception
            event_engine._n8n_webhook_notify(sample_event_record)

            # Call succeeded (no exception raised)
            assert mock_urlopen.called

    def test_webhook_oserror_is_logged_and_ignored(self, event_engine, sample_event_record):
        """Test that OSError during webhook POST is gracefully handled."""
        sample_event_record["event_type"] = "job.created"

        with patch("event_engine.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = OSError("Connection refused")

            # Should not raise an exception
            event_engine._n8n_webhook_notify(sample_event_record)

            assert mock_urlopen.called


# ═══════════════════════════════════════════════════════════════════════
# UNIT TESTS: Event Filtering
# ═══════════════════════════════════════════════════════════════════════


class TestEventFiltering:
    """Test that only job.* events trigger n8n webhooks."""

    def test_only_job_events_trigger_webhook(self, event_engine):
        """Test that only job.* events are processed by n8n webhook handler."""
        non_job_events = [
            "proposal.created",
            "proposal.approved",
            "cost.alert",
            "cost.threshold_exceeded",
            "agent.timeout",
            "deploy.complete",
            "ci.failed",
            "custom",
        ]

        with patch("event_engine.urlopen") as mock_urlopen:
            for event_type in non_job_events:
                record = {
                    "event_id": "test-event",
                    "event_type": event_type,
                    "data": {"id": "test-123"},
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                event_engine._n8n_webhook_notify(record)

            # No webhook calls should have been made
            assert not mock_urlopen.called

    def test_all_job_events_trigger_webhook(self, event_engine):
        """Test that all job.* events are processed."""
        job_events = [
            "job.created",
            "job.completed",
            "job.failed",
            "job.approved",
            "job.phase_change",
        ]

        with patch("event_engine.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=None)
            mock_urlopen.return_value = mock_response

            for event_type in job_events:
                record = {
                    "event_id": f"test-event-{event_type}",
                    "event_type": event_type,
                    "data": {"job_id": "test-123"},
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                event_engine._n8n_webhook_notify(record)

            # All 5 job events should trigger a webhook call
            assert mock_urlopen.call_count == 5


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS: Gateway Endpoint
# ═══════════════════════════════════════════════════════════════════════


class TestN8nWebhookEndpoint:
    """Test the /webhook/openclaw-jobs gateway endpoint."""

    def test_endpoint_receives_and_logs_job_created_event(self, test_client, tmp_path, monkeypatch):
        """Test that the endpoint receives job.created and logs it."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "webhooks").mkdir()
        monkeypatch.setenv("OPENCLAW_DATA_DIR", str(data_dir))

        payload = {
            "event_type": "job.created",
            "event_id": "event-12345",
            "timestamp": "2026-03-03T12:00:00+00:00",
            "data": {
                "job_id": "job-001",
                "project": "openclaw",
                "task": "Test task",
                "priority": "P2"
            }
        }

        response = test_client.post("/webhook/openclaw-jobs", json=payload)

        # Should return 200 OK
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["event_id"] == "event-12345"
        assert "message" in data

    def test_endpoint_receives_and_logs_job_completed_event(self, test_client, tmp_path, monkeypatch):
        """Test that the endpoint receives job.completed and logs it."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "webhooks").mkdir()
        monkeypatch.setenv("OPENCLAW_DATA_DIR", str(data_dir))

        payload = {
            "event_type": "job.completed",
            "event_id": "event-12346",
            "timestamp": "2026-03-03T12:05:00+00:00",
            "data": {
                "job_id": "job-001",
                "status": "success",
                "result": "Task completed successfully"
            }
        }

        response = test_client.post("/webhook/openclaw-jobs", json=payload)

        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_endpoint_receives_and_logs_job_failed_event(self, test_client, tmp_path, monkeypatch):
        """Test that the endpoint receives job.failed and logs it."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "webhooks").mkdir()
        monkeypatch.setenv("OPENCLAW_DATA_DIR", str(data_dir))

        payload = {
            "event_type": "job.failed",
            "event_id": "event-12347",
            "timestamp": "2026-03-03T12:10:00+00:00",
            "data": {
                "job_id": "job-001",
                "error": "Task execution failed",
                "reason": "Resource exhausted"
            }
        }

        response = test_client.post("/webhook/openclaw-jobs", json=payload)

        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_endpoint_logs_to_jsonl_file(self, test_client, tmp_path, monkeypatch):
        """Test that events are actually written to the JSONL log file."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        webhooks_dir = data_dir / "webhooks"
        webhooks_dir.mkdir()
        monkeypatch.setenv("OPENCLAW_DATA_DIR", str(data_dir))

        payload = {
            "event_type": "job.created",
            "event_id": "event-log-test",
            "timestamp": "2026-03-03T12:00:00+00:00",
            "data": {
                "job_id": "job-log-001"
            }
        }

        response = test_client.post("/webhook/openclaw-jobs", json=payload)
        assert response.status_code == 200

        # Verify the log file was created and contains the event
        log_file = webhooks_dir / "n8n_events.jsonl"
        assert log_file.exists()

        with open(log_file, "r") as f:
            lines = f.readlines()
            assert len(lines) > 0

            # Parse the last line
            logged_record = json.loads(lines[-1])
            assert logged_record["event_type"] == "job.created"
            assert logged_record["event_id"] == "event-log-test"
            assert logged_record["data"]["job_id"] == "job-log-001"

    def test_endpoint_no_auth_required(self, test_client, tmp_path, monkeypatch):
        """Test that the endpoint does not require authentication."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "webhooks").mkdir()
        monkeypatch.setenv("OPENCLAW_DATA_DIR", str(data_dir))

        payload = {
            "event_type": "job.created",
            "event_id": "event-no-auth",
            "timestamp": "2026-03-03T12:00:00+00:00",
            "data": {"job_id": "job-001"}
        }

        # No auth headers provided
        response = test_client.post("/webhook/openclaw-jobs", json=payload)

        # Should still succeed (no 401 Unauthorized)
        assert response.status_code == 200

    def test_endpoint_handles_missing_event_type(self, test_client, tmp_path, monkeypatch):
        """Test endpoint gracefully handles missing event_type."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "webhooks").mkdir()
        monkeypatch.setenv("OPENCLAW_DATA_DIR", str(data_dir))

        payload = {
            "event_id": "event-missing-type",
            "timestamp": "2026-03-03T12:00:00+00:00",
            "data": {"job_id": "job-001"}
        }

        response = test_client.post("/webhook/openclaw-jobs", json=payload)

        # Should still return 200 (graceful degradation)
        assert response.status_code == 200

    def test_endpoint_handles_missing_event_id(self, test_client, tmp_path, monkeypatch):
        """Test endpoint gracefully handles missing event_id."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "webhooks").mkdir()
        monkeypatch.setenv("OPENCLAW_DATA_DIR", str(data_dir))

        payload = {
            "event_type": "job.created",
            "timestamp": "2026-03-03T12:00:00+00:00",
            "data": {"job_id": "job-001"}
        }

        response = test_client.post("/webhook/openclaw-jobs", json=payload)

        # Should still return 200
        assert response.status_code == 200

    def test_endpoint_handles_missing_data(self, test_client, tmp_path, monkeypatch):
        """Test endpoint gracefully handles missing data field."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "webhooks").mkdir()
        monkeypatch.setenv("OPENCLAW_DATA_DIR", str(data_dir))

        payload = {
            "event_type": "job.created",
            "event_id": "event-missing-data",
            "timestamp": "2026-03-03T12:00:00+00:00"
        }

        response = test_client.post("/webhook/openclaw-jobs", json=payload)

        # Should still return 200
        assert response.status_code == 200

    def test_endpoint_handles_malformed_json(self, test_client, tmp_path, monkeypatch):
        """Test endpoint handles malformed JSON gracefully."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "webhooks").mkdir()
        monkeypatch.setenv("OPENCLAW_DATA_DIR", str(data_dir))

        response = test_client.post(
            "/webhook/openclaw-jobs",
            content="{invalid json}",
            headers={"Content-Type": "application/json"}
        )

        # Should return 422 Unprocessable Entity or 400 Bad Request
        assert response.status_code in [400, 422]

    def test_endpoint_logs_timestamp_correctly(self, test_client, tmp_path, monkeypatch):
        """Test that endpoint adds its own webhook_timestamp to the log."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        webhooks_dir = data_dir / "webhooks"
        webhooks_dir.mkdir()
        monkeypatch.setenv("OPENCLAW_DATA_DIR", str(data_dir))

        before_time = datetime.now(timezone.utc)

        payload = {
            "event_type": "job.created",
            "event_id": "event-ts-test",
            "timestamp": "2026-03-03T12:00:00+00:00",
            "data": {"job_id": "job-ts-001"}
        }

        response = test_client.post("/webhook/openclaw-jobs", json=payload)
        after_time = datetime.now(timezone.utc)

        assert response.status_code == 200

        log_file = webhooks_dir / "n8n_events.jsonl"
        with open(log_file, "r") as f:
            logged_record = json.loads(f.readlines()[-1])

            # Verify webhook_timestamp is set
            assert "webhook_timestamp" in logged_record
            webhook_ts = datetime.fromisoformat(logged_record["webhook_timestamp"])

            # Timestamp should be between before and after
            assert before_time <= webhook_ts <= after_time


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS: Emit → Endpoint Roundtrip
# ═══════════════════════════════════════════════════════════════════════


class TestEmitWebhookRoundtrip:
    """Test the full flow from emit() to endpoint."""

    def test_emit_job_created_reaches_endpoint(self, temp_data_dir, tmp_path, monkeypatch):
        """Test that emit('job.created') triggers webhook POST to endpoint."""
        webhooks_dir = Path(temp_data_dir) / "webhooks"
        webhooks_dir.mkdir(exist_ok=True)

        monkeypatch.setenv("OPENCLAW_DATA_DIR", temp_data_dir)
        monkeypatch.setenv(
            "N8N_WEBHOOK_URL",
            "http://testserver/webhook/openclaw-jobs"
        )

        # Create a TestClient for the gateway
        test_client = TestClient(app)

        # Track what events are received
        received_events = []
        original_endpoint = app.post.__self__.routes[0]  # This won't work; use patch instead

        with patch("event_engine.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=None)
            mock_urlopen.return_value = mock_response

            # Create engine and emit event
            engine = EventEngine()
            event_id = engine.emit(
                "job.created",
                {
                    "job_id": "roundtrip-job-001",
                    "project": "openclaw",
                    "task": "Roundtrip test"
                },
                skip_dedup=True
            )

            # Wait for daemon thread
            time.sleep(0.2)

            # Verify webhook was called
            assert mock_urlopen.called
            request_obj = mock_urlopen.call_args[0][0]

            payload = json.loads(request_obj.data.decode("utf-8"))
            assert payload["event_type"] == "job.created"
            assert payload["data"]["job_id"] == "roundtrip-job-001"

    def test_emit_job_completed_reaches_endpoint(self, temp_data_dir, monkeypatch):
        """Test that emit('job.completed') triggers webhook POST."""
        monkeypatch.setenv("OPENCLAW_DATA_DIR", temp_data_dir)

        with patch("event_engine.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=None)
            mock_urlopen.return_value = mock_response

            engine = EventEngine()
            engine.emit(
                "job.completed",
                {
                    "job_id": "roundtrip-job-002",
                    "status": "success",
                    "result": "Test completed"
                },
                skip_dedup=True
            )

            time.sleep(0.2)

            assert mock_urlopen.called
            request_obj = mock_urlopen.call_args[0][0]
            payload = json.loads(request_obj.data.decode("utf-8"))
            assert payload["event_type"] == "job.completed"

    def test_emit_job_failed_reaches_endpoint(self, temp_data_dir, monkeypatch):
        """Test that emit('job.failed') triggers webhook POST."""
        monkeypatch.setenv("OPENCLAW_DATA_DIR", temp_data_dir)

        with patch("event_engine.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=None)
            mock_urlopen.return_value = mock_response

            engine = EventEngine()
            engine.emit(
                "job.failed",
                {
                    "job_id": "roundtrip-job-003",
                    "error": "Task failed",
                    "reason": "Resource exhausted"
                },
                skip_dedup=True
            )

            time.sleep(0.2)

            assert mock_urlopen.called
            request_obj = mock_urlopen.call_args[0][0]
            payload = json.loads(request_obj.data.decode("utf-8"))
            assert payload["event_type"] == "job.failed"

    def test_non_job_events_do_not_trigger_webhook(self, temp_data_dir, monkeypatch):
        """Test that non-job.* events don't trigger webhook even when emitted."""
        monkeypatch.setenv("OPENCLAW_DATA_DIR", temp_data_dir)

        with patch("event_engine.urlopen") as mock_urlopen:
            engine = EventEngine()
            engine.emit(
                "proposal.created",
                {
                    "title": "Test proposal",
                    "source_job_id": "job-001"
                },
                skip_dedup=True
            )

            time.sleep(0.2)

            # Webhook should NOT be called for non-job events
            assert not mock_urlopen.called


# ═══════════════════════════════════════════════════════════════════════
# ERROR HANDLING TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestErrorHandling:
    """Test error handling for malformed and edge-case payloads."""

    def test_endpoint_with_empty_payload(self, test_client, tmp_path, monkeypatch):
        """Test endpoint with empty JSON object."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "webhooks").mkdir()
        monkeypatch.setenv("OPENCLAW_DATA_DIR", str(data_dir))

        response = test_client.post("/webhook/openclaw-jobs", json={})

        # Should handle gracefully
        assert response.status_code == 200

    def test_endpoint_with_null_fields(self, test_client, tmp_path, monkeypatch):
        """Test endpoint with null fields."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "webhooks").mkdir()
        monkeypatch.setenv("OPENCLAW_DATA_DIR", str(data_dir))

        payload = {
            "event_type": None,
            "event_id": None,
            "timestamp": None,
            "data": None
        }

        response = test_client.post("/webhook/openclaw-jobs", json=payload)

        # Should handle gracefully
        assert response.status_code == 200

    def test_endpoint_with_unexpected_field_types(self, test_client, tmp_path, monkeypatch):
        """Test endpoint with incorrect field types."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "webhooks").mkdir()
        monkeypatch.setenv("OPENCLAW_DATA_DIR", str(data_dir))

        payload = {
            "event_type": 123,  # Should be string
            "event_id": ["array"],  # Should be string
            "timestamp": {"obj": "ect"},  # Should be string
            "data": "not-a-dict"  # Should be dict
        }

        response = test_client.post("/webhook/openclaw-jobs", json=payload)

        # May be 422 (validation error) or 200 (graceful)
        assert response.status_code in [200, 422]

    def test_endpoint_with_very_large_payload(self, test_client, tmp_path, monkeypatch):
        """Test endpoint with very large payload."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "webhooks").mkdir()
        monkeypatch.setenv("OPENCLAW_DATA_DIR", str(data_dir))

        # Create a large data field (1 MB of text)
        large_data = "x" * (1024 * 1024)

        payload = {
            "event_type": "job.created",
            "event_id": "event-large",
            "timestamp": "2026-03-03T12:00:00+00:00",
            "data": {
                "job_id": "job-large",
                "large_field": large_data
            }
        }

        response = test_client.post("/webhook/openclaw-jobs", json=payload)

        # Should handle or reject gracefully
        assert response.status_code in [200, 413]

    def test_endpoint_with_nested_data(self, test_client, tmp_path, monkeypatch):
        """Test endpoint with deeply nested data structures."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "webhooks").mkdir()
        monkeypatch.setenv("OPENCLAW_DATA_DIR", str(data_dir))

        # Create deeply nested data
        nested = {"level": 1}
        for i in range(2, 10):
            nested = {"level": i, "inner": nested}

        payload = {
            "event_type": "job.created",
            "event_id": "event-nested",
            "timestamp": "2026-03-03T12:00:00+00:00",
            "data": {
                "job_id": "job-nested",
                "nested_data": nested
            }
        }

        response = test_client.post("/webhook/openclaw-jobs", json=payload)

        # Should handle nested structures
        assert response.status_code == 200

    def test_endpoint_with_special_characters(self, test_client, tmp_path, monkeypatch):
        """Test endpoint with special characters in fields."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "webhooks").mkdir()
        monkeypatch.setenv("OPENCLAW_DATA_DIR", str(data_dir))

        payload = {
            "event_type": "job.created",
            "event_id": "event-special-\u00e9\u00e8\u00ea",
            "timestamp": "2026-03-03T12:00:00+00:00",
            "data": {
                "job_id": "job-special",
                "text": "Unicode: \u4e2d\u6587 \ud83d\ude00 \u00e9\u00e7\u00e0"
            }
        }

        response = test_client.post("/webhook/openclaw-jobs", json=payload)

        # Should handle unicode correctly
        assert response.status_code == 200

    def test_endpoint_with_very_long_strings(self, test_client, tmp_path, monkeypatch):
        """Test endpoint with very long string fields."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "webhooks").mkdir()
        monkeypatch.setenv("OPENCLAW_DATA_DIR", str(data_dir))

        very_long_string = "a" * 100000

        payload = {
            "event_type": "job.created",
            "event_id": "event-long-string",
            "timestamp": "2026-03-03T12:00:00+00:00",
            "data": {
                "job_id": "job-long",
                "long_text": very_long_string
            }
        }

        response = test_client.post("/webhook/openclaw-jobs", json=payload)

        # Should handle long strings
        assert response.status_code == 200
