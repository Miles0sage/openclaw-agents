"""
OpenClaw MCP Billing Middleware — Stripe usage-based metering.

Tiers:
  - free:  100 calls/day
  - pro:   10,000 calls/day  ($29/mo)
  - business: 100,000 calls/day ($149/mo)
  - unlimited: no cap ($499/mo)
"""

from __future__ import annotations

import os
import time
import json
import hashlib
from pathlib import Path
from typing import Any
from datetime import datetime, timezone, date

import stripe

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

STRIPE_SECRET = os.getenv("STRIPE_SECRET_KEY", "")
BILLING_DATA_DIR = Path(os.getenv("MCP_BILLING_DIR", "./data/mcp_billing"))
BILLING_DATA_DIR.mkdir(parents=True, exist_ok=True)

TIER_LIMITS = {
    "free": 100,
    "pro": 10_000,
    "business": 100_000,
    "unlimited": float("inf"),
}

TIER_PRICES = {
    "free": 0,
    "pro": 29,
    "business": 149,
    "unlimited": 499,
}


# ---------------------------------------------------------------------------
# Usage tracker (file-backed, no external DB needed)
# ---------------------------------------------------------------------------

class UsageTracker:
    """Per-API-key daily usage tracker with file-based persistence."""

    def __init__(self, server_name: str):
        self.server_name = server_name
        self._dir = BILLING_DATA_DIR / server_name
        self._dir.mkdir(parents=True, exist_ok=True)

    def _key_hash(self, api_key: str) -> str:
        return hashlib.sha256(api_key.encode()).hexdigest()[:16]

    def _usage_file(self, key_hash: str, day: str) -> Path:
        return self._dir / f"{key_hash}_{day}.json"

    def _load_usage(self, api_key: str) -> dict:
        today = date.today().isoformat()
        kh = self._key_hash(api_key)
        f = self._usage_file(kh, today)
        if f.exists():
            return json.loads(f.read_text())
        return {"key_hash": kh, "date": today, "calls": 0, "tools": {}}

    def _save_usage(self, api_key: str, data: dict) -> None:
        today = date.today().isoformat()
        kh = self._key_hash(api_key)
        f = self._usage_file(kh, today)
        f.write_text(json.dumps(data, indent=2))

    def record_call(self, api_key: str, tool_name: str) -> dict:
        """Record a tool call. Returns usage info."""
        data = self._load_usage(api_key)
        data["calls"] += 1
        data["tools"][tool_name] = data["tools"].get(tool_name, 0) + 1
        data["last_call"] = datetime.now(timezone.utc).isoformat()
        self._save_usage(api_key, data)
        return data

    def get_usage(self, api_key: str) -> dict:
        return self._load_usage(api_key)

    def check_limit(self, api_key: str, tier: str = "free") -> tuple[bool, int, int]:
        """Check if under limit. Returns (allowed, used, limit)."""
        data = self._load_usage(api_key)
        limit = TIER_LIMITS.get(tier, 100)
        return data["calls"] < limit, data["calls"], int(limit)


# ---------------------------------------------------------------------------
# API key management (simple file-backed)
# ---------------------------------------------------------------------------

class APIKeyManager:
    """Manage API keys and tiers."""

    def __init__(self, server_name: str):
        self._file = BILLING_DATA_DIR / server_name / "api_keys.json"
        self._file.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        if self._file.exists():
            return json.loads(self._file.read_text())
        return {}

    def _save(self, data: dict) -> None:
        self._file.write_text(json.dumps(data, indent=2))

    def create_key(self, owner: str, tier: str = "free") -> str:
        """Create a new API key."""
        key = f"oc_{self._file.parent.name}_{hashlib.sha256(f'{owner}{time.time()}'.encode()).hexdigest()[:24]}"
        data = self._load()
        data[key] = {
            "owner": owner,
            "tier": tier,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "active": True,
        }
        self._save(data)
        return key

    def validate_key(self, api_key: str) -> tuple[bool, str]:
        """Validate key, return (valid, tier)."""
        data = self._load()
        if api_key in data and data[api_key].get("active"):
            return True, data[api_key].get("tier", "free")
        return False, "free"

    def get_key_info(self, api_key: str) -> dict | None:
        data = self._load()
        return data.get(api_key)

    def revoke_key(self, api_key: str) -> bool:
        data = self._load()
        if api_key in data:
            data[api_key]["active"] = False
            self._save(data)
            return True
        return False


# ---------------------------------------------------------------------------
# Stripe metered billing (optional — works without Stripe too)
# ---------------------------------------------------------------------------

def report_stripe_usage(api_key: str, quantity: int, subscription_item_id: str | None = None) -> bool:
    """Report usage to Stripe for metered billing."""
    if not STRIPE_SECRET or not subscription_item_id:
        return False
    try:
        stripe.api_key = STRIPE_SECRET
        stripe.SubscriptionItem.create_usage_record(
            subscription_item_id,
            quantity=quantity,
            timestamp=int(time.time()),
            action="increment",
        )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Convenience: billing-aware tool wrapper
# ---------------------------------------------------------------------------

def billing_check(tracker: UsageTracker, key_mgr: APIKeyManager, api_key: str, tool_name: str) -> dict | None:
    """
    Run before each tool call. Returns None if OK, or error dict if blocked.
    Also records the call if allowed.
    """
    if not api_key:
        # No key = free tier anonymous
        api_key = "anonymous"
        tier = "free"
    else:
        valid, tier = key_mgr.validate_key(api_key)
        if not valid:
            return {"error": "invalid_api_key", "message": "Invalid or revoked API key."}

    allowed, used, limit = tracker.check_limit(api_key, tier)
    if not allowed:
        return {
            "error": "rate_limit_exceeded",
            "message": f"Daily limit reached ({used}/{limit}). Upgrade to Pro for 10,000 calls/day.",
            "tier": tier,
            "used": used,
            "limit": limit,
            "upgrade_url": "https://openclaw.dev/pricing",
        }

    tracker.record_call(api_key, tool_name)
    return None
