"""
API key authentication + rate limiting middleware helpers for OpenClaw gateway.
"""

import hashlib
import logging
import time
from collections import defaultdict, deque
from datetime import date, datetime, timezone
from typing import Optional

logger = logging.getLogger("openclaw.api_auth")

# In-memory sliding window: key_hash -> timestamps in the last minute.
_rate_windows: dict[str, deque] = defaultdict(deque)


class RateLimitError(Exception):
    """Raised when a per-key rate limit is exceeded."""


class QuotaError(Exception):
    """Raised when a per-key quota is exceeded."""


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _check_rate_window(key_hash: str, limit_per_min: int) -> bool:
    """Sliding 60s window rate check. Returns True if request is allowed."""
    now = time.time()
    cutoff = now - 60
    window = _rate_windows[key_hash]
    while window and window[0] < cutoff:
        window.popleft()
    if len(window) >= max(1, int(limit_per_min or 1)):
        return False
    window.append(now)
    return True


def reset_rate_windows():
    """Test helper: clears all in-memory rate windows."""
    _rate_windows.clear()


async def authenticate_request(raw_key: str) -> Optional[dict]:
    """
    Validate API key and return key record if valid.

    Returns None if key is invalid/inactive.
    Raises RateLimitError on rate limit breach.
    """
    if not raw_key:
        return None

    key_hash = _hash_key(raw_key)
    try:
        from supabase_client import get_client
        sb = get_client()
        if not sb:
            return None
        result = (
            sb.table("api_keys")
            .select("*")
            .eq("key_hash", key_hash)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        key_record = result.data[0]
    except Exception as exc:
        logger.error("api_auth: Supabase lookup failed: %s", exc)
        return None

    if not _check_rate_window(key_hash, int(key_record.get("rate_limit_per_min", 60) or 60)):
        raise RateLimitError(
            f"Rate limit exceeded: {int(key_record.get('rate_limit_per_min', 60) or 60)} req/min"
        )

    # Sustained/day cap from durable counter (best-effort enforce).
    try:
        today = date.today().isoformat()
        usage = (
            sb.table("api_key_usage")
            .select("request_count")
            .eq("key_id", key_record["id"])
            .eq("date", today)
            .limit(1)
            .execute()
        )
        used_today = int(usage.data[0].get("request_count", 0) or 0) if usage.data else 0
        day_limit = int(key_record.get("rate_limit_per_day", 1000) or 1000)
        if used_today >= day_limit:
            raise RateLimitError(f"Daily rate limit exceeded: {day_limit} req/day")
    except RateLimitError:
        raise
    except Exception as exc:
        logger.warning("api_auth: daily request check failed (allowing): %s", exc)

    try:
        sb.table("api_keys").update({
            "last_used_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", key_record["id"]).execute()
    except Exception:
        pass

    return key_record


async def check_job_quota(key_record: dict) -> bool:
    """Check concurrent-job and daily-job quotas for a key."""
    try:
        from supabase_client import get_client
        sb = get_client()
        if not sb:
            return True

        running = (
            sb.table("jobs")
            .select("id", count="exact")
            .eq("api_key_id", key_record["id"])
            .in_("status", ["pending", "running"])
            .execute()
        )
        concurrent = int(getattr(running, "count", 0) or 0)
        max_concurrent = int(key_record.get("max_concurrent_jobs", 3) or 3)
        if concurrent >= max_concurrent:
            raise QuotaError(f"Concurrent job limit reached: {max_concurrent}")

        today = date.today().isoformat()
        usage = (
            sb.table("api_key_usage")
            .select("job_count")
            .eq("key_id", key_record["id"])
            .eq("date", today)
            .limit(1)
            .execute()
        )
        jobs_today = int(usage.data[0].get("job_count", 0) or 0) if usage.data else 0
        max_jobs = int(key_record.get("max_jobs_per_day", 100) or 100)
        if jobs_today >= max_jobs:
            raise QuotaError(f"Daily job quota reached: {max_jobs}")
        return True
    except (RateLimitError, QuotaError):
        raise
    except Exception as exc:
        logger.warning("api_auth: quota check failed (allowing): %s", exc)
        return True


def increment_usage(key_id: str, cost_usd: float = 0.0, is_job: bool = False):
    """Increment request + optional job counters for a key. Non-fatal."""
    if not key_id:
        return
    try:
        from supabase_client import get_client
        sb = get_client()
        if not sb:
            return
        sb.rpc("increment_api_usage", {
            "p_key_id": key_id,
            "p_date": date.today().isoformat(),
            "p_requests": 1,
            "p_jobs": 1 if is_job else 0,
            "p_cost": round(float(cost_usd or 0.0), 6),
        }).execute()
    except Exception as exc:
        logger.debug("api_auth: usage increment failed (non-fatal): %s", exc)
