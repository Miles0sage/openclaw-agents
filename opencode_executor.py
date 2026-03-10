"""
OpenCode Executor — Cheap execution backend for OpenClaw jobs.
================================================================
Wraps the OpenCode CLI (Go-based coding assistant) to execute agent tasks
at ~$0.05-0.08/job instead of $0.50-0.70 via Claude SDK. Falls back to
_call_agent_sdk() on error or timeout.

OpenCode CLI: /root/go/bin/opencode
Docs: opencode -p "prompt" -f json -q -c /workspace

Cost savings: ~90% reduction per job execution.
"""

import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path

from cost_tracker import log_cost_event

logger = logging.getLogger("opencode_executor")

# OpenCode CLI binary path
OPENCODE_BIN = os.environ.get("OPENCODE_BIN", "/root/go/bin/opencode")

# Default timeout for OpenCode execution (seconds)
DEFAULT_TIMEOUT = 120

# Path to the canonical OpenCode config (uses Gemini, not Anthropic)
OPENCODE_CONFIG_SRC = Path("./.opencode.json")

# Cost per 1M tokens for OpenCode (Gemini 2.5 Flash via opencode.json)
OPENCODE_COST_PRICING = {
    "input": 0.15,
    "output": 0.60,
}


def _ensure_opencode_config(workspace: str):
    """Copy .opencode.json into workspace if missing.

    Without this config, OpenCode defaults to Anthropic (which has no credits).
    The config directs it to use Gemini 2.5 Flash instead.
    """
    dest = Path(workspace) / ".opencode.json"
    if not dest.exists() and OPENCODE_CONFIG_SRC.exists():
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(OPENCODE_CONFIG_SRC), str(dest))
            logger.info(f"Copied .opencode.json to {workspace}")
        except Exception as e:
            logger.warning(f"Failed to copy .opencode.json to {workspace}: {e}")


async def run_opencode(
    prompt: str,
    workspace: str = ".",
    timeout: int = DEFAULT_TIMEOUT,
    job_id: str = "",
    phase: str = "",
) -> dict:
    """
    Execute a prompt via the OpenCode CLI.

    Runs `opencode -p "prompt" -f json -q -c <workspace>` as a subprocess.
    Parses JSON output for structured results.

    Returns: {
        "text": str,          # Agent's response text
        "tokens": int,        # Estimated token count
        "tool_calls": list,   # Tool calls made (from JSON output)
        "cost_usd": float,    # Estimated cost
        "source": "opencode", # Execution source identifier
    }

    Raises:
        OpenCodeError: On execution failure, timeout, or parse error.
    """
    if not os.path.isfile(OPENCODE_BIN):
        raise OpenCodeError(f"OpenCode binary not found at {OPENCODE_BIN}")

    # Ensure .opencode.json exists in workspace (OpenCode defaults to Anthropic without it)
    _ensure_opencode_config(workspace)

    # Build command
    cmd = [
        OPENCODE_BIN,
        "-p", prompt,
        "-f", "json",
        "-q",  # quiet mode — no interactive UI
        "-c", workspace,
    ]

    logger.info(
        f"OpenCode call: job={job_id} phase={phase} "
        f"workspace={workspace} timeout={timeout}s"
    )

    start_time = time.time()

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace,
            env={
                **{k: v for k, v in os.environ.items()
                   if k not in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")},
                "NO_COLOR": "1",  # Disable ANSI colors in output
            },
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout,
        )

        elapsed = time.time() - start_time

    except asyncio.TimeoutError:
        # Kill the process on timeout
        try:
            process.kill()
            await process.wait()
        except Exception:
            pass
        raise OpenCodeError(
            f"OpenCode timed out after {timeout}s for job={job_id} phase={phase}"
        )

    except Exception as e:
        raise OpenCodeError(f"OpenCode subprocess failed: {e}") from e

    # Check exit code
    if process.returncode != 0:
        stderr_text = stderr.decode("utf-8", errors="replace")[:2000]
        raise OpenCodeError(
            f"OpenCode exited with code {process.returncode}: {stderr_text}"
        )

    # Parse output
    stdout_text = stdout.decode("utf-8", errors="replace")

    result = _parse_opencode_output(stdout_text)
    result["source"] = "opencode"

    # Estimate cost based on output length (rough token estimation)
    # ~4 chars per token is a reasonable approximation
    est_input_tokens = len(prompt) // 4
    est_output_tokens = len(result["text"]) // 4
    result["tokens"] = est_input_tokens + est_output_tokens
    result["cost_usd"] = round(
        (est_input_tokens * OPENCODE_COST_PRICING["input"]
         + est_output_tokens * OPENCODE_COST_PRICING["output"]) / 1_000_000,
        6,
    )

    # Log cost
    log_cost_event(
        project="openclaw",
        agent="opencode",
        model="opencode",
        tokens_input=est_input_tokens,
        tokens_output=est_output_tokens,
        cost=result["cost_usd"],
        event_type="opencode_call",
        metadata={
            "phase": phase,
            "elapsed_s": round(elapsed, 2),
            "exit_code": process.returncode,
        },
        job_id=job_id,
    )

    logger.info(
        f"OpenCode complete: job={job_id} phase={phase} "
        f"elapsed={elapsed:.1f}s cost=${result['cost_usd']:.6f} "
        f"tokens={result['tokens']}"
    )

    return result


