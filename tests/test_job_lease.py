"""Tests for job_lease module."""

from unittest.mock import MagicMock

import pytest

from job_lease import (
    acquire_lease,
    mark_completed,
    mark_failed,
    reclaim_stale_leases,
)


class MockSupabase:
    """Minimal mock for supabase-py fluent API used in job_lease."""

    def __init__(self, update_returns_data=True):
        self._returns_data = update_returns_data
        self.last_update = None
        self.last_eq = []
        self.last_lt = []

    def table(self, _name):
        return self

    def update(self, data):
        self.last_update = data
        return self

    def eq(self, col, val):
        self.last_eq.append((col, val))
        return self

    def lt(self, col, val):
        self.last_lt.append((col, val))
        return self

    def execute(self):
        result = MagicMock()
        result.data = [{"id": "job-123"}] if self._returns_data else []
        return result


@pytest.mark.asyncio
async def test_acquire_lease_success():
    client = MockSupabase(update_returns_data=True)
    lease = await acquire_lease("job-123", client)
    assert lease is not None
    assert lease.job_id == "job-123"
    assert lease.execution_id
    await lease.release()


@pytest.mark.asyncio
async def test_acquire_lease_fails_when_already_taken():
    client = MockSupabase(update_returns_data=False)
    lease = await acquire_lease("job-123", client)
    assert lease is None


@pytest.mark.asyncio
async def test_mark_completed_success():
    client = MockSupabase(update_returns_data=True)
    ok = await mark_completed("job-123", "exec-uuid", {"output": "done"}, client)
    assert ok is True


@pytest.mark.asyncio
async def test_mark_completed_fails_when_lease_lost():
    client = MockSupabase(update_returns_data=False)
    ok = await mark_completed("job-123", "exec-uuid", {}, client)
    assert ok is False


@pytest.mark.asyncio
async def test_mark_failed_success():
    client = MockSupabase(update_returns_data=True)
    ok = await mark_failed("job-123", "exec-uuid", "timeout", client)
    assert ok is True


@pytest.mark.asyncio
async def test_reclaim_stale_leases_returns_count():
    client = MockSupabase(update_returns_data=True)
    count = await reclaim_stale_leases(client)
    assert count == 1


@pytest.mark.asyncio
async def test_reclaim_stale_leases_no_stale():
    client = MockSupabase(update_returns_data=False)
    count = await reclaim_stale_leases(client)
    assert count == 0


@pytest.mark.asyncio
async def test_double_acquire_second_returns_none():
    call_count = 0

    class RacingMockSupabase(MockSupabase):
        def execute(self):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.data = [{"id": "job-123"}] if call_count == 1 else []
            return result

    client1 = RacingMockSupabase()
    client2 = RacingMockSupabase()

    lease1 = await acquire_lease("job-123", client1)
    lease2 = await acquire_lease("job-123", client2)

    assert lease1 is not None
    assert lease2 is None
    await lease1.release()
