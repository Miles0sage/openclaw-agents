"""
Oz Executor — Warp Oz Cloud Agent execution backend for OpenClaw jobs.
=====================================================================
Uses `oz agent run-cloud` to dispatch tasks to Warp's cloud infrastructure,
then polls `oz run get` for completion. Provides access to 43+ models
including GPT-5.3, Claude 4.6, Gemini 3 Pro via Warp's auto-model routing.

Cloud agents run in Docker environments with full tool access (file I/O,
shell commands, git) — perfect for complex P0/P1 tasks that need more
power than OpenCode's Gemini Flash.

Execution chain: Oz Cloud (auto-model) → OpenCode (Gemini Flash) → SDK (Haiku/Sonnet)

Usage:
    from oz_executor import run_oz_cloud, execute_with_oz_fallback

    result = await run_oz_cloud(prompt="Fix the auth bug", environment="wguVnlBs2L6GmchuiGLKAL")
    result = await execute_with_oz_fallback(prompt, workspace, job_id, phase)
"""

import asyncio
import json
import logging
import os
import re
import time
from typing import Optional

from cost_tracker import log_cost_event

logger = logging.getLogger("oz_executor")

OZ_BIN = os.environ.get("OZ_BIN", "/usr/bin/oz")

# Default timeout (seconds) — reduced from 300 to 120 based on data:
# Successful Oz calls average 109s (max 260s), but 61% of execute phases
# timeout at 300s. 120s captures 95%+ of successes while saving ~180s per timeout.
DEFAULT_TIMEOUT = 120

# Poll interval (seconds) — how often to check run status
POLL_INTERVAL = 5

# Job-level circuit breaker: skip Oz after this many failures in a single job.
# Prevents wasting 120s * N on consecutive timeouts within the same job pipeline.
OZ_MAX_FAILURES_PER_JOB = 2

# Track Oz failures per job for circuit breaker
_oz_job_failures: dict[str, int] = {}

# OpenClaw cloud environment ID (has Miles0sage repos)
OPENCLAW_ENV_ID = os.environ.get("OZ_ENVIRONMENT_ID", "wguVnlBs2L6GmchuiGLKAL")

# Model selection per priority/complexity
OZ_MODELS = {
    "P0": "auto-genius",       # Best available (GPT-5.3, Claude 4.6 Opus)
    "P1": "auto",              # Smart auto-selection
    "P2": "auto-efficient",    # Cost-optimized
    "P3": "auto-efficient",    # Cost-optimized
    "default": "auto-efficient",
}

# Cost estimation per model tier (Warp credits, approximate $/1M tokens)
OZ_COST_TIERS = {
    "auto-genius": {"input": 5.00, "output": 25.00},
    "auto": {"input": 2.00, "output": 10.00},
    "auto-efficient": {"input": 0.50, "output": 2.00},
}


