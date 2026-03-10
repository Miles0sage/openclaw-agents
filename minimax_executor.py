"""
MiniMax Executor — Mid-tier coding backend using MiniMax M2.5.

MiniMax M2.5 scored 80.2% on SWE-Bench — strong for complex coding tasks.
Uses the OpenAI-compatible API at api.minimax.chat.

Cost: ~$0.30/$1.20 per 1M tokens (input/output).

Fallback chain position: OpenCode (Gemini) → Grok (xAI) → **MiniMax** → SDK
"""

import logging
import os

import httpx

from cost_tracker import log_cost_event

logger = logging.getLogger("openclaw.minimax_executor")

MINIMAX_BASE_URL = "https://api.minimax.io/v1"

PRICING = {
    "MiniMax-M2.5": {"input": 0.30, "output": 1.20},
    "MiniMax-M2.5-highspeed": {"input": 0.30, "output": 1.20},
}

DEFAULT_MODEL = "MiniMax-M2.5"


def _get_api_key() -> str:
    return os.environ.get("MINIMAX_API_KEY", "")


async def call_minimax(
    prompt: str,
    system_prompt: str = "",
    model: str = DEFAULT_MODEL,
    max_tokens: int = 8192,
    temperature: float = 0.1,
    timeout: int = 120,
) -> dict:
    """Call MiniMax API and return response text + cost estimate."""

    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY not set")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{MINIMAX_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    choice = data["choices"][0]
    text = choice["message"]["content"]
    usage = data.get("usage", {})
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)

    pricing = PRICING.get(model, PRICING[DEFAULT_MODEL])
    cost_usd = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

    logger.info(f"MiniMax {model}: {input_tokens}in/{output_tokens}out = ${cost_usd:.4f}")

    return {
        "text": text,
        "tokens": input_tokens + output_tokens,
        "cost_usd": cost_usd,
        "model": model,
        "tool_calls": [],
        "source": "minimax",
    }


async def execute_with_minimax(
    prompt: str,
    job_id: str,
    phase: str,
    priority: str,
    conversation: list | None = None,
    system_prompt: str = "",
) -> dict:
    """Execute a job phase using MiniMax. Returns same dict format as other executors."""

    full_prompt = prompt
    if conversation:
        context_parts = []
        for msg in conversation[-6:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                context_parts.append(f"[Previous {role}]: {content[:1000]}")
        if context_parts:
            full_prompt = "CONTEXT FROM PREVIOUS STEPS:\n" + "\n".join(context_parts) + "\n\n---\n\n" + prompt

    if not system_prompt:
        system_prompt = (
            "You are an autonomous AI agent executing a task for the OpenClaw agency. "
            "You are CodeGen Elite — you handle complex coding tasks with deep reasoning. "
            "Provide clear, actionable output. Write code directly when needed. "
            "Be thorough but concise in analysis."
        )

    result = await call_minimax(
        prompt=full_prompt,
        system_prompt=system_prompt,
        model=DEFAULT_MODEL,
        max_tokens=8192,
        temperature=0.1,
    )

    # Log cost
    log_cost_event(
        project="openclaw",
        agent="minimax",
        model=DEFAULT_MODEL,
        tokens_input=result.get("tokens", 0) // 2,
        tokens_output=result.get("tokens", 0) // 2,
        cost=result["cost_usd"],
        event_type="minimax_call",
        metadata={"phase": phase, "priority": priority},
        job_id=job_id,
    )

    logger.info(f"MiniMax completed {job_id}/{phase} for ${result['cost_usd']:.4f}")
    return result
