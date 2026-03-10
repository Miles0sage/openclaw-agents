"""
Supabase Client for OpenClaw
=============================
Shared client instance used by all modules (job_manager, memory_manager,
cost tracking, reflexion, etc.) to access the Supabase database.

Usage:
    from supabase_client import get_client, supabase_request

    # Direct client access (supabase-py)
    sb = get_client()
    sb.table("jobs").select("*").execute()

    # Lower-level HTTP (for bulk ops, upserts, RPC)
    supabase_request("POST", "/rest/v1/jobs", json={...})
"""

import os
import logging
import httpx
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

logger = logging.getLogger("supabase_client")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


def _headers(extra: dict | None = None) -> dict:
    """Standard Supabase headers with service role auth."""
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


@lru_cache(maxsize=1)
def get_client():
    """Get a cached supabase-py client instance."""
    try:
        from supabase import create_client
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except ImportError:
        logger.warning("supabase-py not installed, using HTTP client only")
        return None
    except Exception as e:
        logger.error(f"Failed to create Supabase client: {e}")
        return None


def supabase_request(method: str, path: str, json: dict | list | None = None,
                     params: dict | None = None, headers: dict | None = None,
                     timeout: int = 15) -> httpx.Response:
    """Make a direct HTTP request to Supabase REST API."""
    url = f"{SUPABASE_URL}{path}"
    h = _headers(headers)
    return httpx.request(method, url, json=json, params=params, headers=h, timeout=timeout)


def table_insert(table: str, data: dict | list, upsert: bool = False) -> dict | list | None:
    """Insert row(s) into a table. Returns inserted data."""
    h = {"Prefer": "return=representation"}
    if upsert:
        h["Prefer"] = "return=representation,resolution=merge-duplicates"
    resp = supabase_request("POST", f"/rest/v1/{table}", json=data, headers=h)
    if resp.status_code in (200, 201):
        return resp.json()
    logger.error(f"Insert into {table} failed: {resp.status_code} {resp.text[:200]}")
    return None


def table_select(table: str, query: str = "", limit: int = 1000) -> list:
    """Select rows from a table. query is PostgREST filter string."""
    # Encode '+' as %2B to prevent URL decoding as space (e.g. in +00:00 timezone offsets)
    if query:
        query = query.replace("+", "%2B")
    path = f"/rest/v1/{table}?{query}&limit={limit}" if query else f"/rest/v1/{table}?limit={limit}"
    resp = supabase_request("GET", path)
    if resp.status_code == 200:
        return resp.json()
    logger.error(f"Select from {table} failed: {resp.status_code} {resp.text[:200]}")
    return []


def table_count(table: str, query: str = "", *, select: str = "id") -> int:
    """
    Count rows matching a PostgREST filter string.

    Uses Prefer: count=exact and parses the Content-Range header (e.g. "0-0/123").
    """
    # Encode '+' as %2B to prevent URL decoding as space
    if query:
        query = query.replace("+", "%2B")

    # We only need a minimal select for PostgREST to count.
    # Add limit=1 to avoid fetching large bodies.
    path = f"/rest/v1/{table}?{query}&select={select}&limit=1" if query else f"/rest/v1/{table}?select={select}&limit=1"
    resp = supabase_request("GET", path, headers={"Prefer": "count=exact"})
    if resp.status_code != 200:
        logger.error(f"Count {table} failed: {resp.status_code} {resp.text[:200]}")
        return 0
    cr = resp.headers.get("content-range") or resp.headers.get("Content-Range") or ""
    if "/" not in cr:
        return 0
    try:
        return int(cr.split("/", 1)[1])
    except Exception:
        return 0


def table_update(table: str, match: str, data: dict) -> dict | list | None:
    """Update rows matching a PostgREST filter. e.g. match='id=eq.abc123'"""
    h = {"Prefer": "return=representation"}
    resp = supabase_request("PATCH", f"/rest/v1/{table}?{match}", json=data, headers=h)
    if resp.status_code == 200:
        return resp.json()
    logger.error(f"Update {table} failed: {resp.status_code} {resp.text[:200]}")
    return None


def table_delete(table: str, match: str) -> bool:
    """Delete rows matching a PostgREST filter."""
    resp = supabase_request("DELETE", f"/rest/v1/{table}?{match}")
    return resp.status_code == 204


def rpc(function_name: str, params: dict | None = None) -> dict | None:
    """Call a Postgres function via PostgREST RPC."""
    resp = supabase_request("POST", f"/rest/v1/rpc/{function_name}", json=params or {})
    if resp.status_code == 200:
        return resp.json()
    logger.error(f"RPC {function_name} failed: {resp.status_code} {resp.text[:200]}")
    return None


def is_connected() -> bool:
    """Check if Supabase connection is healthy.
    
    Performs a health check by making a lightweight GET request to the Supabase
    REST API with a 5-second timeout. Returns True if the connection is healthy
    (HTTP 200), False if the request fails or times out.
    
    Returns:
        bool: True if connection is healthy, False on any error or timeout.
    """
    try:
        resp = supabase_request("GET", "/rest/v1/jobs?limit=0", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False
