"""Tests for dead-letter queue module."""

from types import SimpleNamespace

from dead_letter_queue import (
    get_dlq_jobs,
    resolve_dlq,
    retry_from_dlq,
    send_to_dlq,
)


class _MockQuery:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.insert_payload = []
        self.update_payload = []
        self.filters = []
        self.order_calls = []
        self.limit_calls = []

    def insert(self, data):
        self.insert_payload.append(data)
        return self

    def update(self, data):
        self.update_payload.append(data)
        return self

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def order(self, key, desc=False):
        self.order_calls.append((key, desc))
        return self

    def limit(self, n):
        self.limit_calls.append(n)
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class _MockSupabase:
    def __init__(self, rows=None):
        self.query = _MockQuery(rows=rows)
        self.table_calls = []

    def table(self, name):
        self.table_calls.append(name)
        return self.query


def test_send_to_dlq_inserts_record(monkeypatch):
    sb = _MockSupabase()
    monkeypatch.setattr("dead_letter_queue._get_supabase", lambda: sb)
    ok = send_to_dlq(
        job_id="job-1",
        failure_reason="max_retries",
        last_error="boom",
        attempt_count=3,
        cost_total=1.234567,
    )
    assert ok is True
    assert "dead_letter_queue" in sb.table_calls
    assert len(sb.query.insert_payload) == 1
    payload = sb.query.insert_payload[0]
    assert payload["job_id"] == "job-1"
    assert payload["failure_reason"] == "max_retries"
    assert payload["attempt_count"] == 3


def test_send_to_dlq_is_nonfatal_on_supabase_error(monkeypatch):
    def _boom():
        raise RuntimeError("supabase down")

    monkeypatch.setattr("dead_letter_queue._get_supabase", _boom)
    ok = send_to_dlq("job-2", "unrecoverable_error")
    assert ok is False


def test_retry_from_dlq_requeues_job(monkeypatch):
    sb = _MockSupabase(rows=[{"id": "dlq-1", "retry_count": 2}])
    calls = []
    monkeypatch.setattr("dead_letter_queue._get_supabase", lambda: sb)
    monkeypatch.setattr("job_manager.update_job_status", lambda *a, **k: calls.append((a, k)) or True)

    ok = retry_from_dlq("job-3")
    assert ok is True
    assert len(sb.query.update_payload) >= 1
    assert any(c[0][0] == "job-3" and c[0][1] == "pending" for c in calls)


def test_get_dlq_jobs_filters_unresolved(monkeypatch):
    rows = [{"job_id": "a", "resolved": False}, {"job_id": "b", "resolved": True}]
    sb = _MockSupabase(rows=rows)
    monkeypatch.setattr("dead_letter_queue._get_supabase", lambda: sb)

    result = get_dlq_jobs(limit=10, unresolved_only=True)
    assert result == rows
    assert ("resolved", False) in sb.query.filters


def test_resolve_dlq_marks_resolved(monkeypatch):
    sb = _MockSupabase(rows=[{"id": "dlq-1"}])
    monkeypatch.setattr("dead_letter_queue._get_supabase", lambda: sb)
    ok = resolve_dlq("job-4")
    assert ok is True
    assert len(sb.query.update_payload) == 1
    payload = sb.query.update_payload[0]
    assert payload["resolved"] is True
    assert "resolved_at" in payload
