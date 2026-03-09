"""
GitHub Job Bridge — Routes OpenClaw jobs through GitHub Issues + claude-code-action.

Instead of calling the Anthropic API directly (which costs real money), this creates
a GitHub issue with the job prompt. A GitHub Actions workflow picks it up and runs
Claude Code using the Max Plan OAuth token ($0 per-token cost).

Flow: create issue → label triggers workflow → claude-code-action runs → result posted as comment → poll & return
"""

import asyncio
import json
import logging
import subprocess
import time

logger = logging.getLogger("openclaw.github_bridge")

REPO = "Miles0sage/openclaw"
LABEL = "openclaw-job"
POLL_INTERVAL = 30  # seconds between polls
MAX_POLL_TIME = 900  # 15 minutes max wait


async def _run_gh(args: list[str]) -> str:
    """Run a gh CLI command asynchronously and return stdout."""
    cmd = ["gh"] + args
    loop = asyncio.get_running_loop()
    proc = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=30),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh command failed: {' '.join(cmd)}\nstderr: {proc.stderr}")
    return proc.stdout.strip()


async def submit_job(prompt: str, job_id: str, phase: str, priority: str) -> int:
    """Create a GitHub issue with the job prompt. Returns issue number."""
    title = f"[OpenClaw Job] {job_id[:8]} / {phase}"
    # Metadata header + full prompt as body
    body = (
        f"<!-- openclaw-job -->\n"
        f"**Job ID:** `{job_id}`\n"
        f"**Phase:** `{phase}`\n"
        f"**Priority:** `{priority}`\n\n"
        f"---\n\n"
        f"{prompt}"
    )

    result = await _run_gh([
        "issue", "create",
        "--repo", REPO,
        "--title", title,
        "--body", body,
        "--label", LABEL,
    ])

    # gh issue create returns the URL like https://github.com/owner/repo/issues/123
    issue_number = int(result.rstrip("/").split("/")[-1])
    logger.info(f"Created GitHub issue #{issue_number} for {job_id}/{phase}")
    return issue_number


async def poll_for_result(issue_number: int) -> dict:
    """Poll issue comments until claude-code-action posts results."""
    start = time.monotonic()

    while time.monotonic() - start < MAX_POLL_TIME:
        await asyncio.sleep(POLL_INTERVAL)

        try:
            comments_json = await _run_gh([
                "api", f"repos/{REPO}/issues/{issue_number}/comments",
                "--jq", ".[].body",
            ])
        except Exception as e:
            logger.warning(f"Poll error for issue #{issue_number}: {e}")
            continue

        if not comments_json.strip():
            continue

        # claude-code-action posts comments from github-actions[bot]
        # The comment contains the Claude Code output
        # We take the last comment as the result
        comments = comments_json.strip().split("\n")
        if comments:
            result_text = comments[-1]
            # If it looks like a real result (not just a status update)
            if len(result_text) > 20:
                logger.info(f"Got result from issue #{issue_number} ({len(result_text)} chars)")

                # Close the issue
                try:
                    await _run_gh([
                        "issue", "close", str(issue_number),
                        "--repo", REPO,
                        "--comment", "Job completed — closed by OpenClaw bridge.",
                    ])
                except Exception as close_err:
                    logger.warning(f"Failed to close issue #{issue_number}: {close_err}")

                return {
                    "text": result_text,
                    "tokens": 0,
                    "cost_usd": 0.0,
                }

    # Timed out
    logger.error(f"Timed out waiting for result on issue #{issue_number}")

    # Close the issue as timed out
    try:
        await _run_gh([
            "issue", "close", str(issue_number),
            "--repo", REPO,
            "--comment", "Job timed out after 15 minutes — closed by OpenClaw bridge.",
        ])
    except Exception:
        pass

    return {
        "text": f"GitHub Actions job timed out after {MAX_POLL_TIME}s (issue #{issue_number})",
        "tokens": 0,
        "cost_usd": 0.0,
    }


async def execute_via_github(prompt: str, job_id: str, phase: str, priority: str) -> dict:
    """Full flow: submit issue → poll for result → return."""
    issue_number = await submit_job(prompt, job_id, phase, priority)
    return await poll_for_result(issue_number)
