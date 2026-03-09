"""
PC Dispatcher — Send coding tasks to Miles' Windows PC via SSH over Tailscale.

Manages job dispatching to the PC, tracks execution status, and retrieves results.
- SSH into PC via Tailscale IP: 100.67.6.27
- Run Claude Code headless on PC
- Also supports Ollama inference on PC
"""

import os
import asyncio
import json
import logging
import uuid
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger("pc_dispatcher")

# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

PC_TAILSCALE_IP = os.getenv("PC_TAILSCALE_IP", "100.67.6.27")
PC_SSH_USER = os.getenv("PC_SSH_USER", "Miles")
PC_CLAUDE_BIN = os.getenv("PC_CLAUDE_BIN", "C:\\Users\\Miles\\.local\\bin\\claude.exe")
PC_OLLAMA_URL = os.getenv("PC_OLLAMA_URL", "http://100.67.6.27:11434")
PC_OLLAMA_MODEL = os.getenv("PC_OLLAMA_MODEL", "qwen2.5-coder:7b")

# Job storage (in-memory + disk)
JOBS_DIR = Path(os.getenv("OPENCLAW_DATA_DIR", "./data")) / "pc_jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

# In-memory job cache
_job_cache: Dict[str, Dict[str, Any]] = {}

# ═══════════════════════════════════════════════════════════════════════════
# Job Management
# ═══════════════════════════════════════════════════════════════════════════


def _generate_job_id() -> str:
    """Generate a unique job ID."""
    return f"pc_{uuid.uuid4().hex[:12]}"


def _get_job_path(job_id: str) -> Path:
    """Get the on-disk path for a job."""
    return JOBS_DIR / f"{job_id}.json"