async def run_oz_cloud(
    prompt: str,
    environment: str = "",
    timeout: int = DEFAULT_TIMEOUT,
    job_id: str = "",
    phase: str = "",
    model: str = "auto-efficient",
    name: str = "",
    use_environment: bool = True,
) -> dict:
    """
    Execute a prompt via Oz cloud agent (run-cloud).

    Dispatches to Warp cloud, polls for completion, returns result.

    Returns: {
        "text": str,         # Agent's status/summary text
        "tokens": int,       # Estimated token count
        "tool_calls": list,  # (empty for cloud — not available via CLI)
        "cost_usd": float,   # Estimated cost
        "source": "oz",
        "model": str,
        "conversation_id": str,  # Warp session URL
        "run_id": str,           # Oz run ID
    }

    Raises:
        OzError: On dispatch failure, timeout, or task failure.
    """
    if not os.path.isfile(OZ_BIN):
        raise OzError(f"Oz binary not found at {OZ_BIN}")

    task_name = name or (f"openclaw-{job_id}-{phase}" if job_id else "openclaw-task")
    env_id = environment or OPENCLAW_ENV_ID

    cmd = [
        OZ_BIN, "agent", "run-cloud",
        "--prompt", prompt,
        "--model", model,
        "--name", task_name,
    ]

    if use_environment and env_id:
        cmd.extend(["--environment", env_id])
    else:
        cmd.append("--no-environment")

    logger.info(
        f"Oz cloud dispatch: job={job_id} phase={phase} model={model} "
        f"env={env_id if use_environment else 'none'} timeout={timeout}s"
    )

    start_time = time.time()

    # Step 1: Dispatch the cloud agent
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "NO_COLOR": "1"},
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=30
        )
    except asyncio.TimeoutError:
        try:
            process.kill()
            await process.wait()
        except Exception:
            pass
        raise OzError(f"Oz dispatch timed out after 30s for job={job_id}")
    except Exception as e:
        raise OzError(f"Oz dispatch failed: {e}") from e

    output = stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")

    # Extract run ID from output like "Spawned ambient agent with run ID: <uuid>"
    run_id = _extract_run_id(output)
    if not run_id:
        raise OzError(f"Failed to extract run ID from Oz output: {output[:500]}")

    # Extract session URL
    session_url = ""
    url_match = re.search(r"https://app\.warp\.dev/conversation/[a-f0-9-]+", output)
    if url_match:
        session_url = url_match.group(0)

    logger.info(f"Oz dispatched: run_id={run_id} session={session_url}")

    # Step 2: Poll for completion
    result_text = ""
    status = "InProgress"
    poll_count = 0
    deadline = start_time + timeout

    while time.time() < deadline:
        await asyncio.sleep(POLL_INTERVAL)
        poll_count += 1

        try:
            poll_result = await _poll_run_status(run_id)
            status = poll_result["status"]
            result_text = poll_result["text"]

            if status in ("Succeeded", "Failed", "Cancelled"):
                break

        except Exception as e:
            logger.warning(f"Oz poll error (attempt {poll_count}): {e}")
            if poll_count > 3:
                raise OzError(f"Oz polling failed after {poll_count} attempts: {e}")

    elapsed = time.time() - start_time

    if status == "InProgress":
        raise OzError(
            f"Oz cloud agent timed out after {elapsed:.0f}s for "
            f"job={job_id} phase={phase} run_id={run_id}"
        )

    if status == "Failed":
        raise OzError(
            f"Oz cloud agent failed for job={job_id} phase={phase}: {result_text[:500]}"
        )

    if status == "Cancelled":
        raise OzError(f"Oz cloud agent was cancelled: run_id={run_id}")

    if not result_text or len(result_text.strip()) < 10:
        raise OzError(
            f"Oz cloud agent returned empty result for "
            f"job={job_id} phase={phase} run_id={run_id}"
        )

    # Step 3: Build result
    cost_tier = OZ_COST_TIERS.get(model, OZ_COST_TIERS["auto-efficient"])
    est_input_tokens = len(prompt) // 4
    est_output_tokens = len(result_text) // 4
    total_tokens = est_input_tokens + est_output_tokens
    cost_usd = round(
        (est_input_tokens * cost_tier["input"]
         + est_output_tokens * cost_tier["output"]) / 1_000_000,
        6,
    )

    log_cost_event(
        project="openclaw",
        agent="oz",
        model=f"oz-{model}",
        tokens_input=est_input_tokens,
        tokens_output=est_output_tokens,
        cost=cost_usd,
        event_type="oz_cloud_call",
        metadata={
            "phase": phase,
            "elapsed_s": round(elapsed, 2),
            "run_id": run_id,
            "session_url": session_url,
            "poll_count": poll_count,
        },
        job_id=job_id,
    )

    logger.info(
        f"Oz cloud complete: job={job_id} phase={phase} model={model} "
        f"status={status} elapsed={elapsed:.1f}s cost=${cost_usd:.6f} "
        f"tokens={total_tokens} polls={poll_count}"
    )

    return {
        "text": result_text[:10000],
        "tokens": total_tokens,
        "tool_calls": [],
        "cost_usd": cost_usd,
        "source": "oz",
        "model": model,
        "conversation_id": session_url,
        "run_id": run_id,
    }


def _extract_run_id(output: str) -> str:
    """Extract run ID from Oz dispatch output."""
    # Pattern: "Spawned ambient agent with run ID: <uuid>"
    match = re.search(r"run ID:\s*([a-f0-9-]{36})", output)
    if match:
        return match.group(1)
    # Fallback: any UUID-like string
    match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", output)
    return match.group(1) if match else ""


async def _poll_run_status(run_id: str) -> dict:
    """Poll Oz run status. Returns {"status": str, "text": str}."""
    cmd = [OZ_BIN, "run", "get", run_id, "--output-format", "text"]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "NO_COLOR": "1"},
    )
    stdout, stderr = await asyncio.wait_for(
        process.communicate(), timeout=15
    )
    output = stdout.decode("utf-8", errors="replace")

    # Parse status from output
    status = "InProgress"
    text = ""

    if "Succeeded" in output:
        status = "Succeeded"
    elif "Failed" in output:
        status = "Failed"
    elif "Cancelled" in output:
        status = "Cancelled"

    # Extract status/summary text from the output
    # Format: "│ Status: <text> │"
    status_match = re.search(r"Status:\s*(.+?)(?:\s*│\s*$|\s*$)", output, re.MULTILINE)
    if status_match:
        text = status_match.group(1).strip()
        # Multi-line status: collect continuation lines
        lines = output.split("\n")
        collecting = False
        collected = []
        for line in lines:
            if "Status:" in line:
                collecting = True
                collected.append(status_match.group(1).strip())
                continue
            if collecting:
                # Status continues until next section marker (├ or ╰ or Session:)
                clean = line.strip().strip("│").strip()
                if clean.startswith(("├", "╰", "Session:", "Created:")):
                    break
                if clean:
                    collected.append(clean)
        text = " ".join(collected) if collected else text

    return {"status": status, "text": text}


