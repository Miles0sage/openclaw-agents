"""
Claude Code Headless — Spawn Claude Code CLI for complex tasks.

Runs Claude Code CLI in headless mode with --print --output-format json.
Returns structured results suitable for integration with OpenClaw pipeline.
Only available to overseer agent (expensive — uses Opus).
"""

import subprocess
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger("claude_headless")

# Claude Code CLI path
CLAUDE_CLI = "/root/.local/bin/claude"

# Maximum output size (50KB JSON)
MAX_OUTPUT_SIZE = 50000

# Tool access flags for headless mode
CLAUDE_HEADLESS_TOOLS = [
    "Bash(*)", "Read(*)", "Write(*)", "Edit(*)",
    "Glob(*)", "Grep(*)", "WebSearch(*)", "WebFetch(*)",
]


class ClaudeHeadless:
    """Run Claude Code CLI in headless mode for automated tasks."""

    def __init__(self, max_retries: int = 1, timeout_seconds: int = 300):
        """
        Initialize Claude Headless runner.

        Args:
            max_retries: Number of retries on failure (default 1 = no retries)
            timeout_seconds: Maximum execution time per task (default 300 = 5 min)
        """
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds

    async def run(
        self,
        prompt: str,
        cwd: str = ".",
        timeout: Optional[int] = None,
        model: Optional[str] = None,
        max_turns: int = 10,
    ) -> Dict[str, Any]:
        """
        Execute a prompt via Claude Code headless mode.

        Args:
            prompt: The instruction for Claude Code
            cwd: Working directory (default .)
            timeout: Override default timeout (in seconds)
            model: Override default model (e.g., "opus", "sonnet")
            max_turns: Maximum turns before exit (default 10)

        Returns:
            Dict with keys:
                - success (bool): Whether task completed
                - output (str): Claude's response
                - error (str): Error message if failed
                - model (str): Model used
                - cost_estimate (str): Rough cost estimate
                - duration_seconds (float): Execution time
        """
        start_time = datetime.now()
        timeout_val = timeout or self.timeout_seconds

        try:
            # Validate Claude CLI exists
            if not os.path.exists(CLAUDE_CLI):
                return {
                    "success": False,
                    "output": "",
                    "error": f"Claude CLI not found at {CLAUDE_CLI}",
                    "model": model or "unknown",
                    "cost_estimate": "$0",
                    "duration_seconds": (datetime.now() - start_time).total_seconds(),
                }

            # Build command
            cmd = [CLAUDE_CLI, "--print", "--output-format", "json", "--max-turns", str(max_turns)]

            # Add model if specified
            if model:
                cmd.extend(["--model", model])

            # Add tool access
            for tool in CLAUDE_HEADLESS_TOOLS:
                cmd.extend(["--allowedTools", tool])

            # Add prompt
            cmd.append(prompt)

            # Run in target directory
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_val,
                env={**os.environ, "CLAUDECODE": ""},  # Unset nested session flag
            )

            # Parse output
            output = result.stdout
            if result.returncode != 0:
                return {
                    "success": False,
                    "output": output[:MAX_OUTPUT_SIZE],
                    "error": result.stderr[:1000],
                    "model": model or "opus",
                    "cost_estimate": "$0.01",
                    "duration_seconds": (datetime.now() - start_time).total_seconds(),
                }

            # Parse JSON if available
            try:
                parsed = json.loads(output)
                return {
                    "success": True,
                    "output": parsed.get("content", output[:MAX_OUTPUT_SIZE]),
                    "error": None,
                    "model": model or "opus",
                    "cost_estimate": self._estimate_cost(output, model),
                    "duration_seconds": (datetime.now() - start_time).total_seconds(),
                }
            except json.JSONDecodeError:
                # Output wasn't JSON, return as-is
                return {
                    "success": True,
                    "output": output[:MAX_OUTPUT_SIZE],
                    "error": None,
                    "model": model or "opus",
                    "cost_estimate": self._estimate_cost(output, model),
                    "duration_seconds": (datetime.now() - start_time).total_seconds(),
                }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "output": "",
                "error": f"Timeout after {timeout_val} seconds",
                "model": model or "opus",
                "cost_estimate": f"${timeout_val * 0.0001:.2f}",
                "duration_seconds": (datetime.now() - start_time).total_seconds(),
            }
        except Exception as e:
            return {
                "success": False,
                "output": "",
                "error": str(e),
                "model": model or "opus",
                "cost_estimate": "$0",
                "duration_seconds": (datetime.now() - start_time).total_seconds(),
            }

    async def review_pr(self, repo_path: str, branch: str, pr_number: Optional[int] = None) -> Dict[str, Any]:
        """
        Auto-review a PR using Claude Code.

        Args:
            repo_path: Path to the repository
            branch: Branch to review
            pr_number: Optional PR number for context

        Returns:
            Dict with review results and recommendations
        """
        prompt = f"""
Review the code changes on branch '{branch}' in {repo_path}.

Provide a structured code review with:
1. Summary of changes
2. Logic correctness assessment
3. Edge cases that might break
4. Security considerations
5. Performance implications
6. Specific recommendations for improvement

Be thorough. Find real issues, not just style nitpicks.
"""
        return await self.run(prompt, cwd=repo_path, model="opus", max_turns=15)

    async def fix_test(self, test_file: str, error: str, project_path: str = ".") -> Dict[str, Any]:
        """
        Auto-fix a failing test.

        Args:
            test_file: Path to the failing test file
            error: Error message from test failure
            project_path: Root project path

        Returns:
            Dict with fix results
        """
        prompt = f"""
Fix the failing test at {test_file}.

Test failure:
{error}

Read the test file, understand what it's testing, and fix the implementation
(or the test if the test itself is wrong). Run the test to verify the fix works.

Report:
1. Root cause of the failure
2. Changes made
3. Verification that test now passes
"""
        return await self.run(prompt, cwd=project_path, model="opus", max_turns=12)

    async def build_feature(self, spec: str, project_path: str, output_file: Optional[str] = None) -> Dict[str, Any]:
        """
        Build a feature from spec using Claude Code.

        Args:
            spec: Feature specification (what to build)
            project_path: Root project path
            output_file: Optional file to write the spec into for context

        Returns:
            Dict with build results
        """
        prompt = f"""
Implement the following feature in {project_path}:

{spec}

Approach:
1. Read relevant source files to understand the architecture
2. Plan the implementation
3. Write the code
4. Test it
5. Commit with a clear message

Report when done with:
- Files modified
- Key implementation details
- Testing done
- Git commit hash
"""
        return await self.run(prompt, cwd=project_path, model="opus", max_turns=20)

    async def debug_issue(self, issue_description: str, project_path: str, log_file: Optional[str] = None) -> Dict[str, Any]:
        """
        Debug an issue using Claude Code.

        Args:
            issue_description: Description of the problem
            project_path: Root project path
            log_file: Optional path to error logs

        Returns:
            Dict with debug findings and proposed fixes
        """
        prompt = f"""
Debug the following issue in {project_path}:

{issue_description}

Investigation steps:
1. Reproduce the issue (read error logs, check logs)
2. Identify root cause
3. Propose a fix
4. Test the fix
5. Commit if fix is verified

Be systematic. Find the real problem, not just a symptom.
"""
        if log_file and os.path.exists(log_file):
            with open(log_file, "r") as f:
                logs = f.read()[:5000]
                prompt += f"\n\nRecent logs:\n{logs}"

        return await self.run(prompt, cwd=project_path, model="opus", max_turns=15)

    async def audit_code(self, target_path: str, focus: str = "security") -> Dict[str, Any]:
        """
        Audit code for security, performance, or maintainability.

        Args:
            target_path: File or directory to audit
            focus: "security", "performance", or "maintainability"

        Returns:
            Dict with audit findings
        """
        focus_prompt = {
            "security": "Look for vulnerabilities, data leaks, auth bypasses, injection risks, XSS, SQL injection, etc.",
            "performance": "Look for N+1 queries, memory leaks, inefficient algorithms, unnecessary work, blocking operations.",
            "maintainability": "Look for code complexity, unclear logic, missing tests, inconsistent patterns, technical debt.",
        }

        prompt = f"""
Audit {target_path} for {focus}.

{focus_prompt.get(focus, 'Look for issues.')}

Report findings as:
1. Critical issues (must fix before production)
2. Important issues (should fix soon)
3. Nice-to-have improvements

For each issue: specific location, impact, and remediation.
"""
        project_path = Path(target_path).parent
        return await self.run(prompt, cwd=str(project_path), model="opus", max_turns=12)

    def _estimate_cost(self, output: str, model: Optional[str] = None) -> str:
        """Rough cost estimate for Claude Opus."""
        # Rough estimate: ~0.003 per 1000 tokens
        # Assume ~1 token per 4 chars
        tokens = len(output) // 4
        # Opus: $15 per 1M input, $75 per 1M output
        # Assume 3:1 input:output ratio
        output_tokens = tokens
        input_tokens = tokens * 3
        cost = (input_tokens * 15 + output_tokens * 75) / 1_000_000
        return f"${cost:.2f}"


# Module-level convenience function
_headless: Optional[ClaudeHeadless] = None


def get_headless() -> ClaudeHeadless:
    """Get or create the global ClaudeHeadless instance."""
    global _headless
    if _headless is None:
        _headless = ClaudeHeadless()
    return _headless
