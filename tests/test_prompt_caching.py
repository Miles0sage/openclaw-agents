"""Tests for Anthropic prompt-caching wiring."""

from types import SimpleNamespace

import pytest

import provider_chain
from autonomous_runner import (
    _anthropic_messages_create_with_cache,
    _build_cached_system_payload,
    _build_cached_tools_payload,
    _log_anthropic_cache_usage,
)


class _FakeUsage:
    def __init__(self, *, input_tokens=10, output_tokens=5, cache_read=0, cache_created=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read
        self.cache_creation_input_tokens = cache_created


class _FakeResponse:
    def __init__(self, usage=None):
        self.usage = usage or _FakeUsage()
        self.content = []
        self.model = "claude-sonnet"
        self.stop_reason = "stop"


class _FakeMessages:
    def __init__(self, *, fail_cached=False):
        self.calls = []
        self.fail_cached = fail_cached
        self._failed_once = False

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_cached and "extra_headers" in kwargs and not self._failed_once:
            self._failed_once = True
            raise RuntimeError("unsupported header")
        return _FakeResponse()


class _FakeAnthropicClient:
    def __init__(self, *, fail_cached=False):
        self.messages = _FakeMessages(fail_cached=fail_cached)


def test_cache_control_block_structure():
    payload = _build_cached_system_payload("system prompt")
    assert isinstance(payload, list)
    assert payload[0]["type"] == "text"
    assert payload[0]["text"] == "system prompt"
    assert "cache_control" in payload[0]


def test_cache_control_type_is_ephemeral():
    payload = _build_cached_system_payload("x")
    assert payload[0]["cache_control"]["type"] == "ephemeral"


def test_beta_header_present():
    client = _FakeAnthropicClient()
    _anthropic_messages_create_with_cache(
        client,
        model="claude-sonnet",
        max_tokens=100,
        system_prompt="sys",
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        job_id="job-1",
    )
    call = client.messages.calls[0]
    assert call["extra_headers"]["anthropic-beta"] == "prompt-caching-2024-07-31"


@pytest.mark.asyncio
async def test_non_anthropic_models_not_cached(monkeypatch):
    called = {"kimi": 0}

    def _fake_kimi(model, messages, system=None, max_tokens=4096):
        called["kimi"] += 1
        return {
            "content": "ok",
            "provider": "kimi",
            "model": model,
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "stop_reason": "stop",
        }

    monkeypatch.setattr(provider_chain, "_call_kimi", _fake_kimi)
    monkeypatch.setattr(provider_chain, "_call_anthropic", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not call anthropic")))

    result = await provider_chain._call_provider(
        "kimi",
        "kimi-2.5",
        messages=[{"role": "user", "content": "ping"}],
        system="sys",
    )
    assert result["provider"] == "kimi"
    assert called["kimi"] == 1


def test_cache_fallback_on_error():
    client = _FakeAnthropicClient(fail_cached=True)
    _anthropic_messages_create_with_cache(
        client,
        model="claude-sonnet",
        max_tokens=100,
        system_prompt="sys",
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        job_id="job-2",
    )
    assert len(client.messages.calls) == 2
    first, second = client.messages.calls
    assert "extra_headers" in first
    assert "extra_headers" not in second
    assert second["system"] == "sys"


def test_cache_read_tokens_logged(caplog):
    caplog.set_level("DEBUG")
    response = _FakeResponse(usage=_FakeUsage(cache_read=120, cache_created=0))
    _log_anthropic_cache_usage(response, job_id="job-3")
    assert "read=120" in caplog.text


def test_cache_creation_tokens_logged(caplog):
    caplog.set_level("DEBUG")
    response = _FakeResponse(usage=_FakeUsage(cache_read=0, cache_created=88))
    provider_chain._log_cache_usage(response)
    assert "created=88" in caplog.text


def test_empty_system_prompt_handled():
    payload = _build_cached_system_payload("")
    assert isinstance(payload, list)
    assert payload[0]["text"] == ""


def test_cached_tools_payload_marks_last_tool():
    tools = [{"name": "one"}, {"name": "two"}]
    cached = _build_cached_tools_payload(tools)
    assert "cache_control" not in cached[0]
    assert cached[-1]["cache_control"]["type"] == "ephemeral"


def test_provider_chain_anthropic_call_uses_cache_header(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    captured = {}

    class _SDKMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _FakeResponse(usage=_FakeUsage(input_tokens=11, output_tokens=7))

    class _SDKClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.messages = _SDKMessages()

    fake_anthropic = SimpleNamespace(Anthropic=_SDKClient)
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_anthropic)

    result = provider_chain._call_anthropic(
        model="claude-sonnet",
        messages=[{"role": "user", "content": "hello"}],
        system="sys",
    )

    assert result["provider"] == "anthropic"
    assert captured["extra_headers"]["anthropic-beta"] == "prompt-caching-2024-07-31"
    assert captured["system"][0]["cache_control"]["type"] == "ephemeral"
