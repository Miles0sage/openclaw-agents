"""
Email Notification System for OpenClaw

Supports multiple backends:
- SMTP (self-hosted) via env vars: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
- SendGrid API (production) via env var: SENDGRID_API_KEY
- File logging (dev mode) to /tmp/openclaw_emails.jsonl if neither configured

Features:
- Job lifecycle notifications (queued, started, completed, failed, cancelled)
- Budget warnings at 80% threshold
- Weekly digest emails
- Rate limiting: max 10 emails per job, dedup within 5 minutes
- FastAPI endpoints for testing and monitoring
"""

import os
import json
import logging
import smtplib
import urllib.request
import urllib.parse
import urllib.error
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from pathlib import Path
import hashlib

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("openclaw_email")

# -----------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")
EMAIL_LOG_FILE = os.path.join(DATA_DIR, "events", "emails.jsonl")
NOTIFICATION_DEDUP_FILE = os.path.join(DATA_DIR, "events", "notification_dedup.json")
NOTIFICATION_HISTORY_FILE = os.path.join(DATA_DIR, "events", "notification_history.jsonl")
MAX_EMAILS_PER_JOB = 10
DEDUP_WINDOW_MINUTES = 5

# Email backend configuration
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL", "notifications@openclaw.agency")
FROM_NAME = os.getenv("FROM_NAME", "OpenClaw Agency")

# Determine email backend
EMAIL_BACKEND = None
if SENDGRID_API_KEY:
    EMAIL_BACKEND = "sendgrid"
elif SMTP_HOST and SMTP_USER and SMTP_PASS:
    EMAIL_BACKEND = "smtp"
else:
    EMAIL_BACKEND = "file"  # Dev mode

logger.info("Email backend: %s", EMAIL_BACKEND)


# -----------------------------------------------------------------------
# Data Models
# -----------------------------------------------------------------------

@dataclass
class NotificationRecord:
    """Track sent notifications for dedup and rate limiting."""
    job_id: str
    notification_type: str  # "job_started", "job_completed", etc.
    timestamp: str  # ISO format
    recipient: str

    def dedup_key(self) -> str:
        """Generate a key for dedup checking."""
        return f"{self.job_id}:{self.notification_type}"


class TestEmailRequest(BaseModel):
    """Request to send a test email."""
    to: str = Field(..., description="Recipient email address")
    subject: str = Field(default="OpenClaw Test Email", description="Email subject")


class NotificationHistoryItem(BaseModel):
    """A single notification sent."""
    job_id: str
    notification_type: str
    recipient: str
    subject: str
    timestamp: str
    status: str  # "sent", "failed"
    error: Optional[str] = None


# -----------------------------------------------------------------------
# Email Notifier Class
# -----------------------------------------------------------------------

