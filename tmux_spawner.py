"""
tmux_spawner.py — Elvis-pattern tmux-based agent spawning for OpenClaw

Spawns parallel Claude Code agents in tmux panes, each with optional
git worktree isolation. Supports auto-respawn with improved prompts
(Ralph Loop V2).

Usage:
    from tmux_spawner import TmuxSpawner
    spawner = TmuxSpawner()
    pane_id = spawner.spawn_agent("job-123", "Fix the login bug", worktree_repo="/root/Delhi-Palace")
    output = spawner.collect_output(pane_id)
"""

import os
import subprocess
import json
import time
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger("tmux_spawner")

# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════

TMUX_SESSION = "openclaw-agents"
WORKTREE_BASE = "./.worktrees"
LOG_FILE = "./data/tmux_agents.log"
DEFAULT_REPO = "."
CLAUDE_CMD = "/root/.local/bin/claude"  # Claude Code CLI (full path for tmux)
# Full tool access mode for spawned agents.
# --allowedTools with wildcards gives full tool access without interactive prompts.
# --dangerously-skip-permissions doesn't work as root, so we use allowedTools instead.
CLAUDE_FULL_ACCESS = '--allowedTools "Bash(*)" "Read(*)" "Write(*)" "Edit(*)" "Glob(*)" "Grep(*)" "WebSearch(*)" "WebFetch(*)"'


