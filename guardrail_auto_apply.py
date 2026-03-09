"""
Auto-Apply Guardrail Recommendations Engine
===========================================

Automatically applies guardrail adjustments from self_improve.py recommendations
with safety limits and rollback capability. All changes are logged to
data/guardrail_changes.jsonl for auditing.

Features:
- Auto-apply recommendations from self_improve engine
- Safety limits: per-task $0.50-$5.00, daily $50 max
- Rollback mechanism: revert if success rate drops >20%
- Full audit trail in guardrail_changes.jsonl
"""

import json
import os
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List
from threading import Lock

logger = logging.getLogger("guardrail_auto_apply")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "os.environ.get("OPENCLAW_DATA_DIR", "./data")")
CHANGES_FILE = os.path.join(DATA_DIR, "guardrail_changes.jsonl")
GUARDRAIL_CONFIG_FILE = os.path.join(DATA_DIR, "guardrail_config.json")


@dataclass
class GuardrailChange:
    """Record of a guardrail modification."""
    timestamp: str
    change_id: str
    recommendation_type: str  # "tighten", "loosen", "increase_budget"
    project: str
    parameter: str  # "max_iterations", "max_cost_usd", "per_task_limit", "daily_limit"
    old_value: float
    new_value: float
    reason: str
    applied_by: str  # "auto_apply" or "manual"
    rollback_triggered: bool = False
    rollback_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GuardrailAutoApply:
    """Manages auto-application of guardrail recommendations."""

    # Safety limits (hard bounds)
    PER_TASK_MIN = 0.50
    PER_TASK_MAX = 5.00
    DAILY_MAX = 50.0
    MONTHLY_MAX = 1000.0

    # Rollback trigger: if success rate drops by this % after a change
    ROLLBACK_SUCCESS_RATE_DROP_THRESHOLD = 20.0  # percent

    # Lookback window for success rate calculation (days)
    ROLLBACK_CHECK_DAYS = 7

    def __init__(self, auto_apply: bool = True):
        """
        Initialize the auto-apply engine.

        Args:
            auto_apply: If False, recommendations are logged but not applied
        """
        self.auto_apply = auto_apply
        self._lock = Lock()
        self._init_files()

    def _init_files(self):
        """Initialize data directory and files."""
        os.makedirs(os.path.dirname(CHANGES_FILE), exist_ok=True)
        if not os.path.exists(GUARDRAIL_CONFIG_FILE):
            self._save_default_config()

    def _save_default_config(self):
        """Save default guardrail configuration."""
        config = {
            "per_task_limit": 2.0,
            "daily_limit": 50.0,
            "monthly_limit": 1000.0,
            "max_iterations": 400,
            "phase_iteration_limits": {
                "research": 60,
                "plan": 30,
                "execute": 250,
                "verify": 30,
                "deliver": 30,
            },
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        with open(GUARDRAIL_CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)

    def load_config(self) -> Dict[str, Any]:
        """Load current guardrail configuration."""
        if not os.path.exists(GUARDRAIL_CONFIG_FILE):
            self._save_default_config()
        with self._lock:
            with open(GUARDRAIL_CONFIG_FILE) as f:
                return json.load(f)

    def save_config(self, config: Dict[str, Any]):
        """Save guardrail configuration."""
        config["last_updated"] = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with open(GUARDRAIL_CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=2)

    def _log_change(self, change: GuardrailChange):
        """Log a guardrail change to the audit trail."""
        with self._lock:
            with open(CHANGES_FILE, "a") as f:
                f.write(json.dumps(change.to_dict()) + "\n")

    def _validate_and_clamp(
        self,
        parameter: str,
        new_value: float,
        old_value: float,
    ) -> tuple[bool, float, str]:
        """
        Validate a proposed guardrail change and clamp it to safety limits.

        Returns:
            (is_valid, clamped_value, reason)
        """
        # Per-task limits
        if parameter == "per_task_limit":
            if new_value < self.PER_TASK_MIN:
                return False, old_value, f"per_task_limit {new_value} below min {self.PER_TASK_MIN}"
            if new_value > self.PER_TASK_MAX:
                clamped = self.PER_TASK_MAX
                return True, clamped, f"clamped per_task_limit to max {self.PER_TASK_MAX}"
            return True, new_value, "valid"

        # Daily limit
        elif parameter == "daily_limit":
            if new_value > self.DAILY_MAX:
                clamped = self.DAILY_MAX
                return True, clamped, f"clamped daily_limit to max {self.DAILY_MAX}"
            if new_value <= 0:
                return False, old_value, f"daily_limit {new_value} must be positive"
            return True, new_value, "valid"

        # Monthly limit
        elif parameter == "monthly_limit":
            if new_value > self.MONTHLY_MAX:
                clamped = self.MONTHLY_MAX
                return True, clamped, f"clamped monthly_limit to max {self.MONTHLY_MAX}"
            if new_value <= 0:
                return False, old_value, f"monthly_limit {new_value} must be positive"
            return True, new_value, "valid"

        # Iteration limits
        elif parameter.startswith("max_iterations") or parameter in ["max_iterations"] + list(
            ["research", "plan", "execute", "verify", "deliver"]
        ):
            if new_value < 5:
                return False, old_value, f"iteration limit {new_value} below minimum 5"
            return True, int(new_value), "valid"

        return False, old_value, f"unknown parameter {parameter}"

    def apply_recommendation(self, recommendation: Dict[str, Any]) -> Optional[GuardrailChange]:
        """
        Apply a single recommendation from self_improve.py.

        Args:
            recommendation: Dict with keys: type, project, reason, suggested_* fields

        Returns:
            GuardrailChange record if applied, None if not applied
        """
        if not self.auto_apply:
            logger.info(f"Auto-apply disabled; would apply: {recommendation}")
            return None

        rec_type = recommendation.get("type")
        project = recommendation.get("project", "unknown")

        if rec_type == "tighten":
            return self._apply_tighten(recommendation, project)
        elif rec_type == "loosen":
            return self._apply_loosen(recommendation, project)
        elif rec_type == "increase_budget":
            return self._apply_increase_budget(recommendation, project)
        else:
            logger.warning(f"Unknown recommendation type: {rec_type}")
            return None

    def _apply_tighten(self, rec: Dict[str, Any], project: str) -> Optional[GuardrailChange]:
        """Apply tighten recommendation (lower iteration limits)."""
        config = self.load_config()
        old_max_iters = config.get("max_iterations", 400)
        suggested_iters = rec.get("suggested_max_iterations", int(old_max_iters * 0.8))

        is_valid, clamped_iters, reason = self._validate_and_clamp(
            "max_iterations", suggested_iters, old_max_iters
        )

        if not is_valid:
            logger.warning(f"Tighten recommendation rejected for {project}: {reason}")
            return None

        config["max_iterations"] = clamped_iters
        self.save_config(config)

        change = GuardrailChange(
            timestamp=datetime.now(timezone.utc).isoformat(),
            change_id=self._gen_change_id(),
            recommendation_type="tighten",
            project=project,
            parameter="max_iterations",
            old_value=old_max_iters,
            new_value=clamped_iters,
            reason=rec.get("reason", ""),
            applied_by="auto_apply",
        )
        self._log_change(change)
        logger.info(
            f"Applied tighten: {project} max_iterations {old_max_iters} -> {clamped_iters}"
        )
        return change

    def _apply_loosen(self, rec: Dict[str, Any], project: str) -> Optional[GuardrailChange]:
        """Apply loosen recommendation (increase per-task budget)."""
        config = self.load_config()
        old_per_task = config.get("per_task_limit", 2.0)
        suggested_cost = rec.get("suggested_max_cost_usd", old_per_task * 2)

        is_valid, clamped_cost, reason = self._validate_and_clamp(
            "per_task_limit", suggested_cost, old_per_task
        )

        if not is_valid:
            logger.warning(f"Loosen recommendation rejected for {project}: {reason}")
            return None

        config["per_task_limit"] = clamped_cost
        self.save_config(config)

        change = GuardrailChange(
            timestamp=datetime.now(timezone.utc).isoformat(),
            change_id=self._gen_change_id(),
            recommendation_type="loosen",
            project=project,
            parameter="per_task_limit",
            old_value=old_per_task,
            new_value=clamped_cost,
            reason=rec.get("reason", ""),
            applied_by="auto_apply",
        )
        self._log_change(change)
        logger.info(f"Applied loosen: {project} per_task_limit ${old_per_task} -> ${clamped_cost}")
        return change

    def _apply_increase_budget(self, rec: Dict[str, Any], project: str) -> Optional[GuardrailChange]:
        """Apply increase_budget recommendation (raise daily limit)."""
        config = self.load_config()
        old_daily = config.get("daily_limit", 50.0)
        # Increase by 20% or to $50, whichever is higher (but respect max)
        suggested_daily = max(old_daily * 1.2, 50.0)

        is_valid, clamped_daily, reason = self._validate_and_clamp(
            "daily_limit", suggested_daily, old_daily
        )

        if not is_valid:
            logger.warning(f"Increase budget recommendation rejected for {project}: {reason}")
            return None

        config["daily_limit"] = clamped_daily
        self.save_config(config)

        change = GuardrailChange(
            timestamp=datetime.now(timezone.utc).isoformat(),
            change_id=self._gen_change_id(),
            recommendation_type="increase_budget",
            project=project,
            parameter="daily_limit",
            old_value=old_daily,
            new_value=clamped_daily,
            reason=rec.get("reason", ""),
            applied_by="auto_apply",
        )
        self._log_change(change)
        logger.info(f"Applied increase_budget: daily_limit ${old_daily} -> ${clamped_daily}")
        return change

    def check_rollback(self, current_success_rate: float) -> Optional[GuardrailChange]:
        """
        Check if recent guardrail changes should be rolled back based on
        success rate drop.

        Args:
            current_success_rate: Current success rate (0-100)

        Returns:
            GuardrailChange record if rollback applied, None otherwise
        """
        # Get recent changes
        recent_changes = self._get_recent_changes(days=self.ROLLBACK_CHECK_DAYS)
        if not recent_changes:
            return None

        # Get success rate before the most recent change
        most_recent = recent_changes[-1]
        success_before_change = self._get_success_rate_before(most_recent["timestamp"])

        if success_before_change is None:
            return None

        drop = success_before_change - current_success_rate
        if drop > self.ROLLBACK_SUCCESS_RATE_DROP_THRESHOLD:
            logger.warning(
                f"Success rate dropped {drop:.1f}% after guardrail change "
                f"(from {success_before_change:.1f}% to {current_success_rate:.1f}%); "
                f"rolling back {most_recent['parameter']} change"
            )
            return self._rollback_change(most_recent)

        return None

    def _rollback_change(self, change_record: Dict[str, Any]) -> GuardrailChange:
        """Roll back a previous guardrail change."""
        config = self.load_config()
        param = change_record["parameter"]
        old_value = change_record["old_value"]

        config[param] = old_value
        self.save_config(config)

        rollback_change = GuardrailChange(
            timestamp=datetime.now(timezone.utc).isoformat(),
            change_id=self._gen_change_id(),
            recommendation_type=change_record["recommendation_type"],
            project=change_record["project"],
            parameter=param,
            old_value=change_record["new_value"],
            new_value=old_value,
            reason=f"Rollback due to success rate drop",
            applied_by="auto_apply",
            rollback_triggered=True,
            rollback_reason=f"Success rate dropped below {self.ROLLBACK_SUCCESS_RATE_DROP_THRESHOLD}%",
        )
        self._log_change(rollback_change)
        logger.info(f"Rolled back: {param} ${change_record['new_value']} -> ${old_value}")
        return rollback_change

    def _get_recent_changes(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get recent guardrail changes from audit log."""
        changes = []
        if not os.path.exists(CHANGES_FILE):
            return changes
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with open(CHANGES_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    change = json.loads(line)
                    if change.get("timestamp", "") >= cutoff and not change.get("rollback_triggered"):
                        changes.append(change)
                except json.JSONDecodeError:
                    continue
        return changes

    def _get_success_rate_before(self, timestamp: str) -> Optional[float]:
        """
        Get success rate from metrics recorded before a given timestamp.
        Uses self_improve.py's metrics if available.
        """
        try:
            from self_improve import get_self_improve_engine

            engine = get_self_improve_engine()
            # Get metrics from 14 days before the change timestamp
            change_dt = datetime.fromisoformat(timestamp)
            metrics = engine.get_metrics(days=14)
            if not metrics:
                return None

            # Filter to metrics before this change
            before_change = [
                m for m in metrics
                if m.get("timestamp", "") < timestamp
            ]
            if not before_change:
                return None

            successes = sum(1 for m in before_change if m["success"])
            return (successes / len(before_change)) * 100 if before_change else None
        except Exception as e:
            logger.error(f"Could not calculate pre-change success rate: {e}")
            return None

    @staticmethod
    def _gen_change_id() -> str:
        """Generate a unique change ID."""
        import uuid
        return f"change_{uuid.uuid4().hex[:12]}"

    def get_audit_trail(self, project: str = None, days: int = 30) -> List[Dict[str, Any]]:
        """Get audit trail of all guardrail changes."""
        changes = []
        if not os.path.exists(CHANGES_FILE):
            return changes
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with open(CHANGES_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    change = json.loads(line)
                    if change.get("timestamp", "") >= cutoff:
                        if project is None or change.get("project") == project:
                            changes.append(change)
                except json.JSONDecodeError:
                    continue
        return sorted(changes, key=lambda x: x.get("timestamp", ""))


# Global instance
_applier = None
_applier_lock = Lock()


def get_auto_apply_engine(auto_apply: bool = True) -> GuardrailAutoApply:
    """Get or create the auto-apply engine."""
    global _applier
    if _applier is None:
        with _applier_lock:
            if _applier is None:
                _applier = GuardrailAutoApply(auto_apply=auto_apply)
    return _applier


def apply_recommendations(recommendations: List[Dict[str, Any]]) -> List[GuardrailChange]:
    """Apply a batch of recommendations."""
    engine = get_auto_apply_engine()
    applied_changes = []
    for rec in recommendations:
        change = engine.apply_recommendation(rec)
        if change:
            applied_changes.append(change)
    return applied_changes
