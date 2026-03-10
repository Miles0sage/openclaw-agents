"""Tests for stuck_detector module."""

import time
import pytest
from stuck_detector import StuckDetector, StuckError, StuckPattern, StuckResult


def test_no_stuck_on_varied_actions():
    d = StuckDetector(loop_threshold=3)
    r1 = d.record_action("j1", "file_read", {"path": "/a"})
    r2 = d.record_action("j1", "file_read", {"path": "/b"})
    r3 = d.record_action("j1", "file_write", {"path": "/c", "content": "x"})
    assert not r1.is_stuck
    assert not r2.is_stuck
    assert not r3.is_stuck


def test_looper_detected():
    d = StuckDetector(loop_threshold=3)
    d.record_action("j1", "file_read", {"path": "/same"})
    d.record_action("j1", "file_read", {"path": "/same"})
    r = d.record_action("j1", "file_read", {"path": "/same"})
    assert r.is_stuck
    assert r.pattern == StuckPattern.LOOPER
    assert not r.should_fail  # First correction, not failure yet


def test_looper_escalates_after_max_corrections():
    d = StuckDetector(loop_threshold=3, max_corrections=2)
    for _ in range(3):
        d.record_action("j1", "tool", {"a": 1})
    # 1st correction
    for _ in range(3):
        d.record_action("j1", "tool", {"a": 1})
    # 2nd correction
    r = d.record_action("j1", "tool", {"a": 1})
    for _ in range(2):
        r = d.record_action("j1", "tool", {"a": 1})
    # 3rd correction -> should_fail
    assert r.is_stuck
    assert r.should_fail


def test_repeater_detected():
    d = StuckDetector(repeat_threshold=3)
    d.record_response("j1", "I will try reading the file now.")
    d.record_response("j1", "I will try reading the file now.")
    r = d.record_response("j1", "I will try reading the file now.")
    assert r.is_stuck
    assert r.pattern == StuckPattern.REPEATER


def test_repeater_not_triggered_on_varied_responses():
    d = StuckDetector(repeat_threshold=3)
    d.record_response("j1", "Response A")
    d.record_response("j1", "Response B")
    r = d.record_response("j1", "Response A")
    assert not r.is_stuck


def test_wanderer_detected():
    d = StuckDetector(wander_timeout_minutes=0.001)  # ~0.06 sec
    d.record_progress("j1", "execute", 2)
    time.sleep(0.1)
    r = d.check_wanderer("j1")
    assert r.is_stuck
    assert r.pattern == StuckPattern.WANDERER


def test_wanderer_not_triggered_with_progress():
    d = StuckDetector(wander_timeout_minutes=10)
    d.record_progress("j1", "execute", 2)
    r = d.check_wanderer("j1")
    assert not r.is_stuck


def test_progress_resets_wanderer():
    d = StuckDetector(wander_timeout_minutes=0.001)
    time.sleep(0.1)
    d.record_progress("j1", "plan", 0)  # Reset timer
    r = d.check_wanderer("j1")
    assert not r.is_stuck


def test_corrective_prompt_present():
    d = StuckDetector(loop_threshold=2)
    d.record_action("j1", "t", {"x": 1})
    r = d.record_action("j1", "t", {"x": 1})
    assert r.is_stuck
    assert "SYSTEM NOTICE" in r.corrective_prompt
    assert "looper" in r.corrective_prompt


def test_clear_resets_state():
    d = StuckDetector(loop_threshold=3)
    d.record_action("j1", "t", {"x": 1})
    d.record_action("j1", "t", {"x": 1})
    d.clear("j1")
    r = d.record_action("j1", "t", {"x": 1})
    assert not r.is_stuck  # State was cleared


def test_get_status():
    d = StuckDetector()
    d.record_progress("j1", "execute", 3)
    s = d.get_status("j1")
    assert s["job_id"] == "j1"
    assert s["last_phase"] == "execute"
    assert s["last_step_index"] == 3


def test_independent_jobs():
    d = StuckDetector(loop_threshold=3)
    d.record_action("j1", "t", {"x": 1})
    d.record_action("j1", "t", {"x": 1})
    d.record_action("j2", "t", {"x": 1})  # Different job
    r1 = d.record_action("j1", "t", {"x": 1})
    r2 = d.record_action("j2", "t", {"x": 1})
    assert r1.is_stuck  # j1 hit threshold
    assert not r2.is_stuck  # j2 only has 2


def test_get_all_statuses():
    d = StuckDetector()
    d.record_action("j1", "t", {})
    d.record_action("j2", "t", {})
    statuses = d.get_all_statuses()
    assert len(statuses) == 2