def _log(msg: str):
    """Append to the tmux agents log file."""
    try:
        Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def _run(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    """Run a subprocess command and return result."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _tmux(*args, timeout: int = 10) -> subprocess.CompletedProcess:
    """Run a tmux command."""
    return _run(["tmux"] + list(args), timeout=timeout)


class TmuxSpawner:
    """Manages Claude Code agent panes in a tmux session."""

    def __init__(self, session_name: str = TMUX_SESSION):
        self.session = session_name
        self._ensure_session()

    def _ensure_session(self):
        """Create the tmux session if it doesn't exist."""
        check = _tmux("has-session", "-t", self.session)
        if check.returncode != 0:
            # Create detached session with a placeholder window
            _tmux("new-session", "-d", "-s", self.session, "-n", "control")
            _log(f"Created tmux session: {self.session}")

    def _load_workspace_bootstrap(self) -> str:
        """
        Load workspace .md files for agent bootstrap context.
        Returns concatenated content of IDENTITY.md, USER.md, HEARTBEAT.md, TOOLS.md
        plus today's daily log. All files sized for token efficiency (~2KB each).
        """
        workspace = Path("./workspace")
        if not workspace.exists():
            return ""

        bootstrap_files = ["IDENTITY.md", "USER.md", "HEARTBEAT.md", "TOOLS.md"]
        parts = []

        # Load fixed bootstrap files
        for fname in bootstrap_files:
            fpath = workspace / fname
            if fpath.exists():
                try:
                    content = fpath.read_text(encoding="utf-8")
                    # Limit each file to 2000 chars to keep bootstrap token-efficient
                    parts.append(f"## {fname}\n{content[:2000]}")
                except Exception as e:
                    _log(f"Failed to load {fname}: {e}")

        # Load today's daily log
        today = datetime.now().strftime("%Y-%m-%d")
        daily = workspace / f"{today}.md"
        if daily.exists():
            try:
                content = daily.read_text(encoding="utf-8")
                # Limit daily log to 1500 chars
                parts.append(f"## Daily Log ({today})\n{content[:1500]}")
            except Exception as e:
                _log(f"Failed to load daily log: {e}")

        # Join with separators, max 8000 chars total
        bootstrap = "\n\n---\n\n".join(parts)
        return bootstrap[:8000]

    # ───────────────────────────────────────────────────────────
    # Worktree management
    # ───────────────────────────────────────────────────────────

    def _create_worktree(self, job_id: str, repo_path: str = DEFAULT_REPO) -> str:
        """Create an isolated git worktree for a job. Returns worktree path."""
        wt_path = os.path.join(WORKTREE_BASE, job_id)
        if os.path.exists(wt_path):
            # Already exists, reuse it
            _log(f"Reusing existing worktree: {wt_path}")
            return wt_path

        Path(WORKTREE_BASE).mkdir(parents=True, exist_ok=True)
        branch_name = f"agent/{job_id}"

        # Create worktree with a new branch from HEAD
        result = _run(
            ["git", "-C", repo_path, "worktree", "add", "-b", branch_name, wt_path, "HEAD"],
            timeout=30,
        )
        if result.returncode != 0:
            # Branch might already exist, try without -b
            result = _run(
                ["git", "-C", repo_path, "worktree", "add", wt_path, "HEAD", "--detach"],
                timeout=30,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to create worktree: {result.stderr.strip()}")

        _log(f"Created worktree: {wt_path} (repo: {repo_path})")
        return wt_path

    def _cleanup_worktree(self, job_id: str, repo_path: str = DEFAULT_REPO):
        """Remove a worktree and its branch."""
        wt_path = os.path.join(WORKTREE_BASE, job_id)
        if os.path.exists(wt_path):
            _run(["git", "-C", repo_path, "worktree", "remove", wt_path, "--force"], timeout=15)
            _log(f"Removed worktree: {wt_path}")
        # Clean up branch
        branch_name = f"agent/{job_id}"
        _run(["git", "-C", repo_path, "branch", "-D", branch_name], timeout=10)

    # ───────────────────────────────────────────────────────────
    # Agent spawning
    # ───────────────────────────────────────────────────────────

    def spawn_agent(
        self,
        job_id: str,
        prompt: str,
        worktree_repo: Optional[str] = None,
        use_worktree: bool = False,
        cwd: Optional[str] = None,
        timeout_minutes: int = 30,
        claude_args: str = "",
    ) -> str:
        """
        Spawn a Claude Code agent in a new tmux pane.

        Args:
            job_id: Unique identifier for this agent task
            prompt: The prompt/instruction for the agent
            worktree_repo: Git repo to create worktree from (enables use_worktree)
            use_worktree: Create an isolated git worktree
            cwd: Working directory (overrides worktree)
            timeout_minutes: Kill agent after this many minutes (0=no limit)
            claude_args: Extra args for claude CLI

        Returns:
            pane_id in format "session:window.pane"
        """
        self._ensure_session()

        # Determine working directory
        work_dir = cwd
        if worktree_repo or use_worktree:
            repo = worktree_repo or DEFAULT_REPO
            work_dir = self._create_worktree(job_id, repo)
        elif not work_dir:
            work_dir = DEFAULT_REPO

        # Load and inject workspace bootstrap context
        bootstrap = self._load_workspace_bootstrap()
        if bootstrap:
            prompt = f"[WORKSPACE CONTEXT]\n{bootstrap}\n\n[USER MESSAGE]\n{prompt}"

        # Escape prompt for shell (write to file to avoid escaping nightmares)
        agent_outputs_dir = "./data/agent_outputs"
        os.makedirs(agent_outputs_dir, exist_ok=True)
        prompt_file = f"{agent_outputs_dir}/openclaw-prompt-{job_id}.txt"
        with open(prompt_file, "w") as f:
            f.write(prompt)

        # Build a shell script with continuation loop
        # When Claude hits --max-turns, it exits with code 1. Instead of
        # treating this as failure, we continue where it left off (up to
        # MAX_CONTINUATIONS times). This lets complex tasks run 150+ turns.
        script_file = f"{agent_outputs_dir}/openclaw-agent-{job_id}.sh"
        output_file = f"{agent_outputs_dir}/openclaw-output-{job_id}.txt"
        max_turns = 30  # per continuation chunk
        max_continuations = 5  # total attempts = max_turns * max_continuations = 150 turns
        with open(script_file, "w") as sf:
            sf.write("#!/usr/bin/env bash\n")
            sf.write("set -o pipefail\n")
            sf.write("unset CLAUDECODE\n")
            sf.write("unset CLAUDE_CODE_SESSION\n")
            sf.write(f"cd {work_dir}\n")
            sf.write(f'echo "[AGENT_START] $(date)" >> {LOG_FILE}\n')
            sf.write(f'echo "Agent {job_id} starting in {work_dir}..."\n')
            sf.write(f'> {output_file}\n')  # truncate output file
            # Heartbeat: background subshell writes heartbeat every 30s for watchdog
            heartbeat_dir = "./data/agent_outputs/heartbeats"
            heartbeat_file = f"{heartbeat_dir}/heartbeat-{job_id}"
            sf.write(f'mkdir -p {heartbeat_dir}\n')
            sf.write(f'( while true; do date +%s > {heartbeat_file}; sleep 30; done ) &\n')
            sf.write(f'HEARTBEAT_PID=$!\n')
            sf.write(f'trap "kill $HEARTBEAT_PID 2>/dev/null; rm -f {heartbeat_file}" EXIT\n')
            sf.write(f'PROMPT_FILE="{prompt_file}"\n')
            sf.write(f'MAX_CONTINUATIONS={max_continuations}\n')
            sf.write(f'ATTEMPT=0\n')
            sf.write(f'FINAL_EXIT=1\n')
            sf.write(f'\n')
            sf.write(f'while [ $ATTEMPT -lt $MAX_CONTINUATIONS ]; do\n')
            sf.write(f'  ATTEMPT=$((ATTEMPT + 1))\n')
            sf.write(f'  echo "[CONTINUATION $ATTEMPT/{max_continuations}] $(date)"\n')
            sf.write(f'  {CLAUDE_CMD} -p {CLAUDE_FULL_ACCESS} --max-turns {max_turns} --output-format text "$(cat $PROMPT_FILE)" {claude_args} 2>&1 | tee -a {output_file}\n')
            sf.write(f'  FINAL_EXIT=$?\n')
            sf.write(f'\n')
            sf.write(f'  # Exit code 0 = task completed successfully\n')
            sf.write(f'  if [ $FINAL_EXIT -eq 0 ]; then\n')
            sf.write(f'    echo "[AGENT_COMPLETED] Task finished on attempt $ATTEMPT"\n')
            sf.write(f'    break\n')
            sf.write(f'  fi\n')
            sf.write(f'\n')
            sf.write(f'  # Exit code 1 = hit max-turns limit, continue with progress\n')
            sf.write(f'  if [ $FINAL_EXIT -eq 1 ] && [ $ATTEMPT -lt $MAX_CONTINUATIONS ]; then\n')
            sf.write(f'    echo "[TURN_LIMIT_HIT] Continuing from where we left off..."\n')
            sf.write(f'    PROGRESS=$(tail -80 {output_file})\n')
            sf.write(f'    cat > $PROMPT_FILE << CONTINUE_EOF\n')
            sf.write(f'You were working on a task and hit the turn limit. Continue where you left off.\n')
            sf.write(f'\n')
            sf.write(f'Your recent progress:\n')
            sf.write(f'$PROGRESS\n')
            sf.write(f'\n')
            sf.write(f'Continue the task. Do NOT restart from scratch. Pick up exactly where you stopped.\n')
            sf.write(f'When fully done, output "TASK_COMPLETE" on the last line.\n')
            sf.write(f'CONTINUE_EOF\n')
            sf.write(f'  else\n')
            sf.write(f'    echo "[AGENT_FAILED] Exit code $FINAL_EXIT on attempt $ATTEMPT"\n')
            sf.write(f'    break\n')
            sf.write(f'  fi\n')
            sf.write(f'done\n')
            sf.write(f'\n')
            sf.write(f'echo ""\n')
            sf.write(f'echo "[AGENT_EXIT code=$FINAL_EXIT attempts=$ATTEMPT]"\n')
            sf.write(f'echo "[AGENT_DONE] job={job_id} exit=$FINAL_EXIT attempts=$ATTEMPT $(date)" >> {LOG_FILE}\n')
            # Keep pane open for 300s so output can be collected
            sf.write(f'echo "Agent finished. Pane closes in 5min..."\n')
            sf.write(f'sleep 300\n')
        os.chmod(script_file, 0o755)

        # Wrap with timeout if specified
        if timeout_minutes > 0:
            full_cmd = f"timeout {timeout_minutes * 60} bash {script_file}"
        else:
            full_cmd = f"bash {script_file}"

        # Create a new window in the session for this agent
        window_name = f"agent-{job_id[:20]}"
        result = _tmux(
            "new-window", "-t", self.session,
            "-n", window_name,
            "-P", "-F", "#{pane_id}",  # Print the pane ID
            full_cmd,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to spawn agent pane: {result.stderr.strip()}")

        pane_id = result.stdout.strip()

        # Set pane title to job_id for tracking
        _tmux("select-pane", "-t", pane_id, "-T", f"job:{job_id}")

        _log(f"SPAWN job={job_id} pane={pane_id} cwd={work_dir}")
        return pane_id

    def spawn_parallel(self, jobs: list[dict]) -> list[dict]:
        """
        Spawn multiple agents in parallel.

        Args:
            jobs: List of dicts with keys: job_id, prompt, and optionally
                  worktree_repo, use_worktree, cwd, timeout_minutes, claude_args

        Returns:
            List of dicts: {job_id, pane_id, status}
        """
        results = []
        for job in jobs:
            try:
                pane_id = self.spawn_agent(
                    job_id=job["job_id"],
                    prompt=job["prompt"],
                    worktree_repo=job.get("worktree_repo"),
                    use_worktree=job.get("use_worktree", False),
                    cwd=job.get("cwd"),
                    timeout_minutes=job.get("timeout_minutes", 30),
                    claude_args=job.get("claude_args", ""),
                )
                results.append({"job_id": job["job_id"], "pane_id": pane_id, "status": "spawned"})
            except Exception as e:
                _log(f"SPAWN_FAIL job={job['job_id']} error={e}")
                results.append({"job_id": job["job_id"], "pane_id": None, "status": f"error: {e}"})
        return results

    # ───────────────────────────────────────────────────────────
    # Agent monitoring
    # ───────────────────────────────────────────────────────────

    def list_agents(self) -> list[dict]:
        """List all agent panes with their status."""
        self._ensure_session()

        result = _tmux(
            "list-panes", "-t", self.session, "-a",
            "-F", "#{pane_id}|#{window_name}|#{pane_title}|#{pane_pid}|#{pane_dead}|#{pane_start_time}",
        )

        if result.returncode != 0:
            return []

        agents = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("|")
            if len(parts) < 6:
                continue

            pane_id, window_name, pane_title, pane_pid, pane_dead, start_time = parts[:6]

            # Skip the control window
            if window_name == "control":
                continue

            # Extract job_id from pane title (format: "job:xxx")
            job_id = ""
            if pane_title.startswith("job:"):
                job_id = pane_title[4:]

            # Determine status
            is_dead = pane_dead == "1"
            status = "exited" if is_dead else "running"

            # Calculate runtime
            try:
                start_ts = int(start_time)
                runtime_sec = int(time.time()) - start_ts
            except (ValueError, TypeError):
                runtime_sec = 0

            agents.append({
                "pane_id": pane_id,
                "job_id": job_id,
                "window_name": window_name,
                "pid": pane_pid,
                "status": status,
                "runtime_seconds": runtime_sec,
                "runtime_human": _format_duration(runtime_sec),
            })

        return agents

    def get_agent_status(self, pane_id: str) -> Optional[dict]:
        """Get status for a specific pane."""
        agents = self.list_agents()
        for a in agents:
            if a["pane_id"] == pane_id:
                return a
        return None

    # ───────────────────────────────────────────────────────────
    # Output collection
    # ───────────────────────────────────────────────────────────

    def collect_output(self, pane_id: str, lines: int = 5000, job_id: str = None) -> str:
        """Capture the tmux pane scrollback buffer, or read from output file."""
        result = _tmux(
            "capture-pane", "-t", pane_id, "-p",
            "-S", f"-{lines}",  # Start from N lines back
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
        # Pane gone — try the saved output file
        if job_id:
            output_file = f"./data/agent_outputs/openclaw-output-{job_id}.txt"
            if os.path.exists(output_file):
                with open(output_file, "r") as f:
                    return f.read()
        return f"Error capturing output: {result.stderr.strip()}"

    def collect_all_outputs(self) -> dict[str, str]:
        """Collect output from all agent panes. Returns {pane_id: output}."""
        outputs = {}
        for agent in self.list_agents():
            outputs[agent["pane_id"]] = self.collect_output(agent["pane_id"])
        return outputs

    # ───────────────────────────────────────────────────────────
    # Agent lifecycle
    # ───────────────────────────────────────────────────────────

    def kill_agent(self, pane_id: str) -> bool:
        """Kill a specific agent pane."""
        result = _tmux("kill-pane", "-t", pane_id)
        success = result.returncode == 0
        _log(f"KILL pane={pane_id} success={success}")
        return success

    def kill_all(self) -> int:
        """Kill all agent panes (keeps the session). Returns count killed."""
        agents = self.list_agents()
        killed = 0
        for agent in agents:
            if self.kill_agent(agent["pane_id"]):
                killed += 1
        _log(f"KILL_ALL killed={killed}")
        return killed

    def cleanup(self, job_id: str, repo_path: str = DEFAULT_REPO):
        """Full cleanup: kill agent, remove worktree, delete prompt file."""
        # Find and kill any panes for this job
        for agent in self.list_agents():
            if agent["job_id"] == job_id:
                self.kill_agent(agent["pane_id"])

        # Clean up worktree
        self._cleanup_worktree(job_id, repo_path)

        # Clean up prompt file
        prompt_file = f"./data/agent_outputs/openclaw-prompt-{job_id}.txt"
        if os.path.exists(prompt_file):
            os.remove(prompt_file)

        _log(f"CLEANUP job={job_id}")

    # ───────────────────────────────────────────────────────────
    # Ralph Loop V2 — Auto-respawn with improved prompts
    # ───────────────────────────────────────────────────────────

    def auto_respawn(
        self,
        pane_id: str,
        original_prompt: str,
        job_id: str,
        max_retries: int = 3,
        improve_prompt: bool = True,
        worktree_repo: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> dict:
        """
        Ralph Loop V2: If an agent fails, respawn with enhanced prompt.
        Appends failure context so the next attempt can learn from the error.

        Returns:
            {
                "attempts": int,
                "final_pane_id": str,
                "final_status": "success" | "max_retries_exceeded",
                "outputs": [str, ...],  # Output from each attempt
            }
        """
        attempts = 0
        outputs = []
        current_prompt = original_prompt
        current_pane = pane_id

        while attempts < max_retries:
            attempts += 1
            _log(f"RALPH_LOOP job={job_id} attempt={attempts}/{max_retries}")

            # Wait for the agent to finish (poll every 5s, max 30min)
            max_wait = 30 * 60  # 30 minutes
            waited = 0
            while waited < max_wait:
                status = self.get_agent_status(current_pane)
                if status is None or status["status"] == "exited":
                    break
                time.sleep(5)
                waited += 5

            # Collect output
            output = self.collect_output(current_pane)
            outputs.append(output)

            # Check if it succeeded (look for success markers)
            if _check_success(output):
                _log(f"RALPH_LOOP job={job_id} SUCCESS on attempt {attempts}")
                return {
                    "attempts": attempts,
                    "final_pane_id": current_pane,
                    "final_status": "success",
                    "outputs": outputs,
                }

            # Agent failed — improve the prompt and retry
            if improve_prompt and attempts < max_retries:
                # Extract the last ~100 lines of failure context
                failure_lines = output.strip().split("\n")[-100:]
                failure_context = "\n".join(failure_lines)

                current_prompt = (
                    f"{original_prompt}\n\n"
                    f"--- PREVIOUS ATTEMPT {attempts} FAILED ---\n"
                    f"The previous attempt produced this output (last 100 lines):\n"
                    f"```\n{failure_context}\n```\n"
                    f"Please analyze what went wrong and try a different approach. "
                    f"Do NOT repeat the same mistake."
                )

            # Kill old pane, spawn new one
            self.kill_agent(current_pane)

            retry_job_id = f"{job_id}-retry{attempts}"
            try:
                current_pane = self.spawn_agent(
                    job_id=retry_job_id,
                    prompt=current_prompt,
                    worktree_repo=worktree_repo,
                    cwd=cwd,
                )
            except Exception as e:
                _log(f"RALPH_LOOP job={job_id} SPAWN_FAIL on retry {attempts}: {e}")
                return {
                    "attempts": attempts,
                    "final_pane_id": current_pane,
                    "final_status": f"spawn_error: {e}",
                    "outputs": outputs,
                }

        _log(f"RALPH_LOOP job={job_id} MAX_RETRIES_EXCEEDED after {attempts} attempts")
        return {
            "attempts": attempts,
            "final_pane_id": current_pane,
            "final_status": "max_retries_exceeded",
            "outputs": outputs,
        }

    # ───────────────────────────────────────────────────────────
    # Session info
    # ───────────────────────────────────────────────────────────

    def session_exists(self) -> bool:
        """Check if the tmux session exists."""
        result = _tmux("has-session", "-t", self.session)
        return result.returncode == 0

    def destroy_session(self):
        """Destroy the entire tmux session."""
        _tmux("kill-session", "-t", self.session)
        _log(f"Destroyed tmux session: {self.session}")


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _format_duration(seconds: int) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    else:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h {m}m"


def _check_success(output: str) -> bool:
    """
    Heuristic check if agent output indicates success.
    Looks for common success/failure patterns including continuation loop markers.
    """
    output_lower = output.lower()

    # New continuation loop markers (preferred — generated by the while loop)
    if "[agent_completed]" in output_lower:
        return True
    if "[agent_failed]" in output_lower:
        return False

    # New exit marker format: [AGENT_EXIT code=X attempts=Y]
    import re
    exit_match = re.search(r'\[agent_exit code=(\d+)', output_lower)
    if exit_match:
        return exit_match.group(1) == "0"

    # Legacy exit code marker (pre-continuation loop)
    if "[agent_exit code=0]" in output_lower:
        return True
    if "[agent_exit code=" in output_lower:
        return False

    # Failure indicators
    failure_signals = [
        "error:", "traceback", "fatal:", "panic:",
        "command not found", "permission denied",
        "failed to", "could not", "unable to",
    ]
    # Count failure signals in last 20 lines
    last_lines = "\n".join(output.strip().split("\n")[-20:]).lower()
    failure_count = sum(1 for sig in failure_signals if sig in last_lines)

    # If more than 2 failure signals in the tail, consider it failed
    if failure_count >= 2:
        return False

    # Default: assume success if the process exited without obvious errors
    return True


# ═══════════════════════════════════════════════════════════════
# Module-level convenience (singleton)
# ═══════════════════════════════════════════════════════════════

_spawner: Optional[TmuxSpawner] = None


def get_spawner() -> TmuxSpawner:
    """Get or create the global TmuxSpawner instance."""
    global _spawner
    if _spawner is None:
        _spawner = TmuxSpawner()
    return _spawner
