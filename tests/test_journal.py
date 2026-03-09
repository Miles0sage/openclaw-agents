"""Tests for append-only step journal (journal.py)."""
import json
import os
import tempfile
import threading
import pytest
from journal import (
    StepJournal,
    JournalEntry,
    init_journal,
    get_journal,
    DEFAULT_TRACE_DIR,
)


@pytest.fixture
def tmp_trace_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def journal(tmp_trace_dir):
    return StepJournal(trace_dir=tmp_trace_dir)


def test_log_creates_file(journal):
    journal.log("job-1", "job_start", data={"agent": "coder"})
    path = journal._path("job-1")
    assert path.exists()
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["job_id"] == "job-1"
    assert obj["event_type"] == "job_start"
    assert obj["data"]["agent"] == "coder"


def test_log_append_only(journal):
    journal.log("job-2", "phase_start", phase="research")
    journal.log("job-2", "phase_end", phase="research", duration_ms=100.0)
    entries = journal.get_entries("job-2")
    assert len(entries) == 2
    assert entries[0].event_type == "phase_start"
    assert entries[1].event_type == "phase_end"
    assert entries[1].duration_ms == 100.0


def test_get_entries_filter_by_event_type(journal):
    journal.log("job-3", "tool_call", data={"tool": "read_file"})
    journal.log("job-3", "tool_result", data={"ok": True})
    journal.log("job-3", "error", data={"message": "x"})
    all_entries = journal.get_entries("job-3")
    assert len(all_entries) == 3
    errors = journal.get_entries("job-3", event_type="error")
    assert len(errors) == 1
    assert errors[0].data.get("message") == "x"


def test_get_last_entry(journal):
    journal.log("job-4", "phase_start", phase="execute")
    journal.log("job-4", "checkpoint", phase="execute", step_index=2)
    last = journal.get_last_entry("job-4")
    assert last is not None
    assert last.event_type == "checkpoint"
    assert last.step_index == 2


def test_get_last_entry_empty(journal):
    assert journal.get_last_entry("job-none") is None


def test_get_summary(journal):
    journal.log("job-5", "phase_start", phase="research")
    journal.log("job-5", "phase_end", phase="research", duration_ms=50.0)
    journal.log("job-5", "error", data={})
    summary = journal.get_summary("job-5")
    assert summary["job_id"] == "job-5"
    assert summary["total_entries"] == 3
    assert summary["error_count"] == 1
    assert "research" in summary["phases_seen"]
    assert summary["last_event"] == "error"
    assert summary["total_duration_ms"] == 50.0


def test_clear(journal):
    journal.log("job-6", "job_start")
    assert journal._path("job-6").exists()
    journal.clear("job-6")
    assert not journal._path("job-6").exists()
    assert journal.get_entries("job-6") == []


def test_rotate(journal):
    for i in range(15):
        journal.log("job-7", "tool_call", data={"i": i})
    entries_before = journal.get_entries("job-7")
    assert len(entries_before) == 15
    journal.rotate("job-7", max_entries=10)
    entries_after = journal.get_entries("job-7")
    assert len(entries_after) == 5  # 10//2 = 5 kept
    assert entries_after[0].data.get("i") == 10


def test_rotate_archives_trimmed_entries(journal):
    for i in range(12):
        journal.log("job-7a", "tool_call", data={"i": i})
    journal.rotate("job-7a", max_entries=10)
    archives = list(journal._path("job-7a").parent.glob("job-7a.archive.*.jsonl"))
    assert len(archives) == 1
    archived_lines = [ln for ln in archives[0].read_text().splitlines() if ln.strip()]
    assert len(archived_lines) == 7
    first = json.loads(archived_lines[0])
    assert first["data"]["i"] == 0


def test_rotate_no_op_when_under_max(journal):
    journal.log("job-8", "job_start")
    journal.rotate("job-8", max_entries=100)
    assert len(journal.get_entries("job-8")) == 1


def test_concurrent_writes(journal):
    def write_many(job_id: str, n: int):
        for i in range(n):
            journal.log(job_id, "tool_call", data={"thread": job_id, "i": i})

    t1 = threading.Thread(target=write_many, args=("job-concurrent", 20))
    t2 = threading.Thread(target=write_many, args=("job-concurrent", 20))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    entries = journal.get_entries("job-concurrent")
    assert len(entries) == 40


def test_empty_journal_get_entries(journal):
    assert journal.get_entries("job-empty") == []


def test_safe_job_id_filename(journal):
    journal.log("job/with/slashes", "job_start")
    path = journal._path("job/with/slashes")
    assert path.exists()
    entries = journal.get_entries("job/with/slashes")
    assert len(entries) == 1


def test_entry_to_jsonl_roundtrip(journal):
    journal.log("job-9", "quality_score", data={"score": 0.85})
    raw = journal._path("job-9").read_text().strip()
    obj = json.loads(raw)
    assert obj["event_type"] == "quality_score"
    assert obj["data"]["score"] == 0.85


def test_init_and_get_singleton(tmp_trace_dir):
    j1 = init_journal(trace_dir=tmp_trace_dir)
    j2 = get_journal()
    assert j1 is j2


def test_log_never_raises(journal):
    journal.log("job-bad", "unknown_type_xyz")
    journal.log("", "job_start")
    entries = journal.get_entries("job-bad")
    assert len(entries) == 1


def test_malformed_line_handling(journal):
    journal.log("job-malformed", "job_start", data={"ok": True})
    path = journal._path("job-malformed")
    with open(path, "a", encoding="utf-8") as f:
        f.write("{not-json}\n")
        f.write("\n")
    entries = journal.get_entries("job-malformed")
    assert len(entries) == 1
    assert entries[0].event_type == "job_start"
