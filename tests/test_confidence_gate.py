"""Tests for confidence_gate module."""

from confidence_gate import (
    ConfidenceConfig,
    ConfidenceGate,
    ConfidenceVerdict,
    get_confidence_gate,
    init_confidence_gate,
)


def test_pass_above_threshold():
    gate = ConfidenceGate()
    result = gate.evaluate("job-1", "coder_agent", score=0.90, turn_index=0)
    assert result.verdict == ConfidenceVerdict.PASS


def test_repair_below_threshold():
    gate = ConfidenceGate()
    result = gate.evaluate("job-2", "coder_agent", score=0.50, turn_index=0)
    assert result.verdict == ConfidenceVerdict.REPAIR
    assert result.repairs_used == 1


def test_exhausted_after_max_repairs():
    gate = ConfidenceGate(default_config=ConfidenceConfig(threshold=0.75, max_repairs=2))
    gate.evaluate("job-3", "unknown", score=0.50, turn_index=0)
    gate.evaluate("job-3", "unknown", score=0.40, turn_index=0)
    result = gate.evaluate("job-3", "unknown", score=0.30, turn_index=0)
    assert result.verdict == ConfidenceVerdict.EXHAUSTED


def test_skip_when_disabled():
    gate = ConfidenceGate()
    gate.set_config("agent-x", ConfidenceConfig(enabled=False))
    result = gate.evaluate("job-4", "agent-x", score=0.10, turn_index=0)
    assert result.verdict == ConfidenceVerdict.SKIP


def test_per_agent_config():
    gate = ConfidenceGate()
    assert gate.get_config("pentest_ai").threshold == 0.80


def test_parse_self_score_valid_json():
    gate = ConfidenceGate()
    score, weak = gate.parse_self_score(
        '{"confidence": 0.70, "weak_points": ["missing error handling"]}'
    )
    assert score == 0.70
    assert weak == ["missing error handling"]


def test_parse_self_score_invalid_json():
    gate = ConfidenceGate()
    score, weak = gate.parse_self_score("not-json")
    assert score == 1.0
    assert weak == []


def test_parse_self_score_clamps_range():
    gate = ConfidenceGate()
    high, _ = gate.parse_self_score('{"confidence": 1.5, "weak_points": []}')
    low, _ = gate.parse_self_score('{"confidence": -2, "weak_points": []}')
    assert high == 1.0
    assert low == 0.0


def test_repair_prompt_contains_score():
    gate = ConfidenceGate()
    result = gate.evaluate(
        "job-5",
        "coder_agent",
        score=0.40,
        turn_index=0,
        weak_points=["missing edge case"],
    )
    assert result.verdict == ConfidenceVerdict.REPAIR
    assert "0.40" in result.repair_prompt
    assert "missing edge case" in result.repair_prompt


def test_repair_count_increments():
    gate = ConfidenceGate(default_config=ConfidenceConfig(threshold=0.90, max_repairs=3))
    first = gate.evaluate("job-6", "unknown", score=0.20, turn_index=1)
    second = gate.evaluate("job-6", "unknown", score=0.20, turn_index=1)
    assert first.repairs_used == 1
    assert second.repairs_used == 2


def test_clear_resets_repairs():
    gate = ConfidenceGate()
    gate.evaluate("job-7", "coder_agent", score=0.20, turn_index=2)
    gate.clear("job-7")
    result = gate.evaluate("job-7", "coder_agent", score=0.20, turn_index=2)
    assert result.verdict == ConfidenceVerdict.REPAIR
    assert result.repairs_used == 1


def test_get_stats_tracks_all_verdicts():
    gate = ConfidenceGate(default_config=ConfidenceConfig(threshold=0.8, max_repairs=1))
    gate.evaluate("s1", "unknown", score=0.95, turn_index=0)  # pass
    gate.evaluate("s2", "unknown", score=0.20, turn_index=0)  # repair
    gate.evaluate("s2", "unknown", score=0.20, turn_index=0)  # exhausted
    gate.set_config("disabled", ConfidenceConfig(enabled=False))
    gate.evaluate("s3", "disabled", score=0.10, turn_index=0)  # skipped

    stats = gate.get_stats()
    assert stats["evaluated"] == 4
    assert stats["passed"] == 1
    assert stats["repaired"] == 1
    assert stats["exhausted"] == 1
    assert stats["skipped"] == 1


def test_default_config_fallback():
    gate = ConfidenceGate(default_config=ConfidenceConfig(threshold=0.66))
    cfg = gate.get_config("unknown-agent")
    assert cfg.threshold == 0.66


def test_singleton_init_and_get():
    g1 = init_confidence_gate(default_config=ConfidenceConfig(threshold=0.61))
    g2 = get_confidence_gate()
    assert g1 is g2
    assert g2.get_config("unknown").threshold == 0.61
