"""
Grok Executor — xAI Grok as a fallback code generation backend.

Uses the OpenAI-compatible API at api.x.ai. Grok 3 is the workhorse model.
Cost: ~$3/$15 per 1M tokens (grok-3), or ~$0.30/$0.50 (grok-3-mini).

Fallback chain position: OpenCode (Gemini) → **Grok** → GitHub Actions → SDK Haiku
"""

import json
import logging
import os

import httpx

logger = logging.getLogger("openclaw.grok_executor")

XAI_BASE_URL = "https://api.x.ai/v1"


def _get_api_key() -> str:
    """Get API key lazily (after dotenv is loaded)."""
    return os.environ.get("XAI_API_KEY", "")

# Model selection by priority
MODELS = {
    "fast": "grok-3-mini",         # Cheapest, good for simple tasks
    "standard": "grok-3",          # Best quality/cost balance
    "code": "grok-code-fast-1",    # Code-specialized
}

# Pricing per 1M tokens (USD)
PRICING = {
    "grok-3-mini":       {"input": 0.30, "output": 0.50},
    "grok-3":            {"input": 3.00, "output": 15.00},
    "grok-code-fast-1":  {"input": 0.30, "output": 0.50},
}


async def call_grok(
    prompt: str,
    system_prompt: str = "",
    model: str = "grok-3-mini",
    max_tokens: int = 4096,
    temperature: float = 0.2,
    timeout: int = 90,
) -> dict:
    """Call Grok API and return response text + cost estimate."""

    api_key = _get_api_key()
    if not api_key:
        raise ValueError("XAI_API_KEY not set")

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
        try:
            resp = await client.post(
                f"{XAI_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()  # Raise an exception for 4xx or 5xx responses
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error calling Grok API: {e}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error calling Grok API: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error from Grok API response: {e}")
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred during Grok API call: {e}")
            raise

    # Extract response
    choice = data["choices"][0]
    text = choice["message"]["content"]
    usage = data.get("usage", {})
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)

    # Calculate cost
    pricing = PRICING.get(model, PRICING["grok-3-mini"])
    cost_usd = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

    logger.info(f"Grok {model}: {input_tokens}in/{output_tokens}out = ${cost_usd:.4f}")

    return {
        "text": text,
        "tokens": input_tokens + output_tokens,
        "cost_usd": cost_usd,
        "model": model,
        "tool_calls": [],
    }


async def execute_with_grok(
    prompt: str,
    job_id: str,
    phase: str,
    priority: str,
    conversation: list | None = None,
    system_prompt: str = "",
) -> dict:
    """Execute a job phase using Grok. Returns same dict format as other executors."""

    # Pick model based on priority
    if priority == "P0":
        model = "grok-3"           # Best quality for critical
    else:
        model = "grok-3-mini"      # Cheap for everything else

    # Build full prompt with conversation context
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

    # Add agency manual context for better results
    if not system_prompt:
        system_prompt = (
            "You are an autonomous AI agent executing a task for the OpenClaw agency. "
            "Provide clear, actionable output. If the task involves code, write the code directly. "
            "If the task involves analysis, be thorough but concise."
        )

    result = await call_grok(
        prompt=full_prompt,
        system_prompt=system_prompt,
        model=model,
        max_tokens=8192,
        temperature=0.1,
    )

    logger.info(f"Grok completed {job_id}/{phase} with {model} for ${result['cost_usd']:.4f}")
    return result
