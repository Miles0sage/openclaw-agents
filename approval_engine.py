"""
Auto-Approval Rules Engine for OpenClaw Closed-Loop System.

Evaluates proposals against configurable policy rules to determine
whether they can be auto-approved or require human review.
"""

import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests

from job_manager import create_job

logger = logging.getLogger("approval_engine")

CONFIG_PATH = Path("./config.json")

DEFAULT_RULES = [
    {
        "id": "low_cost_non_security",
        "description": "Auto-approve cheap, non-sensitive tasks",
        "condition": "cost_est_usd < 0.50 AND no security tag",
        "action": "auto_approve",
    },
    {
        "id": "cheap_model_moderate_cost",
        "description": "Auto-approve cheap-model agents under $2",
        "condition": "agent in (coder_agent, hacker_agent) AND cost_est_usd < 2.00",
        "action": "auto_approve",
    },
    {
        "id": "sensitive_tags",
        "description": "Require human approval for sensitive operations",
        "condition": "tags include security, production, or deploy",
        "action": "require_human",
    },
    {
        "id": "high_cost",
        "description": "Require human approval for expensive tasks",
        "condition": "cost_est_usd > 5.00",
        "action": "require_human",
    },
    {
        "id": "high_confidence_low_cost",
        "description": "Auto-approve high-confidence cheap proposals",
        "condition": "auto_approve_threshold >= 80 AND cost_est_usd < 1.00",
        "action": "auto_approve",
    },
]

SENSITIVE_TAGS = {"security", "production", "deploy"}
CHEAP_AGENTS = {"coder_agent", "hacker_agent"}


def _load_config_rules() -> list:
    """Load approval rules from config.json ops_policy, falling back to defaults."""
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r") as f:
                config = json.load(f)
            rules = config.get("ops_policy", {}).get("auto_approve_rules")
            if rules:
                logger.info("Loaded %d approval rules from config", len(rules))
                return rules
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load config rules, using defaults: %s", exc)
    return DEFAULT_RULES


def notify_slack(message: str) -> bool:
    """POST a notification to the Slack report channel via the gateway."""
    token = os.environ.get("GATEWAY_AUTH_TOKEN", "")
    url = "http://localhost:18789/slack/report/send"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    try:
        resp = requests.post(url, json={"message": message}, headers=headers, timeout=5)
        if resp.ok:
            logger.info("Slack notification sent successfully")
            return True
        logger.warning("Slack notification failed: %s %s", resp.status_code, resp.text)
        return False
    except requests.RequestException as exc:
        logger.warning("Slack notification error: %s", exc)
        return False


def evaluate_proposal(proposal: dict, rules: list | None = None) -> dict:
    """
    Evaluate a proposal against approval rules.

    Args:
        proposal: dict with keys like cost_est_usd, tags, agent_pref,
                  auto_approve_threshold, task, project.
        rules: optional override; defaults to config or built-in rules.

    Returns:
        {"approved": bool, "reason": str, "rule_matched": str}
    """
    if rules is None:
        rules = _load_config_rules()

    cost = proposal.get("cost_est_usd", 0.0)
    tags = set(proposal.get("tags", []))
    agent = proposal.get("agent_pref", "")
    confidence = proposal.get("auto_approve_threshold", 0)

    has_sensitive = bool(tags & SENSITIVE_TAGS)

    # Rule 3: sensitive tags always require human (check first for safety)
    if has_sensitive:
        reason = f"Tags {tags & SENSITIVE_TAGS} require human approval"
        logger.info("DENIED (sensitive_tags): %s", reason)
        return {"approved": False, "reason": reason, "rule_matched": "sensitive_tags"}

    # Rule 4: high cost requires human
    if cost > 5.00:
        reason = f"Cost ${cost:.2f} exceeds $5.00 threshold"
        logger.info("DENIED (high_cost): %s", reason)
        return {"approved": False, "reason": reason, "rule_matched": "high_cost"}

    # Rule 1: low cost, non-security
    if cost < 0.50 and not has_sensitive:
        reason = f"Low cost ${cost:.2f} with no sensitive tags"
        logger.info("APPROVED (low_cost_non_security): %s", reason)
        return {"approved": True, "reason": reason, "rule_matched": "low_cost_non_security"}

    # Rule 2: cheap model agents under $2
    if agent in CHEAP_AGENTS and cost < 2.00:
        reason = f"Agent '{agent}' is a cheap model and cost ${cost:.2f} < $2.00"
        logger.info("APPROVED (cheap_model_moderate_cost): %s", reason)
        return {"approved": True, "reason": reason, "rule_matched": "cheap_model_moderate_cost"}

    # Rule 5: high confidence + low cost
    if confidence >= 80 and cost < 1.00:
        reason = f"Confidence {confidence}% >= 80 and cost ${cost:.2f} < $1.00"
        logger.info("APPROVED (high_confidence_low_cost): %s", reason)
        return {"approved": True, "reason": reason, "rule_matched": "high_confidence_low_cost"}

    # No rule matched — default to requiring human approval
    reason = f"No auto-approve rule matched (cost=${cost:.2f}, agent={agent}, confidence={confidence}%)"
    logger.info("DENIED (no_match): %s", reason)
    return {"approved": False, "reason": reason, "rule_matched": "none"}


def update_proposal_status(proposal: dict, status: str) -> dict:
    """Update proposal status in-place and log the transition."""
    old_status = proposal.get("status", "unknown")
    proposal["status"] = status
    proposal["status_updated_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(
        "Proposal '%s' status: %s -> %s",
        proposal.get("task", "unknown"),
        old_status,
        status,
    )
    return proposal


def auto_approve_and_execute(proposal: dict, rules: list | None = None) -> dict:
    """
    Evaluate a proposal; if approved, create a job and update status.

    Returns:
        {"decision": dict, "job": dict | None, "executed": bool}
    """
    decision = evaluate_proposal(proposal, rules)

    if decision["approved"]:
        update_proposal_status(proposal, "approved")
        job = create_job(
            project=proposal.get("project", "default"),
            task=proposal.get("task", "untitled"),
            priority=proposal.get("priority", "P1"),
        )
        update_proposal_status(proposal, "executing")
        logger.info("Auto-approved and created job %s for task: %s", job.id, proposal.get("task"))
        notify_slack(
            f"Auto-approved proposal: {proposal.get('task', 'untitled')} "
            f"(rule: {decision['rule_matched']}, job: {job.id})"
        )
        return {"decision": decision, "job": job.to_dict(), "executed": True}

    update_proposal_status(proposal, "pending_human_review")
    logger.info("Proposal requires human review: %s — %s", proposal.get("task"), decision["reason"])
    notify_slack(
        f"Proposal needs human approval: {proposal.get('task', 'untitled')} "
        f"— {decision['reason']}"
    )
    return {"decision": decision, "job": None, "executed": False}


def get_policy(rules: list | None = None) -> dict:
    """Return the current policy rules and configuration."""
    if rules is None:
        rules = _load_config_rules()
    return {
        "rules": rules,
        "sensitive_tags": sorted(SENSITIVE_TAGS),
        "cheap_agents": sorted(CHEAP_AGENTS),
        "config_path": str(CONFIG_PATH),
        "loaded_at": datetime.now(timezone.utc).isoformat(),
    }