class EmailNotifier:
    """
    Send email notifications via SMTP, SendGrid, or file logging.
    """

    def __init__(self):
        self.backend = EMAIL_BACKEND
        self.dedup_window = timedelta(minutes=DEDUP_WINDOW_MINUTES)
        self._load_dedup_cache()
        self._ensure_history_file()

    def _load_dedup_cache(self) -> None:
        """Load dedup cache from disk."""
        self.dedup_cache = {}
        if os.path.exists(NOTIFICATION_DEDUP_FILE):
            try:
                with open(NOTIFICATION_DEDUP_FILE, "r") as f:
                    self.dedup_cache = json.load(f)
            except (json.JSONDecodeError, IOError):
                logger.warning("Failed to load dedup cache, starting fresh")
                self.dedup_cache = {}

    def _save_dedup_cache(self) -> None:
        """Persist dedup cache to disk."""
        try:
            with open(NOTIFICATION_DEDUP_FILE, "w") as f:
                json.dump(self.dedup_cache, f)
        except IOError as e:
            logger.error("Failed to save dedup cache: %s", e)

    def _ensure_history_file(self) -> None:
        """Create history file if it doesn't exist."""
        if not os.path.exists(NOTIFICATION_HISTORY_FILE):
            Path(NOTIFICATION_HISTORY_FILE).touch()

    def _should_deduplicate(self, job_id: str, notification_type: str) -> bool:
        """Check if this notification was sent recently."""
        dedup_key = f"{job_id}:{notification_type}"

        if dedup_key not in self.dedup_cache:
            return False

        last_sent_iso = self.dedup_cache[dedup_key]
        try:
            last_sent = datetime.fromisoformat(last_sent_iso)
            now = datetime.now(timezone.utc)
            age = now - last_sent

            if age < self.dedup_window:
                logger.debug("Deduplicating %s (sent %s ago)", dedup_key, age)
                return True
        except (ValueError, TypeError):
            pass

        return False

    def _count_emails_for_job(self, job_id: str) -> int:
        """Count how many emails have been sent for this job."""
        count = 0
        try:
            with open(NOTIFICATION_HISTORY_FILE, "r") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        if record.get("job_id") == job_id:
                            count += 1
                    except json.JSONDecodeError:
                        pass
        except IOError:
            pass
        return count

    def _record_notification(
        self, job_id: str, notification_type: str, recipient: str,
        subject: str, status: str, error: Optional[str] = None
    ) -> None:
        """Log notification to history file."""
        record = {
            "job_id": job_id,
            "notification_type": notification_type,
            "recipient": recipient,
            "subject": subject,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "error": error,
        }
        try:
            with open(NOTIFICATION_HISTORY_FILE, "a") as f:
                f.write(json.dumps(record) + "\n")
        except IOError as e:
            logger.error("Failed to write to notification history: %s", e)

    def _log_to_file(self, to: str, subject: str, html_body: str) -> None:
        """Log email to JSONL file (dev mode)."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "to": to,
            "subject": subject,
            "html_body": html_body,
        }
        try:
            with open(EMAIL_LOG_FILE, "a") as f:
                f.write(json.dumps(record) + "\n")
            logger.info("Email logged to file: %s", to)
        except IOError as e:
            logger.error("Failed to log email: %s", e)

    def _send_via_smtp(self, to: str, subject: str, html_body: str, text_body: Optional[str] = None) -> bool:
        """Send email via SMTP."""
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
            msg["To"] = to

            if text_body:
                msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)

            logger.info("Email sent via SMTP: %s", to)
            return True
        except Exception as e:
            logger.error("SMTP send failed: %s", e)
            return False

    def _send_via_sendgrid(self, to: str, subject: str, html_body: str, text_body: Optional[str] = None) -> bool:
        """Send email via SendGrid API."""
        try:
            payload = {
                "personalizations": [
                    {
                        "to": [{"email": to}],
                        "subject": subject,
                    }
                ],
                "from": {"email": FROM_EMAIL, "name": FROM_NAME},
                "content": [
                    {"type": "text/html", "value": html_body},
                ],
            }
            if text_body:
                payload["content"].insert(0, {"type": "text/plain", "value": text_body})

            headers = {
                "Authorization": f"Bearer {SENDGRID_API_KEY}",
                "Content-Type": "application/json",
            }

            req = urllib.request.Request(
                "https://api.sendgrid.com/v3/mail/send",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=10) as response:
                status = response.status
                if status in (200, 201, 202):
                    logger.info("Email sent via SendGrid: %s", to)
                    return True
                else:
                    logger.error("SendGrid returned %d", status)
                    return False
        except urllib.error.HTTPError as e:
            logger.error("SendGrid HTTP error: %s", e.read().decode())
            return False
        except Exception as e:
            logger.error("SendGrid send failed: %s", e)
            return False

    def send_email(self, to: str, subject: str, html_body: str, text_body: Optional[str] = None) -> bool:
        """
        Send an email using the configured backend.

        Args:
            to: Recipient email address
            subject: Email subject
            html_body: HTML email content (email-safe, inline CSS)
            text_body: Plain text fallback (optional)

        Returns:
            True if sent successfully, False otherwise
        """
        if not to:
            logger.warning("Cannot send email: no recipient")
            return False

        if self.backend == "sendgrid":
            success = self._send_via_sendgrid(to, subject, html_body, text_body)
        elif self.backend == "smtp":
            success = self._send_via_smtp(to, subject, html_body, text_body)
        else:  # file
            self._log_to_file(to, subject, html_body)
            success = True

        return success

    def notify_on_status_change(
        self, job_id: str, old_status: str, new_status: str, job: Dict[str, Any]
    ) -> bool:
        """
        Send appropriate notification based on status change.

        Maps transitions to notification types:
        - queued → researching: job_started
        - * → done: job_completed
        - * → failed: job_failed
        - * → cancelled: job_cancelled
        - any status with 80%+ budget: budget_warning

        Args:
            job_id: Job UUID
            old_status: Previous status
            new_status: Current status
            job: Full job dict from intake_routes

        Returns:
            True if notification was sent (or intentionally skipped), False if failed
        """
        contact_email = job.get("contact_email")
        if not contact_email:
            logger.debug("Job %s has no contact email, skipping notification", job_id[:8])
            return True

        # Check rate limiting
        email_count = self._count_emails_for_job(job_id)
        if email_count >= MAX_EMAILS_PER_JOB:
            logger.warning("Job %s has reached email limit (%d), skipping", job_id[:8], MAX_EMAILS_PER_JOB)
            return True

        # Determine notification type based on transition
        notification_type = None
        if new_status == "researching" and old_status == "queued":
            notification_type = "job_started"
        elif new_status == "done":
            notification_type = "job_completed"
        elif new_status == "failed":
            notification_type = "job_failed"
        elif new_status == "cancelled":
            notification_type = "job_cancelled"

        # Send the appropriate notification
        if notification_type:
            # Check dedup
            if self._should_deduplicate(job_id, notification_type):
                logger.debug("Notification %s:%s deduplicated", job_id[:8], notification_type)
                return True

            method_name = f"_template_{notification_type}"
            if hasattr(self, method_name):
                subject, html_body = getattr(self, method_name)(job)
                success = self.send_email(contact_email, subject, html_body)

                if success:
                    # Update dedup cache
                    dedup_key = f"{job_id}:{notification_type}"
                    self.dedup_cache[dedup_key] = datetime.now(timezone.utc).isoformat()
                    self._save_dedup_cache()

                # Record in history
                self._record_notification(
                    job_id, notification_type, contact_email, subject,
                    "sent" if success else "failed"
                )
                return success
            else:
                logger.error("No template for notification type: %s", notification_type)

        # Check for budget warning (on any status change)
        budget_limit = job.get("budget_limit")
        cost_so_far = job.get("cost_so_far", 0.0)
        if budget_limit and cost_so_far > 0:
            pct = (cost_so_far / budget_limit) * 100
            if pct >= 80:
                if not self._should_deduplicate(job_id, "budget_warning"):
                    subject, html_body = self._template_budget_warning(job)
                    success = self.send_email(contact_email, subject, html_body)

                    if success:
                        dedup_key = f"{job_id}:budget_warning"
                        self.dedup_cache[dedup_key] = datetime.now(timezone.utc).isoformat()
                        self._save_dedup_cache()

                    self._record_notification(
                        job_id, "budget_warning", contact_email, subject,
                        "sent" if success else "failed"
                    )
                    return success

        return True

    # -----------------------------------------------------------------------
    # Email Templates
    # -----------------------------------------------------------------------

    def _template_job_started(self, job: Dict[str, Any]) -> tuple:
        """Template: Job has been started."""
        job_id = job["job_id"]
        project_name = job["project_name"]
        assigned_agent = job.get("assigned_agent", "Unknown Agent")

        subject = f"🚀 Your job '{project_name}' has started"

        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #1a1a1a; background-color: #0f0f0f; margin: 0; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; background-color: #1a1a1a; border: 1px solid #333; border-radius: 8px; overflow: hidden; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px 20px; text-align: center; color: white; }}
        .header h1 {{ margin: 0; font-size: 24px; }}
        .content {{ padding: 30px 20px; }}
        .section {{ margin-bottom: 25px; }}
        .section h2 {{ color: #667eea; font-size: 16px; text-transform: uppercase; letter-spacing: 1px; margin: 0 0 10px 0; }}
        .detail {{ background-color: #2a2a2a; padding: 15px; border-left: 3px solid #667eea; border-radius: 4px; margin-bottom: 10px; }}
        .detail-label {{ color: #999; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }}
        .detail-value {{ color: #fff; font-size: 16px; margin-top: 5px; font-weight: 500; }}
        .footer {{ background-color: #0a0a0a; padding: 20px; border-top: 1px solid #333; text-align: center; font-size: 12px; color: #666; }}
        .button {{ display: inline-block; background-color: #667eea; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; margin-top: 15px; font-weight: 600; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Job Started</h1>
            <p>Your project is now being executed</p>
        </div>
        <div class="content">
            <div class="section">
                <h2>Project Details</h2>
                <div class="detail">
                    <div class="detail-label">Project Name</div>
                    <div class="detail-value">{project_name}</div>
                </div>
                <div class="detail">
                    <div class="detail-label">Job ID</div>
                    <div class="detail-value">{job_id}</div>
                </div>
                <div class="detail">
                    <div class="detail-label">Assigned Agent</div>
                    <div class="detail-value">{assigned_agent}</div>
                </div>
            </div>
            <div class="section">
                <p style="color: #ccc; line-height: 1.6;">
                    Your job has been picked up by our execution queue and is now being processed by <strong>{assigned_agent}</strong>.
                    We'll notify you when it's completed.
                </p>
            </div>
        </div>
        <div class="footer">
            <p>© 2026 OpenClaw Agency — Questions? Reply to this email</p>
        </div>
    </div>
</body>
</html>
"""
        return subject, html_body

    def _template_job_completed(self, job: Dict[str, Any]) -> tuple:
        """Template: Job has completed successfully."""
        job_id = job["job_id"]
        project_name = job["project_name"]
        cost_so_far = job.get("cost_so_far", 0.0)
        assigned_agent = job.get("assigned_agent", "Unknown Agent")

        subject = f"✅ Your job '{project_name}' is complete"

        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #1a1a1a; background-color: #0f0f0f; margin: 0; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; background-color: #1a1a1a; border: 1px solid #333; border-radius: 8px; overflow: hidden; }}
        .header {{ background: linear-gradient(135deg, #10b981 0%, #059669 100%); padding: 30px 20px; text-align: center; color: white; }}
        .header h1 {{ margin: 0; font-size: 24px; }}
        .content {{ padding: 30px 20px; }}
        .section {{ margin-bottom: 25px; }}
        .section h2 {{ color: #10b981; font-size: 16px; text-transform: uppercase; letter-spacing: 1px; margin: 0 0 10px 0; }}
        .detail {{ background-color: #2a2a2a; padding: 15px; border-left: 3px solid #10b981; border-radius: 4px; margin-bottom: 10px; }}
        .detail-label {{ color: #999; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }}
        .detail-value {{ color: #fff; font-size: 16px; margin-top: 5px; font-weight: 500; }}
        .footer {{ background-color: #0a0a0a; padding: 20px; border-top: 1px solid #333; text-align: center; font-size: 12px; color: #666; }}
        .button {{ display: inline-block; background-color: #10b981; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; margin-top: 15px; font-weight: 600; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>✅ Job Complete</h1>
            <p>Your project is ready to review</p>
        </div>
        <div class="content">
            <div class="section">
                <h2>Summary</h2>
                <div class="detail">
                    <div class="detail-label">Project Name</div>
                    <div class="detail-value">{project_name}</div>
                </div>
                <div class="detail">
                    <div class="detail-label">Job ID</div>
                    <div class="detail-value">{job_id}</div>
                </div>
                <div class="detail">
                    <div class="detail-label">Completed By</div>
                    <div class="detail-value">{assigned_agent}</div>
                </div>
                <div class="detail">
                    <div class="detail-label">Total Cost</div>
                    <div class="detail-value">${cost_so_far:.2f}</div>
                </div>
            </div>
            <div class="section">
                <p style="color: #ccc; line-height: 1.6;">
                    Great news! Your job has been completed successfully. All deliverables are ready for your review.
                    Log in to the client portal to view detailed results and download artifacts.
                </p>
            </div>
        </div>
        <div class="footer">
            <p>© 2026 OpenClaw Agency — Questions? Reply to this email</p>
        </div>
    </div>
</body>
</html>
"""
        return subject, html_body

    def _template_job_failed(self, job: Dict[str, Any]) -> tuple:
        """Template: Job has failed."""
        job_id = job["job_id"]
        project_name = job["project_name"]
        logs = job.get("logs", [])

        # Get last few log entries for context
        recent_logs = logs[-3:] if logs else []
        logs_html = "".join(
            f'<div style="color: #999; font-size: 12px; margin-bottom: 5px; font-family: monospace;">{log.get("message", "")}</div>'
            for log in recent_logs
        )

        subject = f"⚠️ Your job '{project_name}' has failed"

        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #1a1a1a; background-color: #0f0f0f; margin: 0; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; background-color: #1a1a1a; border: 1px solid #333; border-radius: 8px; overflow: hidden; }}
        .header {{ background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%); padding: 30px 20px; text-align: center; color: white; }}
        .header h1 {{ margin: 0; font-size: 24px; }}
        .content {{ padding: 30px 20px; }}
        .section {{ margin-bottom: 25px; }}
        .section h2 {{ color: #ef4444; font-size: 16px; text-transform: uppercase; letter-spacing: 1px; margin: 0 0 10px 0; }}
        .detail {{ background-color: #2a2a2a; padding: 15px; border-left: 3px solid #ef4444; border-radius: 4px; margin-bottom: 10px; }}
        .detail-label {{ color: #999; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }}
        .detail-value {{ color: #fff; font-size: 16px; margin-top: 5px; font-weight: 500; }}
        .logs {{ background-color: #0a0a0a; padding: 12px; border-radius: 4px; border: 1px solid #333; margin-top: 10px; }}
        .footer {{ background-color: #0a0a0a; padding: 20px; border-top: 1px solid #333; text-align: center; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚠️ Job Failed</h1>
            <p>We encountered an issue processing your request</p>
        </div>
        <div class="content">
            <div class="section">
                <h2>Details</h2>
                <div class="detail">
                    <div class="detail-label">Project Name</div>
                    <div class="detail-value">{project_name}</div>
                </div>
                <div class="detail">
                    <div class="detail-label">Job ID</div>
                    <div class="detail-value">{job_id}</div>
                </div>
            </div>
            <div class="section">
                <h2>Error Context</h2>
                <div class="logs">
                    {logs_html if logs_html else '<div style="color: #666; font-size: 12px;">No error logs available</div>'}
                </div>
            </div>
            <div class="section">
                <p style="color: #ccc; line-height: 1.6;">
                    Unfortunately, your job could not be completed due to an error. Our team has been notified and will investigate.
                    Please reply to this email if you'd like more details or need to resubmit with different parameters.
                </p>
            </div>
        </div>
        <div class="footer">
            <p>© 2026 OpenClaw Agency — Questions? Reply to this email</p>
        </div>
    </div>
</body>
</html>
"""
        return subject, html_body

    def _template_job_cancelled(self, job: Dict[str, Any]) -> tuple:
        """Template: Job was cancelled."""
        job_id = job["job_id"]
        project_name = job["project_name"]
        cost_so_far = job.get("cost_so_far", 0.0)

        subject = f"⏸️ Your job '{project_name}' has been cancelled"

        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #1a1a1a; background-color: #0f0f0f; margin: 0; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; background-color: #1a1a1a; border: 1px solid #333; border-radius: 8px; overflow: hidden; }}
        .header {{ background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%); padding: 30px 20px; text-align: center; color: white; }}
        .header h1 {{ margin: 0; font-size: 24px; }}
        .content {{ padding: 30px 20px; }}
        .section {{ margin-bottom: 25px; }}
        .section h2 {{ color: #6366f1; font-size: 16px; text-transform: uppercase; letter-spacing: 1px; margin: 0 0 10px 0; }}
        .detail {{ background-color: #2a2a2a; padding: 15px; border-left: 3px solid #6366f1; border-radius: 4px; margin-bottom: 10px; }}
        .detail-label {{ color: #999; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }}
        .detail-value {{ color: #fff; font-size: 16px; margin-top: 5px; font-weight: 500; }}
        .footer {{ background-color: #0a0a0a; padding: 20px; border-top: 1px solid #333; text-align: center; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⏸️ Job Cancelled</h1>
            <p>Your request has been stopped</p>
        </div>
        <div class="content">
            <div class="section">
                <h2>Cancellation Summary</h2>
                <div class="detail">
                    <div class="detail-label">Project Name</div>
                    <div class="detail-value">{project_name}</div>
                </div>
                <div class="detail">
                    <div class="detail-label">Job ID</div>
                    <div class="detail-value">{job_id}</div>
                </div>
                <div class="detail">
                    <div class="detail-label">Cost Incurred</div>
                    <div class="detail-value">${cost_so_far:.2f}</div>
                </div>
            </div>
            <div class="section">
                <p style="color: #ccc; line-height: 1.6;">
                    Your job has been cancelled. No further charges will be incurred.
                    If you'd like to restart this job or need anything else, please reach out.
                </p>
            </div>
        </div>
        <div class="footer">
            <p>© 2026 OpenClaw Agency — Questions? Reply to this email</p>
        </div>
    </div>
</body>
</html>
"""
        return subject, html_body

    def _template_budget_warning(self, job: Dict[str, Any]) -> tuple:
        """Template: Job approaching budget limit."""
        job_id = job["job_id"]
        project_name = job["project_name"]
        budget_limit = job.get("budget_limit", 0.0)
        cost_so_far = job.get("cost_so_far", 0.0)
        pct = round((cost_so_far / budget_limit) * 100, 1) if budget_limit else 0

        subject = f"💰 Budget warning for '{project_name}' ({pct}% used)"

        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #1a1a1a; background-color: #0f0f0f; margin: 0; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; background-color: #1a1a1a; border: 1px solid #333; border-radius: 8px; overflow: hidden; }}
        .header {{ background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); padding: 30px 20px; text-align: center; color: white; }}
        .header h1 {{ margin: 0; font-size: 24px; }}
        .content {{ padding: 30px 20px; }}
        .section {{ margin-bottom: 25px; }}
        .section h2 {{ color: #f59e0b; font-size: 16px; text-transform: uppercase; letter-spacing: 1px; margin: 0 0 10px 0; }}
        .detail {{ background-color: #2a2a2a; padding: 15px; border-left: 3px solid #f59e0b; border-radius: 4px; margin-bottom: 10px; }}
        .detail-label {{ color: #999; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }}
        .detail-value {{ color: #fff; font-size: 16px; margin-top: 5px; font-weight: 500; }}
        .progress {{ background-color: #0a0a0a; border-radius: 4px; height: 20px; overflow: hidden; margin-top: 10px; }}
        .progress-bar {{ background: linear-gradient(90deg, #f59e0b 0%, #d97706 100%); height: 100%; width: {min(pct, 100)}%; transition: width 0.3s; }}
        .footer {{ background-color: #0a0a0a; padding: 20px; border-top: 1px solid #333; text-align: center; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>💰 Budget Alert</h1>
            <p>Your job is approaching its budget limit</p>
        </div>
        <div class="content">
            <div class="section">
                <h2>Budget Status</h2>
                <div class="detail">
                    <div class="detail-label">Project Name</div>
                    <div class="detail-value">{project_name}</div>
                </div>
                <div class="detail">
                    <div class="detail-label">Job ID</div>
                    <div class="detail-value">{job_id}</div>
                </div>
                <div class="detail">
                    <div class="detail-label">Budget Limit</div>
                    <div class="detail-value">${budget_limit:.2f}</div>
                </div>
                <div class="detail">
                    <div class="detail-label">Cost So Far</div>
                    <div class="detail-value">${cost_so_far:.2f}</div>
                </div>
                <div class="detail">
                    <div class="detail-label">Usage</div>
                    <div style="margin-top: 10px;">
                        <div class="progress">
                            <div class="progress-bar"></div>
                        </div>
                        <div style="color: #f59e0b; margin-top: 8px; font-weight: 600;">{pct}% of budget used</div>
                    </div>
                </div>
            </div>
            <div class="section">
                <p style="color: #ccc; line-height: 1.6;">
                    Your job has consumed {pct}% of its allocated budget. If you need to adjust the budget limit or cancel the job,
                    please do so now to avoid unexpected charges.
                </p>
            </div>
        </div>
        <div class="footer">
            <p>© 2026 OpenClaw Agency — Questions? Reply to this email</p>
        </div>
    </div>
</body>
</html>
"""
        return subject, html_body

    def send_test_email(self, to: str) -> Dict[str, Any]:
        """Send a test email."""
        subject = "🧪 OpenClaw Test Email"
        html_body = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #1a1a1a; background-color: #0f0f0f; margin: 0; padding: 20px; }
        .container { max-width: 600px; margin: 0 auto; background-color: #1a1a1a; border: 1px solid #333; border-radius: 8px; overflow: hidden; }
        .header { background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); padding: 30px 20px; text-align: center; color: white; }
        .header h1 { margin: 0; font-size: 24px; }
        .content { padding: 30px 20px; }
        .footer { background-color: #0a0a0a; padding: 20px; border-top: 1px solid #333; text-align: center; font-size: 12px; color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🧪 Email System Test</h1>
        </div>
        <div class="content">
            <p style="color: #ccc; line-height: 1.6;">
                This is a test email from the OpenClaw notification system.
                If you're seeing this, the email backend is working correctly!
            </p>
            <div style="background-color: #2a2a2a; padding: 15px; border-radius: 4px; margin-top: 20px;">
                <div style="color: #999; font-size: 12px; margin-bottom: 5px;">Backend</div>
                <div style="color: #fff; font-weight: 600;">""" + self.backend.upper() + """</div>
            </div>
        </div>
        <div class="footer">
            <p>© 2026 OpenClaw Agency</p>
        </div>
    </div>
</body>
</html>
"""
        success = self.send_email(to, subject, html_body)

        if success:
            self._record_notification(
                "test", "test_email", to, subject, "sent"
            )

        return {
            "success": success,
            "backend": self.backend,
            "recipient": to,
            "message": f"Test email sent via {self.backend.upper()}" if success else "Failed to send test email",
        }

    def get_notification_history(self, job_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get notification history, optionally filtered by job ID."""
        records = []
        try:
            with open(NOTIFICATION_HISTORY_FILE, "r") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        if job_id is None or record.get("job_id") == job_id:
                            records.append(record)
                    except json.JSONDecodeError:
                        pass
        except IOError:
            pass

        # Return most recent first, limited
        records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return records[:limit]

    def get_backend_status(self) -> Dict[str, Any]:
        """Get status of email backend configuration."""
        status = {
            "backend": self.backend,
            "configured": True,
            "from_email": FROM_EMAIL,
            "from_name": FROM_NAME,
        }

        if self.backend == "sendgrid":
            status["sendgrid_api_key_present"] = bool(SENDGRID_API_KEY)
        elif self.backend == "smtp":
            status["smtp_host"] = SMTP_HOST
            status["smtp_port"] = SMTP_PORT
            status["smtp_user_present"] = bool(SMTP_USER)
            status["smtp_pass_present"] = bool(SMTP_PASS)
        elif self.backend == "file":
            status["log_file"] = EMAIL_LOG_FILE
            try:
                if os.path.exists(EMAIL_LOG_FILE):
                    with open(EMAIL_LOG_FILE, "r") as f:
                        status["logged_emails"] = sum(1 for _ in f)
                else:
                    status["logged_emails"] = 0
            except IOError:
                status["logged_emails"] = -1

        return status


# Global notifier instance
_notifier = None


def get_notifier() -> EmailNotifier:
    """Get or create the global notifier instance."""
    global _notifier
    if _notifier is None:
        _notifier = EmailNotifier()
    return _notifier


# -----------------------------------------------------------------------
# FastAPI Router
# -----------------------------------------------------------------------

router = APIRouter(tags=["notifications"])


@router.post("/api/notifications/test")
async def test_email(req: TestEmailRequest) -> Dict[str, Any]:
    """
    Send a test email to verify email backend is working.

    Returns:
        Success status and backend info
    """
    notifier = get_notifier()
    result = notifier.send_test_email(req.to)
    return result


@router.get("/api/notifications/history")
async def get_notification_history(
    job_id: Optional[str] = Query(None, description="Optional job ID filter"),
    limit: int = Query(50, ge=1, le=500, description="Max notifications to return"),
) -> Dict[str, Any]:
    """
    Get notification history.

    Returns:
        List of sent notifications with timestamps and status
    """
    notifier = get_notifier()
    records = notifier.get_notification_history(job_id=job_id, limit=limit)

    return {
        "count": len(records),
        "limit": limit,
        "job_id_filter": job_id,
        "notifications": records,
    }


@router.get("/api/notifications/config")
async def get_notification_config() -> Dict[str, Any]:
    """
    Get email backend configuration status (no secrets).

    Returns:
        Backend type and configuration info (secrets redacted)
    """
    notifier = get_notifier()
    return notifier.get_backend_status()


# -----------------------------------------------------------------------
# Integration Hook (to be called by intake_routes.update_job_status)
# -----------------------------------------------------------------------

def notify_status_change(job_id: str, old_status: str, new_status: str, job: Dict[str, Any]) -> None:
    """
    Call this from intake_routes.update_job_status to send notifications.

    Args:
        job_id: Job UUID
        old_status: Previous status
        new_status: Current status
        job: Full job dict
    """
    notifier = get_notifier()
    try:
        notifier.notify_on_status_change(job_id, old_status, new_status, job)
    except Exception as e:
        logger.error("Failed to send notification for job %s: %s", job_id[:8], e)


__all__ = [
    "EmailNotifier",
    "get_notifier",
    "router",
    "notify_status_change",
    "TestEmailRequest",
    "NotificationHistoryItem",
]
