"""
Proposal Engine for OpenClaw Closed-Loop System.

Creates, validates, stores, and manages proposals with cost estimation
based on model pricing. Thread-safe JSONL storage.
"""

import json
import os
import uuid
import fcntl
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")
PROPOSALS_FILE = os.path.join(DATA_DIR, "jobs", "proposals.jsonl")

# Per 1M tokens pricing (USD)
MODEL_PRICING = {
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "kimi-2.5": {"input": 0.14, "output": 0.28},
    "kimi": {"input": 0.27, "output": 0.68},
}

VALID_STATUSES = {"pending", "approved", "rejected", "executed"}
VALID_AGENTS = set(MODEL_PRICING.keys())


@dataclass
class Proposal:
    id: str
    title: str
    description: str
    agent_pref: str
    tokens_est: int
    tags: list
    cost_est_usd: float
    status: str
    created_at: str
    auto_approve_threshold: int
    status_reason: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> "Proposal":
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            agent_pref=data["agent_pref"],
            tokens_est=data["tokens_est"],
            tags=data["tags"],
            cost_est_usd=data["cost_est_usd"],
            status=data["status"],
            created_at=data["created_at"],
            auto_approve_threshold=data["auto_approve_threshold"],
            status_reason=data.get("status_reason"),
            updated_at=data.get("updated_at"),
        )


def _generate_proposal_id() -> str:
    """Generate a unique proposal ID: prop-YYYYMMDD-HHMMSS-<8hex>."""
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d-%H%M%S")
    hex_suffix = uuid.uuid4().hex[:8]
    return f"prop-{ts}-{hex_suffix}"


def _validate_inputs(
    title: str,
    description: str,
    agent_pref: str,
    tokens_est: int,
    tags: list,
    auto_approve_threshold: int,
) -> None:
    """Validate all proposal inputs. Raises ValueError on invalid data."""
    if not title or not isinstance(title, str):
        raise ValueError("title must be a non-empty string")
    if len(title) > 200:
        raise ValueError("title must be 200 characters or fewer")
    if not description or not isinstance(description, str):
        raise ValueError("description must be a non-empty string")
    if agent_pref not in VALID_AGENTS:
        raise ValueError(f"agent_pref must be one of {sorted(VALID_AGENTS)}")
    if not isinstance(tokens_est, int) or tokens_est <= 0:
        raise ValueError("tokens_est must be a positive integer")
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ValueError("tags must be a list of strings")
    if not isinstance(auto_approve_threshold, int) or not (0 <= auto_approve_threshold <= 100):
        raise ValueError("auto_approve_threshold must be an integer between 0 and 100")


def estimate_cost(agent_pref: str, tokens_est: int) -> float:
    """Estimate cost in USD for a given agent and token count.

    Assumes a 60/40 input/output split of total tokens.
    Returns cost rounded to 6 decimal places.
    """
    if agent_pref not in MODEL_PRICING:
        raise ValueError(f"Unknown agent: {agent_pref}. Valid: {sorted(VALID_AGENTS)}")
    if not isinstance(tokens_est, int) or tokens_est <= 0:
        raise ValueError("tokens_est must be a positive integer")

    pricing = MODEL_PRICING[agent_pref]
    input_tokens = int(tokens_est * 0.6)
    output_tokens = tokens_est - input_tokens

    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)


def _append_proposal(proposal: Proposal) -> None:
    """Append a proposal to the JSONL file with file locking."""
    line = json.dumps(proposal.to_dict(), separators=(",", ":")) + "\n"
    fd = os.open(PROPOSALS_FILE, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, line.encode("utf-8"))
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read_all_proposals() -> list[Proposal]:
    """Read all proposals from the JSONL file."""
    if not os.path.exists(PROPOSALS_FILE):
        return []
    proposals = []
    with open(PROPOSALS_FILE, "r", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        for line in f:
            line = line.strip()
            if line:
                proposals.append(Proposal.from_dict(json.loads(line)))
        fcntl.flock(f, fcntl.LOCK_UN)
    return proposals


def _rewrite_all_proposals(proposals: list[Proposal]) -> None:
    """Rewrite the entire JSONL file atomically."""
    tmp_path = PROPOSALS_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        for p in proposals:
            f.write(json.dumps(p.to_dict(), separators=(",", ":")) + "\n")
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(tmp_path, PROPOSALS_FILE)


def create_proposal(
    title: str,
    description: str,
    agent_pref: str,
    tokens_est: int,
    tags: list,
    auto_approve_threshold: int = 50,
) -> Proposal:
    """Create a new proposal, validate inputs, estimate cost, and persist.

    Returns the created Proposal object.
    """
    _validate_inputs(title, description, agent_pref, tokens_est, tags, auto_approve_threshold)

    cost = estimate_cost(agent_pref, tokens_est)
    proposal = Proposal(
        id=_generate_proposal_id(),
        title=title,
        description=description,
        agent_pref=agent_pref,
        tokens_est=tokens_est,
        tags=tags,
        cost_est_usd=cost,
        status="pending",
        created_at=datetime.now(timezone.utc).isoformat(),
        auto_approve_threshold=auto_approve_threshold,
    )

    _append_proposal(proposal)
    logger.info("Created proposal %s (agent=%s, cost=$%.6f)", proposal.id, agent_pref, cost)
    return proposal


def get_proposal(proposal_id: str) -> Optional[Proposal]:
    """Fetch a single proposal by ID. Returns None if not found."""
    for p in _read_all_proposals():
        if p.id == proposal_id:
            return p
    return None


def list_proposals(status: Optional[str] = None) -> list[Proposal]:
    """List all proposals, optionally filtered by status."""
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"Invalid status filter: {status}. Valid: {sorted(VALID_STATUSES)}")
    proposals = _read_all_proposals()
    if status is not None:
        proposals = [p for p in proposals if p.status == status]
    return proposals


def update_proposal_status(
    proposal_id: str,
    new_status: str,
    reason: Optional[str] = None,
) -> Proposal:
    """Update a proposal's status. Returns the updated Proposal.

    Raises ValueError for invalid status or KeyError if proposal not found.
    """
    if new_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {new_status}. Valid: {sorted(VALID_STATUSES)}")

    proposals = _read_all_proposals()
    target = None
    for p in proposals:
        if p.id == proposal_id:
            target = p
            break

    if target is None:
        raise KeyError(f"Proposal not found: {proposal_id}")

    target.status = new_status
    target.status_reason = reason
    target.updated_at = datetime.now(timezone.utc).isoformat()

    _rewrite_all_proposals(proposals)
    logger.info("Updated proposal %s -> %s (reason=%s)", proposal_id, new_status, reason)
    return target
