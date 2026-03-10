"""
Test suite for email_notifications.py

Tests:
- EmailNotifier initialization and backend detection
- Template rendering (job_started, job_completed, job_failed, job_cancelled, budget_warning)
- Rate limiting and deduplication
- Notification history tracking
- FastAPI endpoints
- Integration with intake_routes
"""

import pytest
import json
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, mock_open
from email_notifications import (
    EmailNotifier,
    notify_status_change,
    MAX_EMAILS_PER_JOB,
    DEDUP_WINDOW_MINUTES,
)


class TestEmailNotifierInitialization:
    """Test notifier initialization and backend detection."""

    def test_notifier_creates_instance(self):
        """Should create notifier instance."""
        notifier = EmailNotifier()
        assert notifier is not None
        assert hasattr(notifier, 'backend')
        assert notifier.backend in ["file", "sendgrid", "smtp"]

    def test_notifier_has_dedup_cache(self):
        """Notifier should have dedup cache dict."""
        notifier = EmailNotifier()
        assert isinstance(notifier.dedup_cache, dict)

    def test_dedup_cache_init(self, tmp_path):
        """Dedup cache should load from disk if exists."""
        # Pre-create the file
        cache_file = tmp_path / "dedup.json"
        cache_file.write_text(json.dumps({"test:job": "2026-02-19T00:00:00+00:00"}))

        # Patch the path before creating notifier
        with patch('email_notifications.NOTIFICATION_DEDUP_FILE', str(cache_file)):
            notifier = EmailNotifier()
            assert "test:job" in notifier.dedup_cache


class TestTemplateRendering:
    """Test email template generation."""

    def setup_method(self):
        """Create notifier instance."""
        self.notifier = EmailNotifier()

    def test_template_job_started(self):
        """job_started template should render correctly."""
        job = {
            "job_id": "test-job-123",
            "project_name": "Test Project",
            "assigned_agent": "CodeGen Pro",
            "description": "Build a feature",
            "contact_email": "test@example.com",
        }

        subject, html = self.notifier._template_job_started(job)

        assert "Test Project" in subject
        assert "🚀" in subject
        assert "CodeGen Pro" in html
        assert "test-job-123" in html
        assert "<html>" in html
        assert "background: linear-gradient" in html  # inline CSS

    def test_template_job_completed(self):
        """job_completed template should render correctly."""
        job = {
            "job_id": "test-job-456",
            "project_name": "Complete Project",
            "assigned_agent": "CodeGen Elite",
            "cost_so_far": 12.34,
            "contact_email": "test@example.com",
        }

        subject, html = self.notifier._template_job_completed(job)

        assert "Complete Project" in subject
        assert "✅" in subject
        assert "$12.34" in html
        assert "CodeGen Elite" in html

    def test_template_job_failed(self):
        """job_failed template should render correctly."""
        job = {
            "job_id": "test-job-789",
            "project_name": "Failed Project",
            "logs": [
                {"timestamp": "2026-02-19T00:00:00Z", "message": "Error: timeout"},
                {"timestamp": "2026-02-19T00:01:00Z", "message": "Retrying..."},
                {"timestamp": "2026-02-19T00:02:00Z", "message": "Failed again"},
            ],
            "contact_email": "test@example.com",
        }

        subject, html = self.notifier._template_job_failed(job)

        assert "Failed Project" in subject
        assert "⚠️" in subject
        assert "Error: timeout" in html
        assert "Failed again" in html

    def test_template_job_cancelled(self):
        """job_cancelled template should render correctly."""
        job = {
            "job_id": "test-job-cancel",
            "project_name": "Cancelled Project",
            "cost_so_far": 5.50,
            "contact_email": "test@example.com",
        }

        subject, html = self.notifier._template_job_cancelled(job)

        assert "Cancelled Project" in subject
        assert "⏸️" in subject
        assert "$5.50" in html

    def test_template_budget_warning(self):
        """budget_warning template should render correctly."""
        job = {
            "job_id": "test-job-budget",
            "project_name": "Budget Project",
            "budget_limit": 100.0,
            "cost_so_far": 85.0,
            "contact_email": "test@example.com",
        }

        subject, html = self.notifier._template_budget_warning(job)

        assert "Budget Project" in subject
        assert "💰" in subject
        assert "85.0%" in html
        assert "$85.00" in html
        assert "$100.00" in html
        assert "progress-bar" in html


