"""Tests for helper functions: trimming, loop detection, JSON extraction, etc."""

import pytest
from autonomous_runner import (
    _trim_context,
    _make_call_signature,
    _check_loop,
    _extract_json_block,
    _compact_description,
    _job_run_dir,
    LOOP_DETECT_THRESHOLD,
)


class TestTrimContext:
    def test_short_text_unchanged(self):
        text = "Hello world"
        assert _trim_context(text, max_tokens=100) == text

    def test_long_text_truncated(self):
        text = "a" * 10000
        result = _trim_context(text, max_tokens=100)
        assert len(result) < 10000
        assert "truncated" in result

    def test_empty_text(self):
        assert _trim_context("") == ""
        assert _trim_context(None) is None

    def test_exact_boundary(self):
        text = "a" * 400  # 100 tokens * 4 chars = 400
        result = _trim_context(text, max_tokens=100)
        assert result == text  # exactly at boundary, not truncated

    def test_truncation_message_included(self):
        text = "a" * 1000
        result = _trim_context(text, max_tokens=100)
        assert "truncated from 1000 to 400 chars" in result


class TestMakeCallSignature:
    def test_dict_input(self):
        sig = _make_call_signature("file_read", {"path": "/tmp/test.py"})
        assert sig.startswith("file_read:")
        assert len(sig) > len("file_read:")

    def test_deterministic(self):
        sig1 = _make_call_signature("file_read", {"path": "/tmp/test.py"})
        sig2 = _make_call_signature("file_read", {"path": "/tmp/test.py"})
        assert sig1 == sig2

    def test_different_inputs_different_sigs(self):
        sig1 = _make_call_signature("file_read", {"path": "/tmp/a.py"})
        sig2 = _make_call_signature("file_read", {"path": "/tmp/b.py"})
        assert sig1 != sig2

    def test_dict_key_order_irrelevant(self):
        sig1 = _make_call_signature("tool", {"a": 1, "b": 2})
        sig2 = _make_call_signature("tool", {"b": 2, "a": 1})
        assert sig1 == sig2

    def test_string_input(self):
        sig = _make_call_signature("tool", "raw_string_input")
        assert sig.startswith("tool:")


class TestCheckLoop:
    def test_no_loop_initially(self):
        counts = {}
        sig = _make_call_signature("file_read", {"path": "/tmp/test.py"})
        assert _check_loop(sig, counts, "job-1", "execute") is False

    def test_loop_detected_at_threshold(self):
        counts = {}
        sig = _make_call_signature("file_read", {"path": "/tmp/test.py"})
        for _ in range(LOOP_DETECT_THRESHOLD - 1):
            _check_loop(sig, counts, "job-1", "execute")
        # The Nth call should detect the loop
        assert _check_loop(sig, counts, "job-1", "execute") is True


class TestExtractJsonBlock:
    def test_fenced_json(self):
        text = '```json\n{"key": "value"}\n```'
        result = _extract_json_block(text)
        assert '"key"' in result

    def test_fenced_no_lang(self):
        text = '```\n{"key": "value"}\n```'
        result = _extract_json_block(text)
        assert '"key"' in result

    def test_bare_json(self):
        text = 'Some text {"key": "value"} more text'
        result = _extract_json_block(text)
        assert '"key"' in result

    def test_no_json(self):
        text = "Just plain text with no JSON"
        result = _extract_json_block(text)
        assert result is None

    def test_nested_braces(self):
        text = '{"outer": {"inner": "value"}}'
        result = _extract_json_block(text)
        assert "inner" in result

    def test_valid_parseable(self):
        import json
        text = '```json\n{"steps": [{"description": "test", "tools": ["file_write"]}]}\n```'
        result = _extract_json_block(text)
        parsed = json.loads(result)
        assert parsed["steps"][0]["description"] == "test"


class TestCompactDescription:
    def test_short_description(self):
        desc = "Fix the button"
        assert _compact_description(desc) == desc

    def test_long_description_truncated(self):
        desc = "a" * 200
        result = _compact_description(desc, max_len=100)
        assert len(result) <= 103  # 100 + "..."

    def test_default_max_len(self):
        desc = "a" * 200
        result = _compact_description(desc)
        assert len(result) <= 103


class TestJobRunDir:
    def test_creates_directory(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_DATA_DIR", str(tmp_path))
        # Re-import to pick up the env change
        import autonomous_runner as ar
        original_dir = ar.JOB_RUNS_DIR
        ar.JOB_RUNS_DIR = tmp_path / "jobs" / "runs"

        d = ar._job_run_dir("test-job-123")
        assert d.exists()
        assert d.name == "test-job-123"

        # Restore
        ar.JOB_RUNS_DIR = original_dir