def create_pc_job(
    task_type: str,
    prompt: str,
    timeout: int = 300,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Create a new PC dispatch job.

    Args:
        task_type: "claude_code" or "ollama"
        prompt: The task to execute
        timeout: Job timeout in seconds (default 300s)
        metadata: Additional metadata

    Returns:
        job_id: Unique job identifier
    """
    job_id = _generate_job_id()
    now = datetime.now(timezone.utc).isoformat()

    job = {
        "job_id": job_id,
        "task_type": task_type,
        "prompt": prompt,
        "timeout": timeout,
        "status": "pending",  # pending, running, completed, failed
        "created_at": now,
        "started_at": None,
        "completed_at": None,
        "result": None,
        "error": None,
        "metadata": metadata or {},
    }

    # Save to disk
    job_path = _get_job_path(job_id)
    with open(job_path, "w") as f:
        json.dump(job, f, indent=2)

    # Cache in memory
    _job_cache[job_id] = job

    logger.info(f"Created PC job: {job_id} (type={task_type}, timeout={timeout}s)")
    return job_id


def get_pc_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a job by ID."""
    # Try cache first
    if job_id in _job_cache:
        return _job_cache[job_id]

    # Try disk
    job_path = _get_job_path(job_id)
    if job_path.exists():
        with open(job_path, "r") as f:
            job = json.load(f)
            _job_cache[job_id] = job
            return job

    return None


def update_pc_job(job_id: str, **updates) -> bool:
    """Update a job's status."""
    job = get_pc_job(job_id)
    if not job:
        return False

    # Update fields
    for key, value in updates.items():
        if key in job:
            job[key] = value

    # Save to disk
    job_path = _get_job_path(job_id)
    with open(job_path, "w") as f:
        json.dump(job, f, indent=2)

    # Update cache
    _job_cache[job_id] = job

    return True


def list_pc_jobs(status: Optional[str] = None) -> list[Dict[str, Any]]:
    """List all PC jobs, optionally filtered by status."""
    jobs = []

    # Scan disk
    for job_path in JOBS_DIR.glob("*.json"):
        with open(job_path, "r") as f:
            job = json.load(f)
            _job_cache[job["job_id"]] = job
            jobs.append(job)

    # Filter by status
    if status:
        jobs = [j for j in jobs if j["status"] == status]

    # Sort by created_at desc
    jobs.sort(key=lambda j: j["created_at"], reverse=True)

    return jobs


# ═══════════════════════════════════════════════════════════════════════════
# PC Connectivity
# ═══════════════════════════════════════════════════════════════════════════


async def check_pc_health() -> Dict[str, Any]:
    """
    Check if PC is reachable via SSH over Tailscale.

    Returns:
        {
            "healthy": bool,
            "status": str,
            "pc_ip": str,
            "ssh_latency_ms": float,
            "claude_available": bool,
            "ollama_available": bool,
            "timestamp": str
        }
    """
    result = {
        "healthy": False,
        "status": "unknown",
        "pc_ip": PC_TAILSCALE_IP,
        "ssh_latency_ms": None,
        "claude_available": False,
        "ollama_available": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Test SSH connectivity
    ssh_start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            "ssh",
            f"{PC_SSH_USER}@{PC_TAILSCALE_IP}",
            "echo ok",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

        if proc.returncode == 0 and b"ok" in stdout:
            result["healthy"] = True
            result["status"] = "ssh_ok"
            result["ssh_latency_ms"] = (time.time() - ssh_start) * 1000
        else:
            result["status"] = f"ssh_error: {stderr.decode()[:100]}"
    except asyncio.TimeoutError:
        result["status"] = "ssh_timeout"
    except Exception as e:
        result["status"] = f"ssh_failed: {str(e)[:100]}"

    # Check Claude availability (if SSH is OK)
    if result["healthy"]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ssh",
                f"{PC_SSH_USER}@{PC_TAILSCALE_IP}",
                f'cmd /c "{PC_CLAUDE_BIN}" --version',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode == 0:
                result["claude_available"] = True
        except Exception as e:
            logger.warning(f"Claude check failed: {e}")

    # Check Ollama availability
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{PC_OLLAMA_URL}/api/tags")
            if resp.status_code == 200:
                result["ollama_available"] = True
    except Exception as e:
        logger.warning(f"Ollama check failed: {e}")

    return result


# ═══════════════════════════════════════════════════════════════════════════
# Task Execution
# ═══════════════════════════════════════════════════════════════════════════


async def dispatch_claude_code(job_id: str, prompt: str, timeout: int = 300) -> None:
    r"""
    Dispatch a task to Claude Code on the PC via SSH.

    For long prompts (>1KB), writes to a temporary file and passes file path.
    For short prompts, passes directly as argument.

    Updates job status as it progresses.
    """
    job = get_pc_job(job_id)
    if not job:
        logger.error(f"Job {job_id} not found")
        return

    def _ps_single_quote(value: str) -> str:
        """Escape single quotes for PowerShell single-quoted strings."""
        return value.replace("'", "''")

    try:
        # Mark job as running
        update_pc_job(job_id, status="running", started_at=datetime.now(timezone.utc).isoformat())

        # Determine if prompt is long enough to require file-based approach
        # Windows command line limit is ~8KB, but leave buffer for other args
        use_file = len(prompt) > 1024

        if use_file:
            # For long prompts: write to temp file on PC, pass file path to Claude
            # This avoids shell escaping issues and command-line length limits
            import tempfile

            # Stage prompt and runner script locally
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as tmp:
                tmp.write(prompt)
                local_prompt_path = tmp.name

            pc_tmp_path = f"C:\\Users\\{PC_SSH_USER}\\AppData\\Local\\Temp\\openclaw_prompt_{job_id}.txt"
            pc_script_path = f"C:\\Users\\{PC_SSH_USER}\\AppData\\Local\\Temp\\openclaw_run_{job_id}.ps1"
            script_content = "\n".join(
                [
                    "$ErrorActionPreference = 'Stop'",
                    "$exitCode = 1",
                    "try {",
                    f"    $prompt = [System.IO.File]::ReadAllText('{_ps_single_quote(pc_tmp_path)}')",
                    f"    & '{_ps_single_quote(PC_CLAUDE_BIN)}' -p $prompt --output-format json",
                    "    $exitCode = $LASTEXITCODE",
                    "}",
                    "finally {",
                    f"    Remove-Item '{_ps_single_quote(pc_tmp_path)}' -Force -ErrorAction SilentlyContinue",
                    "}",
                    "exit $exitCode",
                    "",
                ]
            )

            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".ps1",
                delete=False,
                encoding="utf-8",
                newline="\n",
            ) as tmp_script:
                tmp_script.write(script_content)
                local_script_path = tmp_script.name

            try:
                for local_path, remote_path in (
                    (local_prompt_path, pc_tmp_path),
                    (local_script_path, pc_script_path),
                ):
                    scp_proc = await asyncio.create_subprocess_exec(
                        "scp",
                        local_path,
                        f"{PC_SSH_USER}@{PC_TAILSCALE_IP}:{remote_path}",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _, scp_stderr = await asyncio.wait_for(scp_proc.communicate(), timeout=30)

                    if scp_proc.returncode != 0:
                        raise Exception(f"SCP failed: {scp_stderr.decode()}")

                # Execute uploaded script directly to avoid inline escaping issues
                ps_cmd = f'powershell -NoProfile -ExecutionPolicy Bypass -File "{pc_script_path}"'
                logger.info(f"Dispatching job {job_id} to PC (file-based script, {len(prompt)} bytes)")
            finally:
                for local_path in (local_prompt_path, local_script_path):
                    try:
                        os.remove(local_path)
                    except Exception:
                        pass
        else:
            # Short prompt - pass directly as argument
            # Escape for PowerShell (simpler escaping since it's short)
            escaped_prompt = prompt.replace('\\', '\\\\').replace('"', '\\"').replace('$', '`$')

            ps_cmd = (
                f'powershell -NoProfile -Command "& '
                f"'{PC_CLAUDE_BIN}' -p \\\"{escaped_prompt}\\\" --output-format json\""
            )
            logger.info(f"Dispatching job {job_id} to PC (arg-based, {len(prompt)} bytes)")

        # SSH to PC and execute
        proc = await asyncio.create_subprocess_exec(
            "ssh",
            f"{PC_SSH_USER}@{PC_TAILSCALE_IP}",
            ps_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            update_pc_job(
                job_id,
                status="failed",
                completed_at=datetime.now(timezone.utc).isoformat(),
                error=f"Timeout after {timeout}s",
            )
            logger.error(f"Job {job_id} timed out")
            return

        # Parse result
        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")

        if proc.returncode == 0:
            # Try to parse JSON response
            try:
                result = json.loads(stdout_str)
                update_pc_job(
                    job_id,
                    status="completed",
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    result=result,
                )
                logger.info(f"Job {job_id} completed successfully")
            except json.JSONDecodeError:
                # If not JSON, return as raw text
                update_pc_job(
                    job_id,
                    status="completed",
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    result={"output": stdout_str},
                )
                logger.info(f"Job {job_id} completed (non-JSON output)")
        else:
            error_msg = stderr_str or stdout_str or f"Command failed with code {proc.returncode}"
            update_pc_job(
                job_id,
                status="failed",
                completed_at=datetime.now(timezone.utc).isoformat(),
                error=error_msg[:1000],
            )
            logger.error(f"Job {job_id} failed: {error_msg[:200]}")

    except Exception as e:
        logger.error(f"Job {job_id} exception: {e}")
        update_pc_job(
            job_id,
            status="failed",
            completed_at=datetime.now(timezone.utc).isoformat(),
            error=str(e)[:500],
        )


async def dispatch_ollama(
    job_id: str, prompt: str, model: str = PC_OLLAMA_MODEL, timeout: int = 300
) -> None:
    """
    Dispatch an inference request to Ollama on the PC.

    Makes a direct HTTP request to PC's Ollama at 100.67.6.27:11434
    """
    job = get_pc_job(job_id)
    if not job:
        logger.error(f"Job {job_id} not found")
        return

    try:
        import httpx

        update_pc_job(job_id, status="running", started_at=datetime.now(timezone.utc).isoformat())

        logger.info(f"Dispatching Ollama job {job_id} to {PC_OLLAMA_URL}")

        async with httpx.AsyncClient(timeout=timeout + 10) as client:
            response = await asyncio.wait_for(
                client.post(
                    f"{PC_OLLAMA_URL}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                    },
                ),
                timeout=timeout,
            )

        if response.status_code == 200:
            result = response.json()
            update_pc_job(
                job_id,
                status="completed",
                completed_at=datetime.now(timezone.utc).isoformat(),
                result=result,
            )
            logger.info(f"Ollama job {job_id} completed")
        else:
            error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
            update_pc_job(
                job_id,
                status="failed",
                completed_at=datetime.now(timezone.utc).isoformat(),
                error=error_msg,
            )
            logger.error(f"Ollama job {job_id} failed: {error_msg}")

    except asyncio.TimeoutError:
        update_pc_job(
            job_id,
            status="failed",
            completed_at=datetime.now(timezone.utc).isoformat(),
            error=f"Timeout after {timeout}s",
        )
        logger.error(f"Ollama job {job_id} timed out")
    except Exception as e:
        logger.error(f"Ollama job {job_id} exception: {e}")
        update_pc_job(
            job_id,
            status="failed",
            completed_at=datetime.now(timezone.utc).isoformat(),
            error=str(e)[:500],
        )


# ═══════════════════════════════════════════════════════════════════════════
# Background Job Runner
# ═══════════════════════════════════════════════════════════════════════════

_running_jobs = set()


async def execute_job_background(job_id: str) -> None:
    """Execute a job in the background (non-blocking)."""
    if job_id in _running_jobs:
        logger.warning(f"Job {job_id} already running")
        return

    _running_jobs.add(job_id)
    try:
        job = get_pc_job(job_id)
        if not job:
            return

        if job["task_type"] == "claude_code":
            await dispatch_claude_code(job_id, job["prompt"], job["timeout"])
        elif job["task_type"] == "ollama":
            await dispatch_ollama(job_id, job["prompt"], PC_OLLAMA_MODEL, job["timeout"])
        else:
            update_pc_job(
                job_id,
                status="failed",
                error=f"Unknown task_type: {job['task_type']}",
            )
    finally:
        _running_jobs.discard(job_id)