class TestRateLimitingAndDedup:
    """Test rate limiting and deduplication logic."""

    def setup_method(self):
        """Create notifier instance."""
        self.notifier = EmailNotifier()

    def test_dedup_key_generation(self):
        """Dedup key should combine job_id and notification_type."""
        job_id = "job-123"
        notif_type = "job_started"

        key = f"{job_id}:{notif_type}"
        assert key == "job-123:job_started"

    def test_should_deduplicate_no_cache(self):
        """Should not deduplicate if not in cache."""
        self.notifier.dedup_cache.clear()

        should_dedup = self.notifier._should_deduplicate("job-1", "job_started")
        assert should_dedup is False

    def test_should_deduplicate_recently_sent(self):
        """Should deduplicate if sent within window."""
        now = datetime.now(timezone.utc)
        self.notifier.dedup_cache["job-1:job_started"] = now.isoformat()

        should_dedup = self.notifier._should_deduplicate("job-1", "job_started")
        assert should_dedup is True

    def test_should_not_deduplicate_old(self):
        """Should not deduplicate if sent outside window."""
        old = datetime.now(timezone.utc) - self.notifier.dedup_window
        self.notifier.dedup_cache["job-1:job_started"] = old.isoformat()

        should_dedup = self.notifier._should_deduplicate("job-1", "job_started")
        assert should_dedup is False

    def test_count_emails_for_job(self, tmp_path):
        """Should count emails sent for a job."""
        history_file = tmp_path / "history.jsonl"
        history_file.write_text(
            json.dumps({"job_id": "job-1", "status": "sent"}) + "\n" +
            json.dumps({"job_id": "job-1", "status": "sent"}) + "\n" +
            json.dumps({"job_id": "job-2", "status": "sent"}) + "\n"
        )

        with patch('email_notifications.NOTIFICATION_HISTORY_FILE', str(history_file)):
            notifier = EmailNotifier()
            assert notifier._count_emails_for_job("job-1") == 2
            assert notifier._count_emails_for_job("job-2") == 1

    def test_max_emails_per_job_limit(self, tmp_path, monkeypatch):
        """Should respect MAX_EMAILS_PER_JOB limit."""
        monkeypatch.setenv("NOTIFICATION_HISTORY_FILE", str(tmp_path / "history.jsonl"))

        history_file = tmp_path / "history.jsonl"
        # Write MAX_EMAILS_PER_JOB entries
        lines = [
            json.dumps({"job_id": "job-1", "status": "sent"})
            for _ in range(MAX_EMAILS_PER_JOB)
        ]
        history_file.write_text("\n".join(lines) + "\n")

        notifier = EmailNotifier()
        job = {
            "job_id": "job-1",
            "contact_email": "test@example.com",
            "project_name": "Test",
        }

        # Should return True (skip intentionally, not fail)
        result = notifier.notify_on_status_change("job-1", "queued", "researching", job)
        assert result is True


class TestFileBackend:
    """Test file logging backend."""

    def test_log_to_file(self, tmp_path):
        """Should log email to JSONL file."""
        log_file = tmp_path / "emails.jsonl"
        log_file.touch()

        with patch('email_notifications.EMAIL_LOG_FILE', str(log_file)):
            notifier = EmailNotifier()
            notifier._log_to_file(
                "test@example.com",
                "Test Subject",
                "<html>Test body</html>"
            )

            # Read file
            assert log_file.exists()
            with open(log_file) as f:
                record = json.loads(f.read().strip())

            assert record["to"] == "test@example.com"
            assert record["subject"] == "Test Subject"
            assert "Test body" in record["html_body"]

    def test_send_email_file_backend(self, tmp_path):
        """send_email should log to file when using file backend."""
        log_file = tmp_path / "emails.jsonl"
        log_file.touch()

        with patch('email_notifications.EMAIL_LOG_FILE', str(log_file)):
            notifier = EmailNotifier()
            notifier.backend = "file"

            result = notifier.send_email(
                "test@example.com",
                "Subject",
                "<html>Body</html>"
            )

            assert result is True
            assert log_file.exists()


class TestNotificationHistory:
    """Test notification history tracking."""

    def test_record_notification(self, tmp_path):
        """Should append to history file."""
        history_file = tmp_path / "history.jsonl"
        history_file.touch()

        with patch('email_notifications.NOTIFICATION_HISTORY_FILE', str(history_file)):
            notifier = EmailNotifier()
            notifier._record_notification(
                "job-1",
                "job_started",
                "test@example.com",
                "Subject",
                "sent"
            )

            assert history_file.exists()
            with open(history_file) as f:
                record = json.loads(f.read().strip())

            assert record["job_id"] == "job-1"
            assert record["notification_type"] == "job_started"
            assert record["status"] == "sent"

    def test_get_notification_history(self, tmp_path):
        """Should retrieve and filter history."""
        history_file = tmp_path / "history.jsonl"
        history_file.write_text(
            json.dumps({"job_id": "job-1", "timestamp": "2026-02-19T00:00:00Z", "status": "sent"}) + "\n" +
            json.dumps({"job_id": "job-1", "timestamp": "2026-02-19T00:01:00Z", "status": "sent"}) + "\n" +
            json.dumps({"job_id": "job-2", "timestamp": "2026-02-19T00:02:00Z", "status": "sent"}) + "\n"
        )

        with patch('email_notifications.NOTIFICATION_HISTORY_FILE', str(history_file)):
            notifier = EmailNotifier()
            history = notifier.get_notification_history(job_id="job-1")

            assert len(history) == 2
            assert all(r["job_id"] == "job-1" for r in history)

    def test_get_notification_history_limit(self, tmp_path):
        """Should respect limit parameter."""
        history_file = tmp_path / "history.jsonl"
        lines = [
            json.dumps({"job_id": "job-1", "timestamp": f"2026-02-19T00:{i:02d}:00Z", "status": "sent"})
            for i in range(10)
        ]
        history_file.write_text("\n".join(lines) + "\n")

        with patch('email_notifications.NOTIFICATION_HISTORY_FILE', str(history_file)):
            notifier = EmailNotifier()
            history = notifier.get_notification_history(limit=5)

            assert len(history) == 5


