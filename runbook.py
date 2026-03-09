"""
Runbook + alert dispatcher for OpenClaw.

Maps failure types to diagnostics/remediation and persists alerts in JSONL.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger("openclaw.runbook")


class AlertSeverity:
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class RunbookEntry:
    failure_type: str
    severity: str
    title: str
    diagnostic_steps: list[str]
    remediation: list[str]
    auto_action: str = ""


@dataclass
class Alert:
    id: str
    timestamp: str
    severity: str
    failure_type: str
    job_id: str
    agent_key: str = ""
    title: str = ""
    message: str = ""
    diagnostic_steps: list[str] = field(default_factory=list)
    remediation: list[str] = field(default_factory=list)
    acknowledged: bool = False
    acknowledged_at: str = ""
    extra_data: dict = field(default_factory=dict)


def get_supabase():
    """Best-effort Supabase client loader (returns None when unavailable)."""
    try:
        from supabase_client import get_client
        return get_client()
    except Exception:
        return None


class Runbook:
    """Failure runbook catalog + alert store/dispatcher."""

    ENTRIES = {
        "stuck_looper": RunbookEntry(
            failure_type="stuck_looper",
            severity=AlertSeverity.WARNING,
            title="Agent Stuck in Loop",
            diagnostic_steps=[
                "Check last 10 tool calls for repetition.",
                "Confirm target files/resources exist.",
                "Confirm tool permissions for the selected agent.",
                "Review whether task instructions are ambiguous.",
            ],
            remediation=[
                "Inject corrective guidance to change strategy.",
                "If repeated: stop and rerun with a tighter prompt.",
                "If recurring: inspect tool behavior for edge cases.",
            ],
        ),
        "stuck_wanderer": RunbookEntry(
            failure_type="stuck_wanderer",
            severity=AlertSeverity.WARNING,
            title="Agent Stalled (No Progress)",
            diagnostic_steps=[
                "Check last progress timestamp.",
                "Check model/provider availability and circuit state.",
                "Check whether waiting for human approval/input.",
                "Check context size near configured limits.",
            ],
            remediation=[
                "If provider issue: wait for breaker recovery/fallback.",
                "If idle: inject progress nudge or stop job.",
                "If context pressure: compact context and continue.",
            ],
        ),
        "stuck_repeater": RunbookEntry(
            failure_type="stuck_repeater",
            severity=AlertSeverity.WARNING,
            title="Agent Repeating Output",
            diagnostic_steps=[
                "Compare last 5 agent responses for duplicates.",
                "Check for validation/tool-feedback loops.",
                "Check generation settings for low diversity.",
            ],
            remediation=[
                "Inject corrective guidance.",
                "If repeated: switch model/profile for this phase.",
                "Review prompt constraints for contradictions.",
            ],
        ),
        "circuit_open": RunbookEntry(
            failure_type="circuit_open",
            severity=AlertSeverity.CRITICAL,
            title="Circuit Breaker Opened",
            diagnostic_steps=[
                "Identify the provider/agent that opened the breaker.",
                "Inspect error logs for root cause.",
                "Check provider status and quotas.",
                "Validate auth credentials and billing.",
            ],
            remediation=[
                "Allow half-open probe to recover automatically.",
                "If auth/billing issue: rotate/fix credentials.",
                "If rate-limited: reduce concurrency or switch provider.",
                "Use fallback model/provider where configured.",
            ],
        ),
        "context_overflow": RunbookEntry(
            failure_type="context_overflow",
            severity=AlertSeverity.WARNING,
            title="Context Budget Exceeded",
            diagnostic_steps=[
                "Check message count and token estimate.",
                "Check if compaction recently ran.",
                "Inspect for excessively verbose model output.",
            ],
            remediation=[
                "Checkpoint and restart with compacted context.",
                "Reduce tool loops/output verbosity.",
                "Lower per-phase context retention.",
            ],
        ),
        "quality_fail": RunbookEntry(
            failure_type="quality_fail",
            severity=AlertSeverity.WARNING,
            title="Quality Gate Failed",
            diagnostic_steps=[
                "Inspect judge score and dimension reasoning.",
                "Confirm task instructions and acceptance criteria.",
                "Confirm selected agent tier is appropriate.",
            ],
            remediation=[
                "Retry once with injected quality feedback.",
                "Escalate to higher-tier agent if repeated.",
                "Improve task-specific system guidance.",
            ],
        ),
        "job_failed_permanent": RunbookEntry(
            failure_type="job_failed_permanent",
            severity=AlertSeverity.CRITICAL,
            title="Job Failed (Permanent Error)",
            diagnostic_steps=[
                "Check exact error and category.",
                "Verify auth/billing and permissions.",
                "Check provider key validity/credits.",
            ],
            remediation=[
                "Do not auto-retry permanent failures.",
                "Fix credentials/permissions/billing first.",
                "Escalate for manual review when needed.",
            ],
        ),
        "job_failed_retries": RunbookEntry(
            failure_type="job_failed_retries",
            severity=AlertSeverity.CRITICAL,
            title="Job Failed After Max Retries",
            diagnostic_steps=[
                "Review retry history and root-cause pattern.",
                "Check whether errors were misclassified as transient.",
                "Check provider health and availability.",
            ],
            remediation=[
                "Switch model/provider for next attempt.",
                "Break task into smaller scoped units.",
                "Escalate to human review for stubborn failures.",
            ],
        ),
    }

    def __init__(self, max_alerts: int = 500, alert_file: str = ""):
        data_dir = os.getenv("OPENCLAW_DATA_DIR", "./data")
        self.max_alerts = max_alerts
        self.alert_file = alert_file or os.path.join(data_dir, "alerts.jsonl")
        self._alerts: list[Alert] = []
        self._webhooks: list[str] = []
        self._stats = {"fired": 0, "critical": 0, "warning": 0, "info": 0}
        self._load_alerts()

    def register_webhook(self, url: str):
        """Register webhook URL for critical alerts."""
        if url and url not in self._webhooks:
            self._webhooks.append(url)

    def fire(
        self,
        failure_type: str,
        job_id: str,
        agent_key: str = "",
        message: str = "",
        extra_data: Optional[dict] = None,
    ) -> Alert:
        """Create, persist, and dispatch an alert."""
        entry = self.ENTRIES.get(failure_type)
        severity = entry.severity if entry else AlertSeverity.WARNING
        title = entry.title if entry else f"Unknown failure: {failure_type}"
        diagnostic_steps = list(entry.diagnostic_steps) if entry else []
        remediation = list(entry.remediation) if entry else []

        now = datetime.now(timezone.utc)
        alert = Alert(
            id=f"{failure_type}-{job_id}-{now.strftime('%Y%m%dT%H%M%S%f')}",
            timestamp=now.isoformat(),
            severity=severity,
            failure_type=failure_type,
            job_id=job_id,
            agent_key=agent_key,
            title=title,
            message=message,
            diagnostic_steps=diagnostic_steps,
            remediation=remediation,
            extra_data=extra_data or {},
        )

        self._alerts.append(alert)
        if len(self._alerts) > self.max_alerts:
            self._alerts = self._alerts[-self.max_alerts :]

        self._stats["fired"] += 1
        self._stats[severity] = self._stats.get(severity, 0) + 1

        self._persist_alert(alert)
        self._sync_alert_to_supabase(alert)
        self._log_alert(alert)
        if severity == AlertSeverity.CRITICAL:
            self._send_webhooks(alert)
        return alert

    def get_alerts(
        self,
        limit: int = 50,
        severity: Optional[str] = None,
        job_id: Optional[str] = None,
        agent_key: Optional[str] = None,
    ) -> list[dict]:
        """Get recent alerts with optional filters."""
        filtered = self._alerts
        if severity:
            filtered = [a for a in filtered if a.severity == severity]
        if job_id:
            filtered = [a for a in filtered if a.job_id == job_id]
        if agent_key:
            filtered = [a for a in filtered if a.agent_key == agent_key]
        if limit < 1:
            limit = 1
        return [self._alert_to_dict(a) for a in filtered[-limit:]]

    def acknowledge(self, alert_id: str) -> bool:
        """Acknowledge one alert and persist updated state."""
        for alert in self._alerts:
            if alert.id == alert_id:
                alert.acknowledged = True
                alert.acknowledged_at = datetime.now(timezone.utc).isoformat()
                self._rewrite_alert_file()
                self._sync_ack_to_supabase(alert_id, alert.acknowledged_at)
                return True
        return False

    def get_runbook_entry(self, failure_type: str) -> Optional[dict]:
        entry = self.ENTRIES.get(failure_type)
        if not entry:
            return None
        return {
            "failure_type": entry.failure_type,
            "severity": entry.severity,
            "title": entry.title,
            "diagnostic_steps": list(entry.diagnostic_steps),
            "remediation": list(entry.remediation),
            "auto_action": entry.auto_action,
        }

    def get_all_runbook_entries(self) -> list[dict]:
        return [self.get_runbook_entry(key) for key in sorted(self.ENTRIES.keys())]

    def get_stats(self) -> dict:
        return dict(self._stats)

    def _persist_alert(self, alert: Alert):
        try:
            os.makedirs(os.path.dirname(self.alert_file) or ".", exist_ok=True)
            with open(self.alert_file, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(self._alert_to_dict(alert), ensure_ascii=True) + "\n")
        except Exception as exc:
            logger.debug("Failed to persist alert: %s", exc)

    def _rewrite_alert_file(self):
        """Rewrite full JSONL store (used after acknowledge)."""
        try:
            os.makedirs(os.path.dirname(self.alert_file) or ".", exist_ok=True)
            with open(self.alert_file, "w", encoding="utf-8") as handle:
                for alert in self._alerts:
                    handle.write(json.dumps(self._alert_to_dict(alert), ensure_ascii=True) + "\n")
        except Exception as exc:
            logger.debug("Failed to rewrite alert file: %s", exc)

    def _load_alerts(self):
        try:
            if not os.path.exists(self.alert_file):
                return
            with open(self.alert_file, "r", encoding="utf-8") as handle:
                for raw in handle:
                    line = raw.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    kwargs = {k: v for k, v in data.items() if k in Alert.__dataclass_fields__}
                    self._alerts.append(Alert(**kwargs))
            if len(self._alerts) > self.max_alerts:
                self._alerts = self._alerts[-self.max_alerts :]
        except Exception as exc:
            logger.debug("Failed to load alerts: %s", exc)

    def _log_alert(self, alert: Alert):
        message = f"[{alert.job_id}] {alert.failure_type}: {alert.message}"
        if alert.severity == AlertSeverity.CRITICAL:
            logger.error(message)
        elif alert.severity == AlertSeverity.WARNING:
            logger.warning(message)
        else:
            logger.info(message)

    def _sync_alert_to_supabase(self, alert: Alert):
        """Best-effort Supabase upsert; never blocks alert fire path."""
        try:
            sb = get_supabase()
            if not sb:
                return
            sb.table("alerts").upsert({
                "id": alert.id,
                "failure_type": alert.failure_type,
                "severity": alert.severity,
                "title": alert.title,
                "message": alert.message,
                "job_id": alert.job_id,
                "agent_key": alert.agent_key,
                "extra_data": alert.extra_data or {},
                "acknowledged": alert.acknowledged,
                "created_at": alert.timestamp,
                "acknowledged_at": alert.acknowledged_at or None,
            }).execute()
        except Exception as exc:
            logger.debug("Alert Supabase sync failed (non-fatal): %s", exc)

    def _sync_ack_to_supabase(self, alert_id: str, acknowledged_at: str):
        """Best-effort Supabase ack sync; never blocks acknowledge path."""
        try:
            sb = get_supabase()
            if not sb:
                return
            sb.table("alerts").update({
                "acknowledged": True,
                "acknowledged_at": acknowledged_at,
            }).eq("id", alert_id).execute()
        except Exception as exc:
            logger.debug("Alert acknowledge Supabase sync failed (non-fatal): %s", exc)

    def _send_webhooks(self, alert: Alert):
        """Best-effort webhook POST for critical alerts."""
        if not self._webhooks:
            return
        payload = json.dumps(self._alert_to_dict(alert), ensure_ascii=True).encode("utf-8")
        for url in self._webhooks:
            try:
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5):  # nosec - internal webhooks
                    pass
            except urllib.error.URLError as exc:
                logger.debug("Webhook failed for %s: %s", url, exc)
            except Exception as exc:
                logger.debug("Webhook failed for %s: %s", url, exc)

    def _alert_to_dict(self, alert: Alert) -> dict:
        return {
            "id": alert.id,
            "timestamp": alert.timestamp,
            "severity": alert.severity,
            "failure_type": alert.failure_type,
            "job_id": alert.job_id,
            "agent_key": alert.agent_key,
            "title": alert.title,
            "message": alert.message,
            "diagnostic_steps": list(alert.diagnostic_steps),
            "remediation": list(alert.remediation),
            "acknowledged": alert.acknowledged,
            "acknowledged_at": alert.acknowledged_at,
            "extra_data": dict(alert.extra_data),
        }


_runbook: Optional[Runbook] = None


def init_runbook(**kwargs) -> Runbook:
    global _runbook
    _runbook = Runbook(**kwargs)
    return _runbook


def get_runbook() -> Runbook:
    global _runbook
    if _runbook is None:
        _runbook = Runbook()
    return _runbook
