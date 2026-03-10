"""
Tests for the OpenClaw CLI.
"""

import json
import argparse
from unittest.mock import patch, MagicMock
import pytest
import io

from cli.openclaw_cli import (
    cmd_health,
    cmd_run,
    cmd_status,
    cmd_jobs,
    Config,
    CliError,
    HttpError,
    _parse_json_or_text,
    _extract_job_id,
    _extract_status,
    _is_terminal,
    _is_success,
    main,
    _build_parser,
    Colors
)

import re
def strip_ansi(text):
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


@pytest.fixture
def config():
    return Config(gateway_url="http://test", auth_token="test_token")


def test_parse_json_or_text():
    assert _parse_json_or_text('{"key": "value"}') == {"key": "value"}
    assert _parse_json_or_text("plain text") == {"raw": "plain text"}
    assert _parse_json_or_text("") == {}


def test_extract_job_id():
    assert _extract_job_id({"job_id": "123"}) == "123"
    assert _extract_job_id({"id": "456"}) == "456"
    assert _extract_job_id({"other": "value"}) is None
    assert _extract_job_id("not a dict") is None


def test_extract_status():
    assert _extract_status({"status": "COMPLETED"}) == "completed"
    assert _extract_status({"status": "Failed"}) == "failed"
    assert _extract_status({}) == "unknown"


def test_is_terminal():
    assert _is_terminal("completed") is True
    assert _is_terminal("failed") is True
    assert _is_terminal("pending") is False


def test_is_success():
    assert _is_success("completed") is True
    assert _is_success("success") is True
    assert _is_success("failed") is False


@patch("cli.openclaw_cli._request")
def test_cmd_health(mock_request, config, capsys):
    mock_request.return_value = {"status": "healthy"}
    args = argparse.Namespace(json=False)

    result = cmd_health(args, config)

    assert result == 0
    mock_request.assert_called_once_with("GET", config, "/health")
    captured = capsys.readouterr()
    assert "Gateway healthy" in captured.out


@patch("cli.openclaw_cli._request")
def test_cmd_health_json(mock_request, config, capsys):
    mock_request.return_value = {"status": "healthy"}
    args = argparse.Namespace(json=True)

    result = cmd_health(args, config)

    assert result == 0
    captured = capsys.readouterr()
    assert '"status": "healthy"' in captured.out


@patch("cli.openclaw_cli._request")
def test_cmd_run_nowait(mock_request, config, capsys):
    mock_request.return_value = {"job_id": "job_123"}
    args = argparse.Namespace(prompt="test prompt", wait=False, json=False)

    result = cmd_run(args, config)

    assert result == 0
    mock_request.assert_called_once_with(
        "POST", config, "/api/jobs", token="test_token", payload={"prompt": "test prompt"}
    )
    captured = capsys.readouterr()
    assert "Submitted job job_123" in strip_ansi(captured.out)


@patch("cli.openclaw_cli.time.sleep")
@patch("cli.openclaw_cli._request")
def test_cmd_run_wait(mock_request, mock_sleep, config, capsys):
    mock_request.side_effect = [
        {"job_id": "job_123"},  # POST response
        {"status": "running"},  # GET response 1
        {"status": "completed"} # GET response 2
    ]
    args = argparse.Namespace(prompt="test prompt", wait=True, json=False)

    result = cmd_run(args, config)

    assert result == 0
    assert mock_request.call_count == 3
    assert mock_sleep.call_count == 2
    captured = capsys.readouterr()
    assert "Final status: completed" in strip_ansi(captured.out)


@patch("cli.openclaw_cli._request")
def test_cmd_status(mock_request, config, capsys):
    mock_request.return_value = {"job_id": "job_123", "status": "completed", "prompt": "test"}
    args = argparse.Namespace(job_id="job_123", json=False)

    result = cmd_status(args, config)

    assert result == 0
    mock_request.assert_called_once_with("GET", config, "/api/jobs/job_123", token="test_token")
    captured = capsys.readouterr()
    assert "Status: completed" in strip_ansi(captured.out)


@patch("cli.openclaw_cli._request")
def test_cmd_jobs(mock_request, config, capsys):
    mock_request.return_value = {"jobs": [{"job_id": "job_1", "status": "completed"}]}
    args = argparse.Namespace(limit=10, json=False)

    result = cmd_jobs(args, config)

    assert result == 0
    mock_request.assert_called_once_with("GET", config, "/api/jobs?limit=10", token="test_token")
    captured = capsys.readouterr()
    assert "Recent jobs: 1" in strip_ansi(captured.out)
    assert "job_1 (completed)" in strip_ansi(captured.out)


@patch("cli.openclaw_cli._request")
def test_cli_error_no_token(mock_request):
    config = Config(gateway_url="http://test", auth_token=None)
    args = argparse.Namespace(prompt="test", wait=False, json=False)

    with pytest.raises(CliError, match="OPENCLAW_AUTH_TOKEN is required"):
        cmd_run(args, config)


@patch("sys.argv", ["openclaw", "health"])
@patch("cli.openclaw_cli._config")
@patch("cli.openclaw_cli.cmd_health")
def test_main_routing(mock_cmd_health, mock_config):
    mock_config.return_value = Config(gateway_url="http://test", auth_token="test_token")
    mock_cmd_health.return_value = 0

    assert main() == 0
    mock_cmd_health.assert_called_once()


@patch("sys.argv", ["openclaw", "run", "test"])
@patch("cli.openclaw_cli._config")
@patch("cli.openclaw_cli.cmd_run")
def test_main_error_handling(mock_cmd_run, mock_config, capsys):
    mock_config.return_value = Config(gateway_url="http://test", auth_token="test_token")
    mock_cmd_run.side_effect = CliError("Test error")

    assert main() == 1
    captured = capsys.readouterr()
    assert "Error: Test error" in strip_ansi(captured.out)
