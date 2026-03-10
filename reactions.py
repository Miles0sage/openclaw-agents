"""
Reactions Engine for OpenClaw — Self-Healing Auto-Responder

Watches events from EventEngine and auto-spawns agents (via tmux) or sends
notifications based on configurable reaction rules.

Each reaction rule has: trigger event type, action, prompt/message template,
max retries, and cooldown to prevent spam.

Usage:
    from reactions import get_reactions_engine, register_with_event_engine
    from event_engine import get_event_engine

    register_with_event_engine(get_event_engine())
"""

import json
import logging
import os
import shlex
import subprocess
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger("reactions")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DATA_DIR = "./data"
RULES_FILENAME = "reactions.json"
TRIGGERS_FILENAME = "reaction_triggers.jsonl"

GATEWAY_URL = "http://localhost:18789"
SLACK_REPORT_ENDPOINT = f"{GATEWAY_URL}/slack/report/send"

# ---------------------------------------------------------------------------
# Default reaction rules (created on first init)
# ---------------------------------------------------------------------------

DEFAULT_RULES = [
    {
        "id": "ci_failed",
        "name": "Auto-fix CI failures",
        "trigger": "ci.failed",
        "action": "spawn_agent",
        "prompt_template": (
            "CI failed on PR #{pr_number} in {project}. "
            "Read the failure logs:\n{error_log}\n\n"
            "Fix the issues and push the fix."
        ),
        "message_template": "",
        "enabled": True,
        "max_retries": 3,
        "cooldown_seconds": 300,
        "agent_pref": "coder_agent",
    },
    {
        "id": "changes_requested",
        "name": "Address review comments",
        "trigger": "pr.changes_requested",
        "action": "spawn_agent",
        "prompt_template": (
            "Review comments posted on PR #{pr_number} in {project}. "
            "Address each comment and push fixes."
        ),
        "message_template": "",
        "enabled": True,
        "max_retries": 2,
        "cooldown_seconds": 600,
        "agent_pref": "coder_agent",
    },
    {
        "id": "pr_approved",
        "name": "Notify on PR approval",
        "trigger": "pr.approved",
        "action": "notify",
        "prompt_template": "",
        "message_template": "PR #{pr_number} in {project} approved and ready to merge.",
        "enabled": True,
        "max_retries": 0,
        "cooldown_seconds": 60,
        "agent_pref": "coder_agent",
    },
    {
        "id": "job_failed_auto_retry",
        "name": "Auto-retry failed jobs",
        "trigger": "job.failed",
        "action": "spawn_agent",
        "prompt_template": (
            "Job {job_id} failed with error: {error}\n"
            "Project: {project}\nTask: {task}\n\n"
            "Diagnose the failure and retry the task."
        ),
        "message_template": "",
        "enabled": True,
        "max_retries": 3,
        "cooldown_seconds": 300,
        "agent_pref": "coder_agent",
    },
    {
        "id": "deploy_complete_notify",
        "name": "Notify on deploy",
        "trigger": "deploy.complete",
        "action": "notify",
        "prompt_template": "",
        "message_template": "Deployed {project} to {env}. URL: {url}",
        "enabled": True,
        "max_retries": 0,
        "cooldown_seconds": 60,
        "agent_pref": "coder_agent",
    },
    {
        "id": "post_deploy_security_scan",
        "name": "Auto-scan after deploy",
        "trigger": "deploy.complete",
        "action": "spawn_agent",
        "prompt_template": (
            "A deploy just completed for {project}. URL: {url}\n\n"
            "Run a quick security scan against the deployed URL using the security_scan tool "
            "with scan_type='web'. Report any findings."
        ),
        "message_template": "",
        "enabled": True,
        "max_retries": 1,
        "cooldown_seconds": 600,
        "agent_pref": "hacker_agent",
    },
]


# ---------------------------------------------------------------------------
# ReactionRule dataclass
# ---------------------------------------------------------------------------


@dataclass
class ReactionRule:
    """Single reaction rule with trigger, action, and template."""

    id: str
    name: str
    trigger: str  # event type to match (e.g. "job.failed", "ci.failed")
    action: str  # "spawn_agent", "notify", "kill"
    prompt_template: str = ""  # used by spawn_agent
    message_template: str = ""  # used by notify
    enabled: bool = True
    max_retries: int = 3
    cooldown_seconds: int = 300
    agent_pref: str = "coder_agent"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ReactionRule":
        # Only pass fields that the dataclass accepts
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# Safe template formatting
# ---------------------------------------------------------------------------


