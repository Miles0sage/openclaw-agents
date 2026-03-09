"""
Event Engine for OpenClaw Closed-Loop System

Singleton event emission/subscription engine with persistent logging,
Slack notifications, and automatic reaction handlers for job lifecycle events.

Usage:
    from event_engine import get_event_engine, init_event_engine

    engine = init_event_engine()
    engine.subscribe("job.completed", my_handler)
    engine.emit("job.completed", {"job_id": "abc", "agent": "coder_agent"})
"""

import json
import os
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger("event_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")
EVENT_LOG_PATH = os.path.join(DATA_DIR, "events", "events.jsonl")

VALID_EVENT_TYPES = frozenset([
    "job.created",
    "job.completed",
    "job.failed",
    "job.approved",
    "job.timeout",
    "job.phase_started",
    "job.phase_completed",
    "job.phase_change",
    "job.tool_called",
    "job.tool_completed",
    "proposal.created",
    "proposal.approved",
    "proposal.rejected",
    "proposal.auto_approved",
    "cost.alert",
    "cost.threshold_exceeded",
    "agent.stale",
    "agent.timeout",
    "deploy.complete",
    "deploy.failed",
    "ci.failed",
    "ci.passed",
    "scan.completed",
    "scan.failed",
    "ceo.started",
    "ceo.job_created",
    "ceo.alert",
    "ceo.decision",
    "ceo.health_check",
    "ceo.goal_updated",
    "custom",
    "test",
])

# Events that trigger a Slack notification
SLACK_NOTIFY_EVENTS = frozenset([
    # "job.completed",  # Too noisy — check dashboard instead
    # "job.failed",     # Too noisy — check dashboard instead
    "proposal.approved",
    "proposal.auto_approved",
    "cost.alert",
    "cost.threshold_exceeded",
    "agent.timeout",
])

GATEWAY_URL = "http://localhost:18789"
SLACK_REPORT_ENDPOINT = f"{GATEWAY_URL}/slack/report/send"

# ---------------------------------------------------------------------------
# Event record helper
# ---------------------------------------------------------------------------


def _make_event_record(event_type: str, data: dict) -> dict:
    """Build a canonical event record with metadata."""
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# EventEngine
# ---------------------------------------------------------------------------