def _parse_opencode_output(stdout: str) -> dict:
    """
    Parse OpenCode CLI JSON output into our standard result format.

    OpenCode with -f json returns structured JSON. Falls back to
    treating raw text as the response if JSON parsing fails.
    """
    text = ""
    tool_calls = []

    # Try to parse as JSON first
    try:
        data = json.loads(stdout.strip())

        # OpenCode JSON format varies — handle known structures
        if isinstance(data, dict):
            text = data.get("response", data.get("content", data.get("text", "")))
            if isinstance(text, list):
                # Content blocks
                text = "\n".join(
                    block.get("text", "") for block in text
                    if isinstance(block, dict) and block.get("type") == "text"
                ) or str(text)

            # Extract tool calls if present
            raw_tools = data.get("tool_calls", data.get("tools", []))
            if isinstance(raw_tools, list):
                for tc in raw_tools:
                    if isinstance(tc, dict):
                        tool_calls.append({
                            "tool": tc.get("name", tc.get("tool", "unknown")),
                            "input": tc.get("input", tc.get("args", {})),
                            "result": tc.get("result", "(opencode-managed)"),
                        })

        elif isinstance(data, list):
            # Array of content blocks
            text = "\n".join(
                item.get("text", str(item)) for item in data
                if isinstance(item, dict)
            ) or stdout

    except (json.JSONDecodeError, ValueError):
        # Not JSON — use raw text
        text = stdout.strip()

    if not text:
        text = stdout.strip() or "(no output)"

    return {
        "text": text[:10000],  # Cap output size
        "tokens": 0,  # Calculated by caller
        "tool_calls": tool_calls,
        "cost_usd": 0.0,  # Calculated by caller
    }


async def execute_with_fallback(
    prompt: str,
    workspace: str = ".",
    timeout: int = DEFAULT_TIMEOUT,
    job_id: str = "",
    phase: str = "",
    priority: str = "P2",
    guardrails=None,
    system_prompt: str = "",
) -> dict:
    """
    Execute via cheap LLM backends, falling back to expensive SDK only as last resort.

    Fallback chain: OpenCode (Gemini 2.5 Flash, ~$0.001) → Grok (xAI, ~$0.0004)
                    → MiniMax (M2.5, ~$0.003) → Agent SDK (Anthropic, ~$0.02-0.50/job)

    Returns: Standard result dict with "text", "tokens", "tool_calls", "cost_usd"
    """
    # Primary: OpenCode (Gemini 2.5 Flash via rebuilt binary, ~$0.001/job)
    try:
        logger.info(f"Executing via OpenCode for {job_id}/{phase}")
        oc_result = await run_opencode(
            prompt=prompt,
            workspace=workspace,
            timeout=timeout,
            job_id=job_id,
            phase=phase,
        )
        if oc_result and oc_result.get("text"):
            logger.info(f"OpenCode completed {job_id}/{phase} for ${oc_result.get('cost_usd', 0):.6f}")
            return oc_result
        logger.warning(f"OpenCode returned empty response for {job_id}/{phase} — trying Grok")
    except OpenCodeError as oc_err:
        logger.warning(f"OpenCode failed for {job_id}/{phase}: {oc_err} — trying Grok")
    except Exception as oc_err:
        logger.warning(f"OpenCode unexpected error for {job_id}/{phase}: {oc_err} — trying Grok")

    # Secondary: Grok (xAI API, ~$0.0004/job via grok-3-mini)
    try:
        from grok_executor import execute_with_grok

        logger.info(f"Executing via Grok for {job_id}/{phase}")
        grok_result = await execute_with_grok(
            prompt=prompt,
            job_id=job_id,
            phase=phase,
            priority=priority,
            system_prompt=system_prompt or "",
        )
        if grok_result and grok_result.get("text"):
            logger.info(f"Grok completed {job_id}/{phase} for ${grok_result.get('cost_usd', 0):.4f}")
            return grok_result
        logger.warning(f"Grok returned empty response for {job_id}/{phase} — falling back to SDK")
    except ImportError:
        logger.warning("grok_executor not available — falling back to SDK")
    except Exception as grok_err:
        logger.warning(f"Grok failed for {job_id}/{phase}: {grok_err} — trying MiniMax")

    # Tertiary: MiniMax (M2.5 API, ~$0.003/job, 80.2% SWE-Bench)
    try:
        from minimax_executor import execute_with_minimax

        logger.info(f"Executing via MiniMax for {job_id}/{phase}")
        mm_result = await execute_with_minimax(
            prompt=prompt,
            job_id=job_id,
            phase=phase,
            priority=priority,
            system_prompt=system_prompt or "",
        )
        if mm_result and mm_result.get("text"):
            logger.info(f"MiniMax completed {job_id}/{phase} for ${mm_result.get('cost_usd', 0):.4f}")
            return mm_result
        logger.warning(f"MiniMax returned empty response for {job_id}/{phase} — falling back to SDK")
    except ImportError:
        logger.warning("minimax_executor not available — falling back to SDK")
    except Exception as mm_err:
        logger.warning(f"MiniMax failed for {job_id}/{phase}: {mm_err} — falling back to SDK")

    # Last resort: Agent SDK (costs real API money)
    from autonomous_runner import _call_agent_sdk

    logger.info(f"Falling back to Agent SDK for {job_id}/{phase}")
    return await _call_agent_sdk(
        prompt=prompt,
        system_prompt=system_prompt,
        job_id=job_id,
        phase=phase,
        priority=priority,
        guardrails=guardrails,
        workspace=workspace,
    )


class OpenCodeError(Exception):
    """Raised when OpenCode CLI execution fails."""
    pass