class _SafeDict(defaultdict):
    """Dict that returns '{key}' for missing keys during str.format_map."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _safe_format(template: str, data: dict) -> str:
    """Format a template string, leaving unknown placeholders intact."""
    safe = _SafeDict(str)
    safe.update(data)
    try:
        return template.format_map(safe)
    except (KeyError, ValueError, IndexError):
        logger.warning("Template formatting failed, returning raw template")
        return template


# ---------------------------------------------------------------------------
# ReactionsEngine
# ---------------------------------------------------------------------------


class ReactionsEngine:
    """Watches events and auto-triggers reactions based on configurable rules."""

    def __init__(self, data_dir: str = DEFAULT_DATA_DIR) -> None:
        self._data_dir = data_dir
        self._rules_path = os.path.join(data_dir, RULES_FILENAME)
        self._triggers_path = os.path.join(data_dir, TRIGGERS_FILENAME)

        self._lock = threading.Lock()

        # rule_id -> last trigger timestamp
        self._cooldowns: Dict[str, float] = {}

        # rule_id -> consecutive trigger count (for max_retries)
        self._retry_counts: Dict[str, int] = {}

        # Load or create default rules
        self._rules: List[ReactionRule] = self.load_rules()

        logger.info(
            "ReactionsEngine initialized with %d rules from %s",
            len(self._rules),
            self._rules_path,
        )

    # ------------------------------------------------------------------
    # Rule persistence
    # ------------------------------------------------------------------

    def load_rules(self) -> List[ReactionRule]:
        """Load rules from data/reactions.json. Create defaults if missing."""
        os.makedirs(self._data_dir, exist_ok=True)

        if os.path.exists(self._rules_path):
            try:
                with open(self._rules_path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                rules = [ReactionRule.from_dict(r) for r in raw]
                logger.info("Loaded %d reaction rules", len(rules))
                return rules
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("Failed to load reactions.json: %s — using defaults", exc)

        # Create defaults
        rules = [ReactionRule.from_dict(r) for r in DEFAULT_RULES]
        self._rules = rules
        self.save_rules()
        logger.info("Created default reactions.json with %d rules", len(rules))
        return rules

    def save_rules(self) -> None:
        """Persist current rules to data/reactions.json."""
        os.makedirs(self._data_dir, exist_ok=True)
        with self._lock:
            data = [r.to_dict() for r in self._rules]
        try:
            with open(self._rules_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            logger.debug("Saved %d rules to %s", len(data), self._rules_path)
        except OSError as exc:
            logger.error("Failed to save reactions.json: %s", exc)

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def add_rule(self, rule: ReactionRule) -> str:
        """Add a new reaction rule. Returns the rule id."""
        with self._lock:
            # Ensure unique id
            existing_ids = {r.id for r in self._rules}
            if rule.id in existing_ids:
                rule.id = f"{rule.id}_{int(time.time())}"
            self._rules.append(rule)
        self.save_rules()
        logger.info("Added reaction rule: %s (%s)", rule.id, rule.name)
        return rule.id

    def update_rule(self, rule_id: str, updates: dict) -> None:
        """Update fields on an existing rule by id."""
        with self._lock:
            for rule in self._rules:
                if rule.id == rule_id:
                    for key, value in updates.items():
                        if hasattr(rule, key) and key != "id":
                            setattr(rule, key, value)
                    break
            else:
                logger.warning("Rule %s not found for update", rule_id)
                return
        self.save_rules()
        logger.info("Updated reaction rule: %s", rule_id)

    def delete_rule(self, rule_id: str) -> None:
        """Remove a rule by id."""
        with self._lock:
            self._rules = [r for r in self._rules if r.id != rule_id]
        self.save_rules()
        logger.info("Deleted reaction rule: %s", rule_id)

    def get_rules(self) -> List[dict]:
        """Return all rules as dicts (for API / dashboard)."""
        with self._lock:
            return [r.to_dict() for r in self._rules]

    # ------------------------------------------------------------------
    # Event handling (called by EventEngine subscriber)
    # ------------------------------------------------------------------

    def handle_event(self, event_record: dict) -> None:
        """Check all enabled rules against the incoming event.

        Called by EventEngine's wildcard subscriber. If a rule matches
        and is not on cooldown, execute its action.
        """
        event_type = event_record.get("event_type", "")
        event_data = event_record.get("data", {})

        # Merge top-level event fields into data for template access
        merged_data = dict(event_data)
        merged_data.setdefault("event_type", event_type)
        merged_data.setdefault("event_id", event_record.get("event_id", ""))
        merged_data.setdefault("timestamp", event_record.get("timestamp", ""))

        with self._lock:
            rules_snapshot = [r for r in self._rules if r.enabled]

        for rule in rules_snapshot:
            if rule.trigger != event_type:
                continue

            # Cooldown check
            if self._is_on_cooldown(rule.id):
                logger.debug(
                    "Reaction %s skipped (cooldown) for event %s",
                    rule.id,
                    event_type,
                )
                continue

            # Max retries check
            if rule.max_retries > 0:
                count = self._retry_counts.get(rule.id, 0)
                if count >= rule.max_retries:
                    logger.warning(
                        "Reaction %s hit max retries (%d/%d) — skipping",
                        rule.id,
                        count,
                        rule.max_retries,
                    )
                    continue

            # Execute the action
            logger.info(
                "Reaction triggered: %s (rule=%s, action=%s)",
                event_type,
                rule.id,
                rule.action,
            )

            # Update cooldown
            with self._lock:
                self._cooldowns[rule.id] = time.time()
                self._retry_counts[rule.id] = self._retry_counts.get(rule.id, 0) + 1

            # Dispatch by action type
            try:
                if rule.action == "spawn_agent":
                    self._execute_spawn(rule, merged_data)
                elif rule.action == "notify":
                    self._execute_notify(rule, merged_data)
                elif rule.action == "kill":
                    self._execute_kill(rule, merged_data)
                else:
                    logger.warning("Unknown action type: %s", rule.action)
            except Exception:
                logger.exception("Reaction %s execution failed", rule.id)
                self._log_trigger(rule.id, event_type, rule.action, "error")

    # ------------------------------------------------------------------
    # Action executors
    # ------------------------------------------------------------------

    def _execute_spawn(self, rule: ReactionRule, event_data: dict) -> None:
        """Spawn a Claude agent in a tmux pane to handle the reaction."""
        prompt = _safe_format(rule.prompt_template, event_data)
        output_file = f"/tmp/openclaw-reaction-{rule.id}-{int(time.time())}.txt"

        # Escape the prompt for shell embedding
        escaped_prompt = prompt.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")

        cmd = f'claude -p --allowedTools "*" "{escaped_prompt}" > {output_file} 2>&1'

        try:
            subprocess.Popen(
                [
                    "tmux",
                    "new-window",
                    "-t",
                    "openclaw",
                    "-n",
                    f"reaction-{rule.id}",
                    cmd,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(
                "Spawned reaction agent: rule=%s, window=reaction-%s, output=%s",
                rule.id,
                rule.id,
                output_file,
            )
            self._log_trigger(
                rule.id,
                rule.trigger,
                "spawn_agent",
                "spawned",
                extra={"output_file": output_file, "prompt_preview": prompt[:200]},
            )
        except FileNotFoundError:
            logger.error("tmux not found — cannot spawn reaction agent for %s", rule.id)
            self._log_trigger(rule.id, rule.trigger, "spawn_agent", "error_tmux_missing")
        except OSError as exc:
            logger.error("Failed to spawn reaction agent for %s: %s", rule.id, exc)
            self._log_trigger(rule.id, rule.trigger, "spawn_agent", f"error: {exc}")

    def _execute_notify(self, rule: ReactionRule, event_data: dict) -> None:
        """Send a Slack notification for the reaction."""
        message = _safe_format(rule.message_template, event_data)

        token = os.environ.get("GATEWAY_AUTH_TOKEN", "")
        if not token:
            logger.debug("GATEWAY_AUTH_TOKEN not set — logging notify locally only")
            logger.info("Reaction notify [%s]: %s", rule.id, message)
            self._log_trigger(rule.id, rule.trigger, "notify", "logged_local", extra={"message": message})
            return

        payload = json.dumps({
            "text": f"[Reaction: {rule.name}] {message}",
            "event_type": rule.trigger,
            "reaction_id": rule.id,
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
                logger.info(
                    "Reaction notify sent [%s]: %d — %s",
                    rule.id,
                    resp.status,
                    message[:100],
                )
                self._log_trigger(rule.id, rule.trigger, "notify", "sent", extra={"message": message})
        except (URLError, OSError) as exc:
            logger.warning("Reaction notify failed [%s]: %s", rule.id, exc)
            self._log_trigger(rule.id, rule.trigger, "notify", f"error: {exc}", extra={"message": message})

    def _execute_kill(self, rule: ReactionRule, event_data: dict) -> None:
        """Kill a tmux window/pane (used for runaway agents)."""
        target = event_data.get("tmux_target", "")
        if not target:
            logger.warning("Kill reaction %s has no tmux_target in event data", rule.id)
            self._log_trigger(rule.id, rule.trigger, "kill", "no_target")
            return

        try:
            subprocess.run(
                ["tmux", "kill-window", "-t", target],
                capture_output=True,
                timeout=10,
            )
            logger.info("Reaction kill: terminated tmux target %s (rule=%s)", target, rule.id)
            self._log_trigger(rule.id, rule.trigger, "kill", "killed", extra={"target": target})
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.error("Reaction kill failed [%s]: %s", rule.id, exc)
            self._log_trigger(rule.id, rule.trigger, "kill", f"error: {exc}")

    # ------------------------------------------------------------------
    # Cooldown management
    # ------------------------------------------------------------------

    def _is_on_cooldown(self, rule_id: str) -> bool:
        """Check if a rule is within its cooldown window."""
        with self._lock:
            last_trigger = self._cooldowns.get(rule_id)
            if last_trigger is None:
                return False

            # Find the rule to get its cooldown setting
            cooldown_seconds = 300  # default
            for rule in self._rules:
                if rule.id == rule_id:
                    cooldown_seconds = rule.cooldown_seconds
                    break

        elapsed = time.time() - last_trigger
        return elapsed < cooldown_seconds

    def reset_cooldown(self, rule_id: str) -> None:
        """Manually reset the cooldown for a rule (for admin/dashboard use)."""
        with self._lock:
            self._cooldowns.pop(rule_id, None)
            self._retry_counts.pop(rule_id, None)
        logger.info("Reset cooldown and retry count for rule %s", rule_id)

    def reset_all_cooldowns(self) -> None:
        """Reset all cooldowns and retry counters."""
        with self._lock:
            self._cooldowns.clear()
            self._retry_counts.clear()
        logger.info("Reset all reaction cooldowns and retry counts")

    # ------------------------------------------------------------------
    # Trigger history (JSONL log)
    # ------------------------------------------------------------------

    def _log_trigger(
        self,
        rule_id: str,
        event_type: str,
        action: str,
        result: str,
        extra: Optional[dict] = None,
    ) -> None:
        """Append a trigger record to data/reaction_triggers.jsonl."""
        record = {
            "rule_id": rule_id,
            "event_type": event_type,
            "action": action,
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            record["extra"] = extra

        try:
            os.makedirs(self._data_dir, exist_ok=True)
            with open(self._triggers_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, separators=(",", ":")) + "\n")
        except OSError as exc:
            logger.error("Failed to log trigger: %s", exc)

    def get_recent_triggers(self, limit: int = 20) -> List[dict]:
        """Return recent reaction triggers for dashboard display (newest first)."""
        triggers: List[dict] = []
        if not os.path.exists(self._triggers_path):
            return triggers

        try:
            with open(self._triggers_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        triggers.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError as exc:
            logger.error("Failed to read trigger log: %s", exc)
            return triggers

        # Return newest first, up to limit
        return triggers[-limit:][::-1]

    # ------------------------------------------------------------------
    # Status / dashboard helpers
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Return engine status summary for dashboard / API."""
        with self._lock:
            rules_count = len(self._rules)
            enabled_count = sum(1 for r in self._rules if r.enabled)
            cooldown_active = {
                rid: round(time.time() - ts, 1)
                for rid, ts in self._cooldowns.items()
            }
            retry_counts = dict(self._retry_counts)

        recent = self.get_recent_triggers(limit=5)

        return {
            "rules_total": rules_count,
            "rules_enabled": enabled_count,
            "cooldowns_active": cooldown_active,
            "retry_counts": retry_counts,
            "recent_triggers": recent,
        }


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_engine: Optional[ReactionsEngine] = None
_engine_lock = threading.Lock()


def get_reactions_engine(data_dir: str = DEFAULT_DATA_DIR) -> ReactionsEngine:
    """Return the singleton ReactionsEngine, creating it if needed."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = ReactionsEngine(data_dir=data_dir)
    return _engine


def register_with_event_engine(event_engine) -> None:
    """Subscribe the reactions engine to all events in the event engine.

    Call this once during application startup:
        from reactions import register_with_event_engine
        from event_engine import get_event_engine
        register_with_event_engine(get_event_engine())
    """
    engine = get_reactions_engine()
    event_engine.subscribe("*", engine.handle_event)
    logger.info("ReactionsEngine registered with EventEngine (wildcard subscriber)")
