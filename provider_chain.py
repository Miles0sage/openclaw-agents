"""Provider fallback chain — automatic provider switching on failures.

Usage
-----
    from provider_chain import call_with_fallback, get_chain_status

    # Text-only research/planning phase (cheap providers first):
    result = await call_with_fallback(
        "text_reasoner",
        messages=[{"role": "user", "content": "Summarise this repo..."}],
        system="You are a helpful research assistant.",
    )

    # Tool-executing phase (Anthropic only, native tool_use required):
    result = await call_with_fallback(
        "tool_executor",
        messages=[{"role": "user", "content": "Run the tests."}],
        tools=[...],
    )

Return value
------------
    {
        "content":     <str | list>,   # str for kimi/minimax, list of blocks for anthropic
        "provider":    <str>,
        "model":       <str>,
        "usage":       {"input_tokens": int, "output_tokens": int},
        "stop_reason": <str | None>,
    }
"""

import asyncio
import logging
import time
import threading
from typing import Optional

logger = logging.getLogger("openclaw.provider_chain")
_ANTHROPIC_PROMPT_CACHING_HEADER = {"anthropic-beta": "prompt-caching-2024-07-31"}

# ---------------------------------------------------------------------------
# Chain definitions — ordered by preference (cheapest first for text phases,
# Anthropic-only for tool execution because only Anthropic supports native
# tool_use content blocks that can be dispatched to execute_tool()).
#
# TIER 0 (FREE): Ollama — local GPU on Miles' PC via SSH tunnel (localhost:11434)
# TIER 1: Gemini 3 Flash — FREE (but rate-limited)
# TIER 2: Bailian (Alibaba) — $0.00003/call (Qwen, Kimi, GLM)
# TIER 3: Kimi 2.5 — $0.14/M tokens
# TIER 4: MiniMax M2.5 — $0.30/M tokens
# TIER 5: Anthropic — $15/$75 per 1M tokens (Opus)
# ---------------------------------------------------------------------------
PROVIDER_CHAINS: dict = {
    "tool_executor": [
        {"provider": "anthropic", "model": "claude-sonnet-4-5-20250929"},
        {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    ],
    "text_reasoner": [
        # Tier 0 (FREE): Local GPU via SSH tunnel
        {"provider": "ollama",   "model": "qwen2.5:7b"},
        # Tier 1: FREE but rate-limited
        {"provider": "gemini",   "model": "gemini-3-flash-preview"},
        # Tier 2: Bailian ($0.00003) — NOT in chain yet, add if needed
        # Tier 3: Kimi 2.5 ($0.14)
        {"provider": "kimi",     "model": "kimi-2.5"},
        # Tier 4: MiniMax M2.5 ($0.30)
        {"provider": "minimax",  "model": "m2.5"},
        # Tier 4b: Gemini Flash Lite
        {"provider": "gemini",   "model": "gemini-2.5-flash-lite"},
        # Tier 5: Anthropic ($15)
        {"provider": "anthropic","model": "claude-haiku-4-5-20251001"},
    ],
}


# ---------------------------------------------------------------------------
# Lightweight synchronous provider-level cooldown tracker.
#
# error_recovery.CircuitBreaker operates per agent-key and is async; it is
# not designed for per-provider billing/rate-limit tracking.  We implement
# our own simple tracker here so provider_chain.py is self-contained and
# works without requiring a running asyncio event loop for cooldown queries.
# ---------------------------------------------------------------------------

class _ErrorKind:
    BILLING    = "billing"     # 402 / credit exhausted — long cooldown
    RATE_LIMIT = "rate_limit"  # 429                    — short cooldown
    OTHER      = "other"       # anything else          — brief cooldown

# Cooldown durations in seconds
_COOLDOWN = {
    _ErrorKind.BILLING:    3600,   # 1 hour — credits unlikely to refill faster
    _ErrorKind.RATE_LIMIT: 60,     # 1 minute
    _ErrorKind.OTHER:      15,     # brief pause before retry
}


class ProviderCooldownTracker:
    """Thread-safe, synchronous provider-level cooldown tracker.

    Tracks when a provider failed and prevents reuse until the appropriate
    cooldown window has elapsed.  Distinct from error_recovery.CircuitBreaker
    which operates on per-agent keys asynchronously.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # provider -> {"kind": str, "until": float}
        self._cooldowns: dict = {}

    def is_available(self, provider: str) -> tuple[bool, str]:
        """Return (available, reason_str).

        Thread-safe, synchronous — safe to call from any context.
        """
        with self._lock:
            entry = self._cooldowns.get(provider)
            if entry is None:
                return True, "ok"
            if time.time() >= entry["until"]:
                del self._cooldowns[provider]
                return True, "ok"
            remaining = int(entry["until"] - time.time())
            return False, f"cooling down ({entry['kind']}, {remaining}s remaining)"

    def mark_failure(self, provider: str, kind: str = _ErrorKind.OTHER) -> None:
        """Record a provider failure and start the appropriate cooldown."""
        duration = _COOLDOWN.get(kind, _COOLDOWN[_ErrorKind.OTHER])
        with self._lock:
            self._cooldowns[provider] = {
                "kind":  kind,
                "until": time.time() + duration,
            }
        logger.warning(
            f"Provider '{provider}' marked as {kind!r} — cooldown {duration}s"
        )

    def mark_success(self, provider: str) -> None:
        """Clear any cooldown after a successful call."""
        with self._lock:
            self._cooldowns.pop(provider, None)

    def get_status(self) -> dict:
        """Return a snapshot of all active cooldowns."""
        with self._lock:
            active_cooldowns = {}
            for p, e in self._cooldowns.items():
                remaining = max(0, int(e["until"] - time.time()))
                if remaining > 0:
                    active_cooldowns[p] = {
                        "kind":      e["kind"],
                        "remaining": remaining,
                    }
            return active_cooldowns


# Module-level singleton — imported by other modules for shared state.
provider_cooldowns = ProviderCooldownTracker()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def call_with_fallback(
    chain_name: str,
    messages: list,
    tools: list = None,
    max_tokens: int = 4096,
    system: str = None,
) -> dict:
    """Try providers in chain order, skipping cooled-down ones.

    Args:
        chain_name:  Key in PROVIDER_CHAINS — "tool_executor" or "text_reasoner".
        messages:    Conversation messages list (OpenAI/Anthropic style dicts).
        tools:       Tool definitions (Anthropic format).  Only works with
                     the "tool_executor" chain (Anthropic provider).
        max_tokens:  Maximum output tokens.
        system:      System prompt string.

    Returns:
        Normalised response dict — see module docstring.

    Raises:
        RuntimeError if every provider in the chain is unavailable or fails.
    """
    candidates = PROVIDER_CHAINS.get(chain_name, PROVIDER_CHAINS["text_reasoner"])
    errors: list[str] = []

    for candidate in candidates:
        provider = candidate["provider"]
        model    = candidate["model"]

        available, reason = provider_cooldowns.is_available(provider)
        if not available:
            msg = f"{provider}/{model}: {reason}"
            errors.append(msg)
            logger.info(f"Skipping provider {provider!r}: {reason}")
            continue

        try:
            result = await _call_provider(
                provider, model, messages,
                tools=tools,
                max_tokens=max_tokens,
                system=system,
            )
            provider_cooldowns.mark_success(provider)
            logger.info(
                f"Provider {provider!r} ({model}) succeeded — "
                f"usage={result.get('usage', {})}"
            )
            return result

        except Exception as exc:
            err_str = str(exc).lower()

            if any(x in err_str for x in ["credit", "billing", "402", "balance", "payment", "insufficient"]):
                kind = _ErrorKind.BILLING
            elif any(x in err_str for x in ["rate", "429", "too many", "throttl"]):
                kind = _ErrorKind.RATE_LIMIT
            else:
                kind = _ErrorKind.OTHER

            provider_cooldowns.mark_failure(provider, kind)
            msg = f"{provider}/{model}: {exc}"
            errors.append(msg)
            logger.warning(
                f"Provider {provider!r} failed ({kind}): {exc} — trying next in chain"
            )
            continue

    raise RuntimeError(
        f"All providers in chain '{chain_name}' exhausted. "
        f"Errors: {'; '.join(errors)}"
    )


async def _call_provider(
    provider: str,
    model: str,
    messages: list,
    tools: list = None,
    max_tokens: int = 4096,
    system: str = None,
) -> dict:
    """Dispatch to the appropriate provider client.

    All providers are called via run_in_executor so the event loop stays
    unblocked while waiting for network I/O.

    Anthropic returns a list of content blocks (matching the SDK response
    format expected by autonomous_runner._call_agent).  Kimi and MiniMax
    return a plain string in the "content" field.

    Ollama returns plain text content (async but wrapped in executor for
    consistency with other providers).
    """
    loop = asyncio.get_running_loop()

    if provider == "anthropic":
        return await loop.run_in_executor(
            None,
            lambda: _call_anthropic(model, messages, tools=tools, max_tokens=max_tokens, system=system),
        )

    elif provider == "ollama":
        # Ollama is already async, but wrap in executor for consistency
        return await _call_ollama(model, messages, system=system, max_tokens=max_tokens)

    elif provider == "kimi":
        return await loop.run_in_executor(
            None,
            lambda: _call_kimi(model, messages, system=system, max_tokens=max_tokens),
        )

    elif provider == "minimax":
        return await loop.run_in_executor(
            None,
            lambda: _call_minimax(model, messages, system=system, max_tokens=max_tokens),
        )

    elif provider == "gemini":
        return await loop.run_in_executor(
            None,
            lambda: _call_gemini(model, messages, tools=tools, system=system, max_tokens=max_tokens),
        )

    else:
        raise ValueError(f"Unknown provider: {provider!r}")


# ---------------------------------------------------------------------------
# Provider-specific call helpers
# ---------------------------------------------------------------------------

async def _call_ollama(
    model: str,
    messages: list,
    system: str = None,
    max_tokens: int = 4096,
) -> dict:
    """Async Ollama call via SSH tunnel (localhost:11434).

    Ollama is already async, so we don't wrap in run_in_executor.
    This handler converts messages to a prompt and calls the chat endpoint.
    """
    from ollama_client import get_ollama_client

    client = get_ollama_client()

    # Check if tunnel is active before attempting call
    available = await client.is_available()
    if not available:
        raise RuntimeError("Ollama tunnel not active (Miles' PC SSH reverse tunnel down)")

    try:
        # Use chat endpoint for multi-turn conversations
        result = await client.chat(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
        )

        return {
            "content": result["content"],  # Plain text string
            "provider": "ollama",
            "model": model,
            "usage": {
                "input_tokens": result["tokens_input"],
                "output_tokens": result["tokens_output"],
            },
            "stop_reason": result.get("stop_reason", "stop"),
        }

    except Exception as e:
        logger.warning(f"Ollama call failed: {e}")
        raise


def _call_anthropic(
    model: str,
    messages: list,
    tools: list = None,
    max_tokens: int = 4096,
    system: str = None,
) -> dict:
    """Synchronous Anthropic SDK call."""
    import os
    import anthropic  # type: ignore

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY environment variable not set")

    client = anthropic.Anthropic(api_key=api_key)

    plain_kwargs: dict = {
        "model":      model,
        "max_tokens": max_tokens,
        "messages":   messages,
    }
    if system is not None:
        plain_kwargs["system"] = system
    if tools:
        plain_kwargs["tools"] = tools

    cached_kwargs = dict(plain_kwargs)
    cache_enabled = False
    try:
        if system is not None:
            cached_kwargs["system"] = _build_cached_system(system)
        if tools:
            cached_kwargs["tools"] = _build_cached_tools(tools)
        cached_kwargs["extra_headers"] = dict(_ANTHROPIC_PROMPT_CACHING_HEADER)
        cache_enabled = True
    except Exception:
        cached_kwargs = dict(plain_kwargs)
        cache_enabled = False

    try:
        response = client.messages.create(**cached_kwargs)
    except Exception as cache_err:
        if not cache_enabled:
            raise
        logger.debug(
            "Anthropic prompt caching rejected (%s); retrying without cache controls",
            cache_err,
        )
        response = client.messages.create(**plain_kwargs)

    _log_cache_usage(response)

    return {
        "content":     response.content,          # list of SDK content blocks
        "provider":    "anthropic",
        "model":       response.model,
        "usage": {
            "input_tokens":  response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
        "stop_reason": response.stop_reason,
    }


def _build_cached_system(system_prompt):
    """Build Anthropic system payload with cache controls when possible."""
    if isinstance(system_prompt, str):
        return [{
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }]
    return system_prompt


def _build_cached_tools(tools: list) -> list:
    """Apply cache controls to Anthropic tool schema payload."""
    cached_tools = list(tools)
    if cached_tools:
        cached_tools[-1] = {**cached_tools[-1], "cache_control": {"type": "ephemeral"}}
    return cached_tools


def _log_cache_usage(response) -> None:
    """Emit debug-only cache usage details for cost visibility."""
    usage = getattr(response, "usage", None)
    if not usage:
        return
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_created = getattr(usage, "cache_creation_input_tokens", 0) or 0
    if cache_read or cache_created:
        logger.debug(
            "[provider-chain] Cache: read=%s created=%s savings≈%.0f tokens",
            cache_read,
            cache_created,
            cache_read * 0.9,
        )


def _call_kimi(
    model: str,
    messages: list,
    system: str = None,
    max_tokens: int = 4096,
) -> dict:
    """Synchronous Kimi (Deepseek) call via deepseek_client.DeepseekClient.

    Converts the messages list to a (system_prompt, user_prompt) pair that
    DeepseekClient.call() expects.  If there are multiple turns we pass the
    last user message as the prompt and reconstruct system from the first
    system block (if any).
    """
    from deepseek_client import DeepseekClient  # type: ignore

    # Extract system prompt — prefer explicit arg, fall back to messages list.
    sys_prompt = system
    user_messages = []
    for msg in messages:
        if msg.get("role") == "system" and sys_prompt is None:
            sys_prompt = msg["content"]
        else:
            user_messages.append(msg)

    # Build prompt: join all user/assistant turns, then end with final user msg.
    if not user_messages:
        raise ValueError("No user messages provided for kimi call")

    # For simplicity, concatenate prior turns as context in the prompt string.
    # DeepseekClient.call() does not natively accept multi-turn arrays, so we
    # flatten them here.  Full multi-turn support could use the conversation_history
    # feature of KimiAgent, but that requires an agent_id rather than a raw model.
    if len(user_messages) == 1:
        prompt = user_messages[-1]["content"]
    else:
        parts = []
        for m in user_messages:
            role_label = "User" if m["role"] == "user" else "Assistant"
            parts.append(f"{role_label}: {m['content']}")
        prompt = "\n".join(parts)

    client = DeepseekClient()
    response = client.call(
        model=model,
        prompt=prompt,
        system_prompt=sys_prompt,
        max_tokens=max_tokens,
    )

    return {
        "content":     response.content,
        "provider":    "kimi",
        "model":       model,
        "usage": {
            "input_tokens":  response.tokens_input,
            "output_tokens": response.tokens_output,
        },
        "stop_reason": getattr(response, "stop_reason", "stop"),
    }


def _call_minimax(
    model: str,
    messages: list,
    system: str = None,
    max_tokens: int = 4096,
) -> dict:
    """Synchronous MiniMax call via minimax_client.MiniMaxClient.

    Same flattening strategy as _call_kimi — MiniMaxClient.call() takes
    (model, prompt, system_prompt) rather than a messages array.
    """
    from minimax_client import MiniMaxClient  # type: ignore

    sys_prompt = system
    user_messages = []
    for msg in messages:
        if msg.get("role") == "system" and sys_prompt is None:
            sys_prompt = msg["content"]
        else:
            user_messages.append(msg)

    if not user_messages:
        raise ValueError("No user messages provided for minimax call")

    if len(user_messages) == 1:
        prompt = user_messages[-1]["content"]
    else:
        parts = []
        for m in user_messages:
            role_label = "User" if m["role"] == "user" else "Assistant"
            parts.append(f"{role_label}: {m['content']}")
        prompt = "\n".join(parts)

    # MiniMaxClient constructor raises ValueError if MINIMAX_API_KEY is unset.
    client = MiniMaxClient()
    response = client.call(
        model=model,
        prompt=prompt,
        system_prompt=sys_prompt,
        max_tokens=max_tokens,
    )

    return {
        "content":     response.content,
        "provider":    "minimax",
        "model":       model,
        "usage": {
            "input_tokens":  response.tokens_input,
            "output_tokens": response.tokens_output,
        },
        "stop_reason": response.stop_reason,
    }


def _call_gemini(
    model: str,
    messages: list,
    tools: list = None,
    system: str = None,
    max_tokens: int = 4096,
) -> dict:
    """Synchronous Gemini call via gemini_client.GeminiClient.

    Same flattening strategy as _call_kimi — GeminiClient.call() takes
    (model, prompt, system_prompt) rather than a messages array.

    When tools are provided, they are converted to Gemini functionDeclarations
    and any functionCall responses are normalized to Anthropic-style tool_use
    content blocks (list format matching Anthropic provider output).
    """
    from gemini_client import GeminiClient  # type: ignore

    sys_prompt = system
    user_messages = []
    for msg in messages:
        if msg.get("role") == "system" and sys_prompt is None:
            sys_prompt = msg["content"]
        else:
            user_messages.append(msg)

    if not user_messages:
        raise ValueError("No user messages provided for gemini call")

    if len(user_messages) == 1:
        prompt = user_messages[-1]["content"]
    else:
        parts = []
        for m in user_messages:
            role_label = "User" if m["role"] == "user" else "Assistant"
            parts.append(f"{role_label}: {m['content']}")
        prompt = "\n".join(parts)

    client = GeminiClient()
    response = client.call(
        model=model,
        prompt=prompt,
        system_prompt=sys_prompt,
        max_tokens=max_tokens,
        tools=tools,
    )

    # Build content — if tool calls present, return as list of content blocks
    # (matching Anthropic format for tool_executor chain compatibility).
    if response.tool_calls:
        content_blocks = []
        if response.content:
            content_blocks.append({"type": "text", "text": response.content})
        for tc in response.tool_calls:
            content_blocks.append(tc)
        content = content_blocks
    else:
        content = response.content

    return {
        "content":     content,
        "provider":    "gemini",
        "model":       model,
        "usage": {
            "input_tokens":  response.tokens_input,
            "output_tokens": response.tokens_output,
        },
        "stop_reason": response.stop_reason,
    }


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def get_chain_status() -> dict:
    """Return current availability of all providers across all chains.

    Example output::

        {
            "tool_executor": [
                {"provider": "anthropic", "model": "claude-haiku-4-5-20251001",
                 "available": True, "reason": "ok"}
            ],
            "text_reasoner": [
                {"provider": "kimi",    "model": "kimi-2.5",
                 "available": False, "reason": "cooling down (billing, 3412s remaining)"},
                ...
            ]
        }
    """
    status: dict = {}
    for chain_name, candidates in PROVIDER_CHAINS.items():
        chain_status = []
        for c in candidates:
            available, reason = provider_cooldowns.is_available(c["provider"])
            chain_status.append({
                "provider":  c["provider"],
                "model":     c["model"],
                "available": available,
                "reason":    reason,
            })
        status[chain_name] = chain_status
    return status