class EventEngine:
    """Thread-safe event emission and subscription engine with persistent logging
    and deduplication."""

    # Deduplication window in seconds (5 minutes)
    DEDUP_WINDOW_SEC = 300

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable]] = {}
        self._lock = threading.Lock()
        self._log_path = EVENT_LOG_PATH
        self._running = True

        # Deduplication: track (event_type, dedup_key) -> last_emit_time
        self._dedup_cache: Dict[str, float] = {}
        self._dedup_lock = threading.Lock()

        # Failure tracking for smart escalation: task_key -> [failure records]
        self._failure_tracker: Dict[str, List[dict]] = {}
        self._failure_lock = threading.Lock()

        # Register built-in subscribers
        self.subscribe("*", self._log_event)
        for evt in SLACK_NOTIFY_EVENTS:
            self.subscribe(evt, self._slack_notify)
        self.subscribe("job.completed", self._reaction_handler)
        self.subscribe("job.failed", self._reaction_handler)
        # Subscribe to job and cost events for n8n webhook
        self.subscribe("job.created", self._n8n_webhook_notify)
        self.subscribe("job.completed", self._n8n_webhook_notify)
        self.subscribe("job.failed", self._n8n_webhook_notify)
        self.subscribe("job.approved", self._n8n_webhook_notify)
        self.subscribe("job.phase_change", self._n8n_webhook_notify)
        self.subscribe("cost.alert", self._n8n_webhook_notify)
        self.subscribe("cost.threshold_exceeded", self._n8n_webhook_notify)

        logger.info("EventEngine initialized with built-in subscribers + deduplication")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _dedup_key(self, event_type: str, data: dict) -> str:
        """Generate a deduplication key from event type + stable data fields."""
        # Use job_id, agent, and task_type as stable identifiers
        parts = [event_type]
        for field in ("job_id", "id", "agent", "task_type", "title", "severity"):
            val = data.get(field)
            if val:
                parts.append(str(val))
        return "|".join(parts)

    def _is_duplicate(self, dedup_key: str) -> bool:
        """Check if this event was already emitted within the dedup window."""
        now = time.time()
        with self._dedup_lock:
            # Clean old entries
            expired = [k for k, t in self._dedup_cache.items()
                       if now - t > self.DEDUP_WINDOW_SEC]
            for k in expired:
                del self._dedup_cache[k]

            last_time = self._dedup_cache.get(dedup_key)
            if last_time and (now - last_time) < self.DEDUP_WINDOW_SEC:
                return True
            self._dedup_cache[dedup_key] = now
            return False

    def emit(self, event_type: str, data: dict, skip_dedup: bool = False) -> str:
        """Fire an event to all subscribers. Non-blocking (runs in a thread).

        Deduplicates events with the same type+key within a 5-minute window.
        Set skip_dedup=True to force emission regardless.

        Returns the generated event_id, or empty string if deduplicated.
        """
        if event_type not in VALID_EVENT_TYPES:
            logger.warning("Unknown event type: %s (emitting anyway)", event_type)

        # Deduplication check
        if not skip_dedup:
            dk = self._dedup_key(event_type, data)
            if self._is_duplicate(dk):
                logger.debug("Deduplicated event: %s (%s)", event_type, dk[:60])
                return ""

        record = _make_event_record(event_type, data)
        event_id = record["event_id"]

        thread = threading.Thread(
            target=self._dispatch,
            args=(event_type, record),
            daemon=True,
            name=f"event-{event_type}-{event_id[:8]}",
        )
        thread.start()

        return event_id

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """Register a handler for an event type. Use '*' for all events."""
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(callback)
        logger.debug("Subscribed %s to %s", callback.__name__, event_type)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """Remove a handler for an event type."""
        with self._lock:
            subs = self._subscribers.get(event_type, [])
            try:
                subs.remove(callback)
                logger.debug("Unsubscribed %s from %s", callback.__name__, event_type)
            except ValueError:
                logger.warning(
                    "Callback %s not found for event %s",
                    callback.__name__,
                    event_type,
                )

    def get_recent_events(
        self, limit: int = 50, event_type: Optional[str] = None
    ) -> List[dict]:
        """Read recent events from the persistent log file.

        Returns up to *limit* events, newest first. Optionally filter by
        *event_type*.
        """
        events: List[dict] = []
        if not os.path.exists(self._log_path):
            return events

        try:
            with open(self._log_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event_type and record.get("event_type") != event_type:
                        continue
                    events.append(record)
        except OSError as exc:
            logger.error("Failed to read event log: %s", exc)
            return events

        # Return newest first, up to limit
        return events[-limit:][::-1]

    def shutdown(self) -> None:
        """Mark engine as shutting down (best-effort; daemon threads will exit)."""
        self._running = False
        logger.info("EventEngine shutting down")

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, event_type: str, record: dict) -> None:
        """Dispatch an event record to all matching subscribers."""
        with self._lock:
            # Gather callbacks for the specific event type + wildcard
            callbacks = list(self._subscribers.get(event_type, []))
            callbacks += list(self._subscribers.get("*", []))

        for cb in callbacks:
            try:
                cb(record)
            except Exception:
                logger.exception(
                    "Subscriber %s raised for %s", cb.__name__, event_type
                )

    # ------------------------------------------------------------------
    # Built-in subscribers
    # ------------------------------------------------------------------

    def _log_event(self, record: dict) -> None:
        """Append every event to the JSONL log file (always registered)."""
        try:
            with open(self._log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, separators=(",", ":")) + "\n")
        except OSError as exc:
            logger.error("Failed to write event log: %s", exc)

    def _slack_notify(self, record: dict) -> None:
        """POST important events to Slack via the gateway report endpoint."""
        event_type = record.get("event_type", "unknown")
        data = record.get("data", {})
        event_id = record.get("event_id", "n/a")
        ts = record.get("timestamp", "")

        # Build a human-readable summary
        summary = self._format_slack_summary(event_type, data, event_id, ts)

        token = os.environ.get("GATEWAY_AUTH_TOKEN", "")
        if not token:
            logger.debug("GATEWAY_AUTH_TOKEN not set; skipping Slack notify")
            return

        payload = json.dumps({
            "text": summary,
            "event_type": event_type,
            "event_id": event_id,
        }).encode("utf-8")

        req = Request(
            SLACK_REPORT_ENDPOINT,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )

        try:
            with urlopen(req, timeout=5) as resp:
                logger.debug(
                    "Slack notify sent (%s): %d", event_type, resp.status
                )
        except (URLError, OSError) as exc:
            logger.warning("Slack notify failed for %s: %s", event_type, exc)

    def _n8n_webhook_notify(self, record: dict) -> None:
        """POST job events to n8n webhook for pipeline monitoring and visualization."""
        event_type = record.get("event_type", "unknown")
        data = record.get("data", {})
        event_id = record.get("event_id", "n/a")
        ts = record.get("timestamp", "")

        # Only post job-related events to n8n; cost.* events are silently dropped
        if not event_type.startswith("job."):
            return

        # Post directly to n8n webhook. Production URL expects workflow to be active.
        # Use test URL format for development (http://localhost:5678/webhook-test/{path})
        # Use production URL for active workflows (http://localhost:5678/webhook/{path})
        n8n_base_url = os.environ.get("N8N_BASE_URL", "http://localhost:5678")
        n8n_webhook_mode = os.environ.get("N8N_WEBHOOK_MODE", "webhook")  # "webhook" or "webhook-test"
        n8n_webhook_path = os.environ.get("N8N_WEBHOOK_PATH", "openclaw-events")

        n8n_webhook_url = f"{n8n_base_url}/{n8n_webhook_mode}/{n8n_webhook_path}"

        payload = json.dumps({
            "event_type": event_type,
            "event_id": event_id,
            "timestamp": ts,
            "data": data,
        }).encode("utf-8")

        req = Request(
            n8n_webhook_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(req, timeout=5) as resp:
                logger.debug(
                    "n8n webhook sent (%s): %d", event_type, resp.status
                )
        except (URLError, OSError) as exc:
            logger.debug("n8n webhook failed for %s: %s (non-critical)", event_type, exc)

    def _reaction_handler(self, record: dict) -> None:
        """Smart automatic reactions to job lifecycle events.

        - job.completed + code task  -> emit proposal.created for "run tests"
        - job.completed              -> extract memories from result
        - job.failed (1st time)      -> propose retry on same agent
        - job.failed (2nd time same task) -> escalate to Opus instead of retrying on Kimi
        """
        event_type = record.get("event_type")
        data = record.get("data", {})

        if event_type == "job.completed":
            task_type = data.get("task_type", "")
            job_id = data.get("job_id", data.get("id", "unknown"))
            agent = data.get("agent", "unknown")

            # Memory extraction (memory_manager removed — no-op)
            logger.debug("Memory extraction skipped for job %s (memory_manager removed)", job_id)

            # Only propose test run for code-related tasks
            code_indicators = {"code", "build", "deploy", "implement", "fix", "refactor"}
            if any(kw in task_type.lower() for kw in code_indicators):
                self.emit("proposal.created", {
                    "title": f"Run tests for completed job {job_id}",
                    "description": (
                        f"Agent {agent} completed code task '{task_type}'. "
                        "Proposing automated test run to verify changes."
                    ),
                    "source_event_id": record.get("event_id"),
                    "source_job_id": job_id,
                    "priority": "normal",
                    "proposed_action": "run_tests",
                })
                logger.info("Reaction: proposed test run for job %s", job_id)

        elif event_type == "job.failed":
            job_id = data.get("job_id", data.get("id", "unknown"))
            agent = data.get("agent", "unknown")
            reason = data.get("reason", data.get("error", "unknown error"))
            task_type = data.get("task_type", data.get("task", ""))

            # Track failures per task key for escalation detection
            task_key = f"{task_type}|{data.get('project', 'default')}"
            failure_count = self._track_failure(task_key, {
                "job_id": job_id,
                "agent": agent,
                "reason": reason,
                "timestamp": record.get("timestamp", ""),
            })

            # Lesson recording (memory_manager removed — no-op)
            logger.debug("Lesson recording skipped for job %s (memory_manager removed)", job_id)

            if failure_count >= 2:
                # ESCALATION: same task failed 2+ times -> route to Opus
                self.emit("proposal.created", {
                    "title": f"Escalate job {job_id} to Claude Opus (2x failure on {agent})",
                    "description": (
                        f"Task '{task_type}' has failed {failure_count}x "
                        f"(last agent: {agent}, reason: {reason}). "
                        "Escalating to Claude Opus for higher reasoning capability."
                    ),
                    "source_event_id": record.get("event_id"),
                    "source_job_id": job_id,
                    "priority": "critical",
                    "proposed_action": "escalate_to_opus",
                    "target_agent": "overseer",
                    "target_model": "claude-opus-4-6",
                    "failure_count": failure_count,
                }, skip_dedup=True)
                logger.warning(
                    "Reaction: ESCALATING job %s to Opus after %d failures on %s",
                    job_id, failure_count, agent,
                )
            else:
                # First failure: propose retry on same agent
                self.emit("proposal.created", {
                    "title": f"Retry failed job {job_id} with higher priority",
                    "description": (
                        f"Agent {agent} failed: {reason}. "
                        "Proposing retry with elevated priority."
                    ),
                    "source_event_id": record.get("event_id"),
                    "source_job_id": job_id,
                    "priority": "high",
                    "proposed_action": "retry",
                })
                logger.info("Reaction: proposed retry for failed job %s", job_id)

    def _track_failure(self, task_key: str, failure_record: dict) -> int:
        """Track failures per task key. Returns total failure count for this task.

        Failures older than 1 hour are pruned to avoid stale escalation.
        """
        now = time.time()
        with self._failure_lock:
            if task_key not in self._failure_tracker:
                self._failure_tracker[task_key] = []

            # Prune failures older than 1 hour
            one_hour_ago = now - 3600
            self._failure_tracker[task_key] = [
                f for f in self._failure_tracker[task_key]
                if f.get("_tracked_at", 0) > one_hour_ago
            ]

            failure_record["_tracked_at"] = now
            self._failure_tracker[task_key].append(failure_record)

            return len(self._failure_tracker[task_key])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_slack_summary(
        event_type: str, data: dict, event_id: str, ts: str
    ) -> str:
        """Build a concise Slack-friendly text summary for an event."""
        prefix_map = {
            "job.completed": "[OK]",
            "job.failed": "[FAIL]",
            "proposal.approved": "[APPROVED]",
            "proposal.auto_approved": "[AUTO-OK]",
            "cost.alert": "[COST]",
            "cost.threshold_exceeded": "[BUDGET]",
            "agent.timeout": "[TIMEOUT]",
        }
        prefix = prefix_map.get(event_type, "[EVENT]")
        agent = data.get("agent", "system")
        job_id = data.get("job_id", data.get("id", ""))
        detail = data.get("reason", data.get("description", data.get("title", "")))

        parts = [f"{prefix} {event_type}"]
        if agent:
            parts.append(f"agent={agent}")
        if job_id:
            parts.append(f"job={job_id}")
        if detail:
            parts.append(f"| {detail[:120]}")
        parts.append(f"({event_id[:8]})")

        return " ".join(parts)


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_engine_instance: Optional[EventEngine] = None
_engine_lock = threading.Lock()


def init_event_engine() -> EventEngine:
    """Initialize the singleton EventEngine. Safe to call multiple times;
    returns the existing instance if already created."""
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None:
            _engine_instance = EventEngine()
        return _engine_instance


def get_event_engine() -> EventEngine:
    """Return the singleton EventEngine, initializing if needed."""
    if _engine_instance is None:
        return init_event_engine()
    return _engine_instance
