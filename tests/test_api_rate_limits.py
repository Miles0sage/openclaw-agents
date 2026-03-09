"""Tests for API auth/rate-limits module."""

from types import SimpleNamespace

import pytest

import api_auth
from api_auth import (
    QuotaError,
    RateLimitError,
    authenticate_request,
    check_job_quota,
    increment_usage,
    reset_rate_windows,
)


class _Query:
    def __init__(self, parent, table_name):
        self.parent = parent
        self.table_name = table_name
        self.filters = []
        self.limit_n = None
        self.select_args = None
        self._count = None

    def select(self, *args, **kwargs):
        self.select_args = (args, kwargs)
        if "count" in kwargs:
            self._count = self.parent.counts.get(self.table_name, 0)
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def in_(self, key, values):
        self.filters.append((key, tuple(values)))
        return self

    def limit(self, n):
        self.limit_n = n
        return self

    def order(self, *_args, **_kwargs):
        return self

    def update(self, data):
        self.parent.updated.setdefault(self.table_name, []).append(data)
        return self

    def rpc(self, name, params):
        self.parent.rpc_calls.append((name, params))
        return self

    def execute(self):
        return SimpleNamespace(
            data=self.parent.rows.get(self.table_name, []),
            count=self._count,
        )


class _Supabase:
    def __init__(self, rows=None, counts=None):
        self.rows = rows or {}
        self.counts = counts or {}
        self.updated = {}
        self.rpc_calls = []

    def table(self, name):
        return _Query(self, name)

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[]))


@pytest.mark.asyncio
async def test_valid_key_authenticates(monkeypatch):
    reset_rate_windows()
    sb = _Supabase(
        rows={
            "api_keys": [{
                "id": "k1",
                "key_hash": api_auth._hash_key("raw-key"),
                "is_active": True,
                "rate_limit_per_min": 10,
                "rate_limit_per_day": 1000,
                "max_concurrent_jobs": 3,
                "max_jobs_per_day": 100,
            }],
            "api_key_usage": [{"request_count": 0}],
        }
    )
    monkeypatch.setattr("supabase_client.get_client", lambda: sb)
    key = await authenticate_request("raw-key")
    assert key is not None
    assert key["id"] == "k1"


@pytest.mark.asyncio
async def test_invalid_key_returns_none(monkeypatch):
    reset_rate_windows()
    sb = _Supabase(rows={"api_keys": []})
    monkeypatch.setattr("supabase_client.get_client", lambda: sb)
    key = await authenticate_request("bad-key")
    assert key is None


@pytest.mark.asyncio
async def test_rate_limit_exceeded_raises(monkeypatch):
    reset_rate_windows()
    sb = _Supabase(
        rows={
            "api_keys": [{
                "id": "k2",
                "key_hash": api_auth._hash_key("raw-key"),
                "is_active": True,
                "rate_limit_per_min": 2,
                "rate_limit_per_day": 1000,
            }],
            "api_key_usage": [{"request_count": 0}],
        }
    )
    monkeypatch.setattr("supabase_client.get_client", lambda: sb)
    await authenticate_request("raw-key")
    await authenticate_request("raw-key")
    with pytest.raises(RateLimitError):
        await authenticate_request("raw-key")


@pytest.mark.asyncio
async def test_rate_window_resets_after_60s(monkeypatch):
    reset_rate_windows()
    sb = _Supabase(
        rows={
            "api_keys": [{
                "id": "k3",
                "key_hash": api_auth._hash_key("raw-key"),
                "is_active": True,
                "rate_limit_per_min": 1,
                "rate_limit_per_day": 1000,
            }],
            "api_key_usage": [{"request_count": 0}],
        }
    )
    monkeypatch.setattr("supabase_client.get_client", lambda: sb)
    times = iter([0, 0, 61, 61])
    monkeypatch.setattr("api_auth.time.time", lambda: next(times))
    await authenticate_request("raw-key")
    second = await authenticate_request("raw-key")
    assert second["id"] == "k3"


@pytest.mark.asyncio
async def test_concurrent_job_quota_blocks(monkeypatch):
    sb = _Supabase(
        rows={
            "api_key_usage": [{"job_count": 0}],
        },
        counts={"jobs": 3},
    )
    monkeypatch.setattr("supabase_client.get_client", lambda: sb)
    with pytest.raises(QuotaError):
        await check_job_quota({
            "id": "k4",
            "max_concurrent_jobs": 3,
            "max_jobs_per_day": 100,
        })


def test_increment_usage_is_nonfatal(monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr("supabase_client.get_client", _boom)
    increment_usage("key-1", cost_usd=1.2, is_job=True)
