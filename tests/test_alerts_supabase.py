"""Tests for Supabase-backed alert persistence."""

from unittest.mock import MagicMock, patch

from runbook import Runbook


class MockSupabase:
    def __init__(self):
        self.tables = []
        self.upserted = []
        self.updated = []
        self.filters = []

    def table(self, name):
        self.tables.append(name)
        return self

    def upsert(self, data):
        self.upserted.append(data)
        return self

    def update(self, data):
        self.updated.append(data)
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def execute(self):
        result = MagicMock()
        result.data = []
        return result


def test_fire_upserts_to_supabase(tmp_path):
    sb = MockSupabase()
    rb = Runbook(alert_file=str(tmp_path / "alerts.jsonl"))
    with patch("runbook.get_supabase", return_value=sb):
        alert = rb.fire("job_failed_permanent", job_id="job-test", message="test")
    assert "alerts" in sb.tables
    assert len(sb.upserted) >= 1
    assert sb.upserted[0]["failure_type"] == "job_failed_permanent"
    assert sb.upserted[0]["id"] == alert.id


def test_acknowledge_updates_supabase(tmp_path):
    sb = MockSupabase()
    rb = Runbook(alert_file=str(tmp_path / "alerts.jsonl"))
    with patch("runbook.get_supabase", return_value=sb):
        alert = rb.fire("job_failed_permanent", job_id="job-ack-test", message="ack test")
        assert rb.acknowledge(alert.id) is True
    assert len(sb.updated) >= 1
    assert sb.updated[-1]["acknowledged"] is True
    assert ("id", alert.id) in sb.filters


def test_supabase_failure_is_nonfatal(tmp_path):
    path = tmp_path / "alerts.jsonl"
    rb = Runbook(alert_file=str(path))
    with patch("runbook.get_supabase", side_effect=Exception("Supabase down")):
        rb.fire("job_failed_permanent", job_id="job-nofatal", message="test")
    assert path.exists()
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
