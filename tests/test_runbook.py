"""Tests for runbook module."""

import json
from pathlib import Path

from runbook import (
    AlertSeverity,
    Runbook,
    get_runbook,
    init_runbook,
)


def test_fire_alert_with_known_failure(tmp_path):
    rb = Runbook(alert_file=str(tmp_path / "alerts.jsonl"))
    alert = rb.fire("quality_fail", job_id="job-1", agent_key="coder_agent", message="score too low")
    assert alert.failure_type == "quality_fail"
    assert alert.severity == AlertSeverity.WARNING
    assert alert.title
    assert len(alert.diagnostic_steps) > 0


def test_fire_unknown_failure_defaults_to_warning(tmp_path):
    rb = Runbook(alert_file=str(tmp_path / "alerts.jsonl"))
    alert = rb.fire("unknown_failure", job_id="job-2", message="unknown")
    assert alert.severity == AlertSeverity.WARNING
    assert "Unknown failure" in alert.title


def test_get_alerts_limit_and_filters(tmp_path):
    rb = Runbook(alert_file=str(tmp_path / "alerts.jsonl"))
    rb.fire("quality_fail", job_id="job-a", message="a")
    rb.fire("circuit_open", job_id="job-b", message="b")
    rb.fire("quality_fail", job_id="job-b", message="c")

    only_warning = rb.get_alerts(limit=10, severity=AlertSeverity.WARNING)
    assert all(a["severity"] == AlertSeverity.WARNING for a in only_warning)

    only_job_b = rb.get_alerts(limit=10, job_id="job-b")
    assert len(only_job_b) == 2

    limited = rb.get_alerts(limit=1)
    assert len(limited) == 1


def test_acknowledge_alert(tmp_path):
    rb = Runbook(alert_file=str(tmp_path / "alerts.jsonl"))
    alert = rb.fire("quality_fail", job_id="job-3", message="needs review")
    assert rb.acknowledge(alert.id) is True
    alerts = rb.get_alerts(limit=10)
    assert any(a["id"] == alert.id and a["acknowledged"] for a in alerts)
    assert rb.acknowledge("missing-id") is False


def test_get_runbook_entry_and_all_entries(tmp_path):
    rb = Runbook(alert_file=str(tmp_path / "alerts.jsonl"))
    entry = rb.get_runbook_entry("circuit_open")
    assert entry is not None
    assert entry["severity"] == AlertSeverity.CRITICAL
    assert rb.get_runbook_entry("does_not_exist") is None
    all_entries = rb.get_all_runbook_entries()
    assert len(all_entries) >= 8


def test_persist_and_reload(tmp_path):
    path = tmp_path / "alerts.jsonl"
    rb = Runbook(alert_file=str(path))
    rb.fire("quality_fail", job_id="job-4", message="persist me")
    rb2 = Runbook(alert_file=str(path))
    alerts = rb2.get_alerts(limit=10)
    assert len(alerts) == 1
    assert alerts[0]["job_id"] == "job-4"


def test_trim_old_alerts(tmp_path):
    rb = Runbook(max_alerts=2, alert_file=str(tmp_path / "alerts.jsonl"))
    rb.fire("quality_fail", job_id="j1", message="1")
    rb.fire("quality_fail", job_id="j2", message="2")
    rb.fire("quality_fail", job_id="j3", message="3")
    alerts = rb.get_alerts(limit=10)
    assert len(alerts) == 2
    assert alerts[0]["job_id"] == "j2"
    assert alerts[1]["job_id"] == "j3"


def test_register_webhook_deduplicates(tmp_path):
    rb = Runbook(alert_file=str(tmp_path / "alerts.jsonl"))
    rb.register_webhook("https://example.test/hook")
    rb.register_webhook("https://example.test/hook")
    assert len(rb._webhooks) == 1


def test_critical_alert_sends_webhook(tmp_path, monkeypatch):
    sent = {"count": 0, "payload": b""}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fake_urlopen(req, timeout=0):  # noqa: ARG001
        sent["count"] += 1
        sent["payload"] = req.data or b""
        return _Resp()

    monkeypatch.setattr("runbook.urllib.request.urlopen", _fake_urlopen)

    rb = Runbook(alert_file=str(tmp_path / "alerts.jsonl"))
    rb.register_webhook("https://example.test/hook")
    rb.fire("circuit_open", job_id="job-5", message="critical")
    assert sent["count"] == 1
    assert b"circuit_open" in sent["payload"]


def test_get_stats_counts(tmp_path):
    rb = Runbook(alert_file=str(tmp_path / "alerts.jsonl"))
    rb.fire("quality_fail", job_id="s1", message="warn")
    rb.fire("circuit_open", job_id="s2", message="critical")
    stats = rb.get_stats()
    assert stats["fired"] == 2
    assert stats["warning"] == 1
    assert stats["critical"] == 1


def test_alert_file_is_valid_jsonl(tmp_path):
    path = tmp_path / "alerts.jsonl"
    rb = Runbook(alert_file=str(path))
    rb.fire("quality_fail", job_id="j", message="line1")
    rb.fire("quality_fail", job_id="j", message="line2")

    with open(path, "r", encoding="utf-8") as handle:
        lines = [line.strip() for line in handle if line.strip()]
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert isinstance(parsed, dict)
        assert "id" in parsed


def test_singleton_init_and_get(tmp_path):
    path = tmp_path / "alerts.jsonl"
    r1 = init_runbook(alert_file=str(path))
    r2 = get_runbook()
    assert r1 is r2
    r1.fire("quality_fail", job_id="singleton", message="ok")
    assert len(r2.get_alerts(limit=10)) == 1