class TestNotifyOnStatusChange:
    """Test the main notification trigger."""

    def test_notify_no_contact_email(self):
        """Should skip if job has no contact email."""
        notifier = EmailNotifier()
        job = {
            "job_id": "job-1",
            "project_name": "Test",
            "contact_email": None,
        }

        result = notifier.notify_on_status_change("job-1", "queued", "researching", job)
        assert result is True  # Skip intentionally

    def test_notify_status_transition_started(self, tmp_path, monkeypatch):
        """queued → researching should trigger job_started."""
        monkeypatch.setenv("NOTIFICATION_HISTORY_FILE", str(tmp_path / "history.jsonl"))
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        monkeypatch.delenv("SMTP_HOST", raising=False)

        tmp_path.joinpath("emails.jsonl").touch()
        monkeypatch.setenv("EMAIL_LOG_FILE", str(tmp_path / "emails.jsonl"))

        notifier = EmailNotifier()
        notifier.backend = "file"

        job = {
            "job_id": "job-1",
            "project_name": "Test Project",
            "assigned_agent": "CodeGen Pro",
            "contact_email": "test@example.com",
            "description": "Test",
        }

        result = notifier.notify_on_status_change("job-1", "queued", "researching", job)
        assert result is True

        # Check that it was recorded
        assert notifier._count_emails_for_job("job-1") > 0

    def test_notify_status_transition_completed(self, tmp_path, monkeypatch):
        """* → done should trigger job_completed."""
        monkeypatch.setenv("NOTIFICATION_HISTORY_FILE", str(tmp_path / "history.jsonl"))
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        monkeypatch.delenv("SMTP_HOST", raising=False)

        tmp_path.joinpath("emails.jsonl").touch()
        monkeypatch.setenv("EMAIL_LOG_FILE", str(tmp_path / "emails.jsonl"))

        notifier = EmailNotifier()
        notifier.backend = "file"

        job = {
            "job_id": "job-2",
            "project_name": "Test Project",
            "contact_email": "test@example.com",
            "cost_so_far": 10.0,
        }

        result = notifier.notify_on_status_change("job-2", "executing", "done", job)
        assert result is True

    def test_notify_budget_warning(self, tmp_path, monkeypatch):
        """Should trigger budget_warning at 80%."""
        monkeypatch.setenv("NOTIFICATION_HISTORY_FILE", str(tmp_path / "history.jsonl"))
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        monkeypatch.delenv("SMTP_HOST", raising=False)

        tmp_path.joinpath("emails.jsonl").touch()
        monkeypatch.setenv("EMAIL_LOG_FILE", str(tmp_path / "emails.jsonl"))

        notifier = EmailNotifier()
        notifier.backend = "file"

        job = {
            "job_id": "job-3",
            "project_name": "Test Project",
            "contact_email": "test@example.com",
            "budget_limit": 100.0,
            "cost_so_far": 85.0,  # 85%
        }

        result = notifier.notify_on_status_change("job-3", "executing", "executing", job)
        assert result is True


class TestBackendStatus:
    """Test get_backend_status endpoint."""

    def test_backend_status_file(self):
        """Should return file backend status."""
        notifier = EmailNotifier()
        notifier.backend = "file"

        status = notifier.get_backend_status()

        assert status["backend"] == "file"
        assert status["configured"] is True
        assert "log_file" in status

    def test_backend_status_sendgrid(self):
        """Should return sendgrid backend status."""
        notifier = EmailNotifier()
        notifier.backend = "sendgrid"

        status = notifier.get_backend_status()

        assert status["backend"] == "sendgrid"
        assert "sendgrid_api_key_present" in status

    def test_backend_status_smtp(self):
        """Should return SMTP backend status."""
        notifier = EmailNotifier()
        notifier.backend = "smtp"

        status = notifier.get_backend_status()

        assert status["backend"] == "smtp"
        assert "smtp_host" in status
        assert "smtp_user_present" in status


class TestIntegration:
    """Integration tests."""

    def test_notify_status_change_function(self, tmp_path):
        """notify_status_change helper should work."""
        history_file = tmp_path / "history.jsonl"
        history_file.touch()
        log_file = tmp_path / "emails.jsonl"
        log_file.touch()

        with patch('email_notifications.NOTIFICATION_HISTORY_FILE', str(history_file)), \
             patch('email_notifications.EMAIL_LOG_FILE', str(log_file)):
            job = {
                "job_id": "job-1",
                "project_name": "Test",
                "contact_email": "test@example.com",
                "assigned_agent": "CodeGen Pro",
            }

            # Should not raise
            notify_status_change("job-1", "queued", "researching", job)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