async def execute_with_oz_fallback(
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
    Execute via Oz Cloud first, fall back to OpenCode, then SDK.

    Oz handles complex tasks (P0/P1) with GPT-5.3/Claude 4.6 Opus.
    OpenCode handles routine tasks (P2/P3) with Gemini Flash.
    SDK is the safety net.
    """
    model = OZ_MODELS.get(priority, OZ_MODELS["default"])

    # Determine if we need an environment (code tasks) or not (reasoning tasks)
    code_phases = {"execute", "verify", "deliver"}
    use_env = phase.lower() in code_phases if phase else False

    # SKIP Oz for execute/verify/deliver phases — Oz cloud containers are ephemeral.
    # Execute: file changes made inside the container are lost when it terminates.
    #   Multi-step execution is worse: each step is a new container, so cross-step
    #   changes vanish. Oz "success" on execute is a false positive — verify then
    #   finds the host files unchanged. All successful jobs use OpenCode for execute.
    # Verify/Deliver: inspect locally-modified files from execute phase; Oz can't
    #   see local changes since it has a stale repo snapshot.
    skip_oz_phases = {"execute", "verify", "deliver"}
    skip_oz = phase.lower() in skip_oz_phases if phase else False

    # Circuit breaker: skip Oz if it has failed too many times for this job
    job_key = job_id or "unknown"
    oz_failures = _oz_job_failures.get(job_key, 0)
    if oz_failures >= OZ_MAX_FAILURES_PER_JOB:
        logger.info(
            f"Oz circuit breaker: skipping for {job_id}/{phase} "
            f"({oz_failures} prior failures in this job)"
        )
        skip_oz = True

    # Try Oz first (unless skipping)
    if not skip_oz:
        try:
            full_prompt = prompt
            if system_prompt:
                full_prompt = f"{system_prompt}\n\n---\n\n{prompt}"

            # Oz cloud agents run in Docker containers where projects mount at /workspace/
            # Translate host paths so the agent finds files at the correct location
            if use_env and workspace:
                import re as _re
                oz_workspace = _re.sub(r"/root/", "/workspace/", workspace)
                full_prompt = full_prompt.replace(workspace, oz_workspace)
                full_prompt = _re.sub(
                    r"/root/(openclaw|Delhi-Palace|Barber-CRM|Mathcad-Scripts|concrete-canoe-project2026)\b",
                    r"/workspace/\1",
                    full_prompt,
                )
                logger.info(f"Oz path normalization: {workspace} → {oz_workspace}")

            result = await run_oz_cloud(
                prompt=full_prompt,
                timeout=timeout,
                job_id=job_id,
                phase=phase,
                model=model,
                use_environment=use_env,
            )

            if result["text"] and len(result["text"].strip()) > 20:
                logger.info(f"Oz cloud succeeded for {job_id}/{phase}")
                # Reset circuit breaker on success
                _oz_job_failures.pop(job_key, None)
                return result

            logger.warning(
                f"Oz returned empty/short result for {job_id}/{phase}, "
                f"falling back to OpenCode"
            )

        except OzError as e:
            _oz_job_failures[job_key] = oz_failures + 1
            logger.warning(
                f"Oz cloud failed for {job_id}/{phase}: {e} — "
                f"falling back to OpenCode (failures={oz_failures + 1})"
            )

        except Exception as e:
            _oz_job_failures[job_key] = oz_failures + 1
            logger.error(
                f"Unexpected Oz error for {job_id}/{phase}: {e} — "
                f"falling back to OpenCode (failures={oz_failures + 1})"
            )
    else:
        logger.info(
            f"Skipping Oz for {job_id}/{phase} — "
            f"{'circuit breaker' if oz_failures >= OZ_MAX_FAILURES_PER_JOB else 'verify/deliver needs local file access'}"
        )

    # Fall back to OpenClaw IDE (native Gemini tool calling with all MCP tools)
    try:
        from openclaw_ide import execute_ide_with_fallback
        logger.info(f"Falling back to OpenClaw IDE for {job_id}/{phase}")
        return await execute_ide_with_fallback(
            prompt=prompt,
            workspace=workspace,
            job_id=job_id,
            phase=phase,
            priority=priority,
            guardrails=guardrails,
            system_prompt=system_prompt,
        )
    except Exception as e:
        logger.error(f"OpenClaw IDE fallback also failed for {job_id}/{phase}: {e}")

    # Final fallback to SDK
    from autonomous_runner import _call_agent_sdk
    logger.info(f"Final fallback to SDK for {job_id}/{phase}")
    return await _call_agent_sdk(
        prompt=prompt,
        system_prompt=system_prompt,
        job_id=job_id,
        phase=phase,
        priority=priority,
        guardrails=guardrails,
        workspace=workspace,
    )


class OzError(Exception):
    """Raised when Oz cloud execution fails."""
    pass
