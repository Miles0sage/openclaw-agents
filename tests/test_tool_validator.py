"""Tests for tool_validator module."""

import pytest
from tool_validator import ToolValidator, ToolValidationError


@pytest.fixture
def validator():
    return ToolValidator()


def test_valid_file_read(validator):
    assert validator.validate("file_read", {"path": "/tmp/test.py"}) is None


def test_missing_required_arg(validator):
    err = validator.validate("file_read", {})
    assert err is not None
    assert "Missing required" in err
    assert "path" in err


def test_wrong_arg_type(validator):
    err = validator.validate("file_read", {"path": 123})
    assert err is not None
    assert "expected str" in err


def test_valid_shell_execute(validator):
    assert validator.validate("shell_execute", {"command": "ls -la"}) is None


def test_dangerous_shell_blocked(validator):
    err = validator.validate("shell_execute", {"command": "rm -rf /"})
    assert err is not None
    assert "dangerous" in err.lower()


def test_dangerous_drop_table_blocked(validator):
    err = validator.validate("shell_execute", {"command": "echo 'DROP TABLE users'"})
    assert err is not None


def test_unknown_tool_passes(validator):
    """Unknown tools with no schema should pass through."""
    assert validator.validate("custom_unknown_tool", {"anything": "goes"}) is None


def test_empty_tool_name_fails(validator):
    err = validator.validate("", {"x": 1})
    assert err is not None
    assert "non-empty" in err


def test_non_dict_args_fails(validator):
    err = validator.validate("file_read", "not a dict")
    assert err is not None
    assert "dict" in err


def test_allowlist_pass(validator):
    err = validator.validate("file_read", {"path": "/x"}, agent_allowlist=["file_read", "file_write"])
    assert err is None


def test_allowlist_block(validator):
    err = validator.validate("shell_execute", {"command": "ls"}, agent_allowlist=["file_read"])
    assert err is not None
    assert "allowlist" in err


def test_stats_tracking(validator):
    validator.validate("file_read", {"path": "/x"})
    validator.validate("file_read", {})
    stats = validator.get_stats()
    assert stats["total"] == 2
    assert stats["passed"] == 1
    assert stats["failed"] == 1


def test_register_custom_schema(validator):
    validator.register_schema("my_tool", required=["query"], types={"query": str})
    assert validator.validate("my_tool", {"query": "test"}) is None
    err = validator.validate("my_tool", {})
    assert "Missing required" in err


def test_file_edit_valid(validator):
    assert validator.validate("file_edit", {
        "path": "/x", "old_string": "a", "new_string": "b"
    }) is None


def test_file_edit_missing_args(validator):
    err = validator.validate("file_edit", {"path": "/x"})
    assert "old_string" in err or "new_string" in err


def test_git_commit_valid(validator):
    assert validator.validate("git_commit", {"message": "fix: stuff"}) is None


def test_optional_args_ignored(validator):
    """Extra args not in schema should be fine."""
    assert validator.validate("file_read", {"path": "/x", "extra": True}) is None
