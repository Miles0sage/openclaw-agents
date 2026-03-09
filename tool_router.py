"""
Tool Router — Phase-gated tool dispatch with audit logging.
=============================================================
Central dispatcher that enforces which tools are available in each phase
of the pipeline (RESEARCH, PLAN, EXECUTE, VERIFY, DELIVER). Prevents
agents from using dangerous tools (shell_execute, file_write) during
read-only phases.

Patterns: Composio (dynamic tool routing), LangGraph (conditional tool gating)
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from agent_tools import execute_tool as _raw_execute_tool, AGENT_TOOLS

logger = logging.getLogger("tool_router")

# Audit log path
AUDIT_LOG_DIR = os.path.join(
    os.environ.get("OPENCLAW_DATA_DIR", "/root/openclaw/data"),
    "audit",
)
AUDIT_LOG_PATH = os.path.join(AUDIT_LOG_DIR, "tool_calls.jsonl")

# ---------------------------------------------------------------------------
# Phase → tool availability mapping (source of truth)
# ---------------------------------------------------------------------------
# These mirror the whitelists in autonomous_runner.py but are the canonical
# definition going forward. The runner imports from here.

PHASE_TOOLS = {
    "research": [
        "research_task", "web_search", "web_fetch", "web_scrape",
        "file_read", "glob_files", "grep_search",
        "github_repo_info",
    ],
    "plan": [
        "file_read", "glob_files", "grep_search",
        "github_repo_info",
    ],
    "execute": [
        "shell_execute", "git_operations", "file_read", "file_write", "file_edit",
        "glob_files", "grep_search", "install_package",
        "vercel_deploy", "process_manage", "env_manage", "propose_tool",
    ],
    "verify": [
        "shell_execute", "file_read", "glob_files", "grep_search",
        "github_repo_info",
    ],
    "deliver": [
        "git_operations", "vercel_deploy", "shell_execute",
        "send_slack_message",
    ],
}

# Tool risk levels
TOOL_RISK_LEVELS = {
    # Safe — read-only, no side effects
    "github_repo_info": "safe",
    "web_search": "safe",
    "web_fetch": "safe",
    "web_scrape": "safe",
    "file_read": "safe",
    "glob_files": "safe",
    "grep_search": "safe",
    "research_task": "safe",
    "get_cost_summary": "safe",
    "list_jobs": "safe",
    "agency_status": "safe",
    "get_events": "safe",
    "search_memory": "safe",
    "compute_sort": "safe",
    "compute_stats": "safe",
    "compute_math": "safe",
    "compute_search": "safe",
    "compute_matrix": "safe",
    "compute_prime": "safe",
    "compute_hash": "safe",
    "compute_convert": "safe",

    # Medium — creates/modifies state but within sandbox
    "file_write": "medium",
    "file_edit": "medium",
    "install_package": "medium",
    "env_manage": "medium",
    "save_memory": "medium",
    "rebuild_semantic_index": "medium",
    "flush_memory_before_compaction": "medium",
    "create_job": "medium",
    "create_proposal": "medium",
    "manage_reactions": "medium",
    "github_create_issue": "medium",

    # High — executes arbitrary commands, deploys, sends messages
    "shell_execute": "high",
    "git_operations": "high",
    "vercel_deploy": "high",
    "send_slack_message": "high",
    "kill_job": "high",
    "approve_job": "high",
    "process_manage": "high",
    "tmux_agents": "high",
    "security_scan": "high",
}


class ToolRegistry:
    """
    Singleton registry for phase-gated tool dispatch.

    Loads tool definitions from AGENT_TOOLS at startup, enriches them
    with availability and risk_level metadata, and provides centralized
    execute + audit functionality.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._tools = {}
        self._load_tools()
        self._ensure_audit_dir()

    def _load_tools(self):
        """Load and index all tool definitions from AGENT_TOOLS + dynamic tools."""
        # Load static tools
        for tool_def in AGENT_TOOLS:
            name = tool_def["name"]
            self._tools[name] = {
                **tool_def,
                "risk_level": TOOL_RISK_LEVELS.get(name, "medium"),
                "availability": self._compute_availability(name),
            }

        # Load approved dynamic tools from tool_factory
        try:
            from tool_factory import get_factory
            factory = get_factory()
            dynamic_tools = factory.list_dynamic_tools(approved_only=True)
            for dyn_tool in dynamic_tools:
                # Convert DynamicTool to tool definition format
                tool_def = {
                    "name": dyn_tool.name,
                    "description": dyn_tool.description,
                    "input_schema": dyn_tool.input_schema,
                    "dynamic": True,
                    "risk_level": "medium",  # Dynamic tools default to medium risk
                    "availability": {"research": False, "plan": False, "execute": True, "verify": False, "deliver": False},
                }
                self._tools[dyn_tool.name] = tool_def
        except Exception as e:
            logger.warning(f"Could not load dynamic tools: {e}")

        logger.info(f"ToolRegistry loaded {len(self._tools)} tools")

    def _compute_availability(self, tool_name: str) -> dict:
        """Compute which phases a tool is available in."""
        return {
            phase: tool_name in tools
            for phase, tools in PHASE_TOOLS.items()
        }

    def _ensure_audit_dir(self):
        """Create audit log directory if needed."""
        os.makedirs(AUDIT_LOG_DIR, exist_ok=True)

    def get_tool(self, name: str) -> Optional[dict]:
        """Get a tool definition by name."""
        return self._tools.get(name)

    def get_tools_for_phase(self, phase: str) -> list[dict]:
        """
        Return tool definitions available for the given phase.

        Only returns tools that are whitelisted for this phase,
        preventing agents from accessing dangerous tools during
        read-only phases.
        """
        allowed_names = set(PHASE_TOOLS.get(phase, []))
        return [
            tool_def for name, tool_def in self._tools.items()
            if name in allowed_names
        ]

    def get_tool_names_for_phase(self, phase: str) -> list[str]:
        """Return just the tool names available for a phase."""
        return list(PHASE_TOOLS.get(phase, []))

    def is_tool_allowed(self, tool_name: str, phase: str) -> bool:
        """Check if a tool is allowed in the given phase."""
        return tool_name in PHASE_TOOLS.get(phase, [])

    def get_risk_level(self, tool_name: str) -> str:
        """Get the risk level of a tool."""
        tool = self._tools.get(tool_name)
        if tool:
            return tool.get("risk_level", "medium")
        return "medium"

    def execute_tool(
        self,
        tool_name: str,
        tool_input: dict,
        phase: str = "",
        job_id: str = "",
        enforce_phase: bool = True,
    ) -> str:
        """
        Execute a tool with phase gating and audit logging.

        Args:
            tool_name: Name of the tool to execute
            tool_input: Input parameters for the tool
            phase: Current pipeline phase (required if enforce_phase=True)
            job_id: Job ID for audit trail
            enforce_phase: If True, reject tools not allowed in current phase

        Returns:
            Tool execution result as string

        Raises:
            PhaseViolationError: If tool is not allowed in the current phase
        """
        # Phase enforcement
        if enforce_phase and phase:
            if not self.is_tool_allowed(tool_name, phase):
                error_msg = (
                    f"Tool '{tool_name}' is not allowed in phase '{phase}'. "
                    f"Allowed tools: {', '.join(self.get_tool_names_for_phase(phase))}"
                )
                logger.warning(f"Phase violation: {error_msg} (job={job_id})")

                # Audit the rejection
                self.audit_tool_call(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_output=error_msg,
                    job_id=job_id,
                    phase=phase,
                    status="rejected",
                )

                raise PhaseViolationError(error_msg)

        # Execute the tool (static or dynamic)
        start_time = time.time()
        try:
            tool_def = self.get_tool(tool_name)
            if tool_def and tool_def.get("dynamic"):
                # Execute dynamic tool via tool_factory
                try:
                    from tool_factory import get_factory
                    factory = get_factory()
                    result = factory.execute_dynamic_tool(tool_name, tool_input)
                except Exception as e:
                    result = f"Dynamic tool execution failed: {e}"
                    raise
            else:
                # Execute static tool via standard handler
                result = _raw_execute_tool(tool_name, tool_input)
            elapsed = time.time() - start_time
            status = "success"
        except Exception as e:
            elapsed = time.time() - start_time
            result = f"Error: {e}"
            status = "error"
            logger.error(f"Tool {tool_name} failed: {e} (job={job_id})")

        # Audit the call
        self.audit_tool_call(
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=result,
            job_id=job_id,
            phase=phase,
            status=status,
            elapsed_s=elapsed,
        )

        if status == "error":
            raise ToolExecutionError(result)

        return result

    def audit_tool_call(
        self,
        tool_name: str,
        tool_input: dict,
        tool_output: str,
        job_id: str = "",
        phase: str = "",
        status: str = "success",
        elapsed_s: float = 0.0,
    ):
        """
        Write an audit log entry for a tool call.

        Logs to JSONL at data/audit/tool_calls.jsonl for compliance
        and debugging.
        """
        entry = {
            "timestamp": time.time(),
            "iso_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "job_id": job_id,
            "phase": phase,
            "tool": tool_name,
            "risk_level": self.get_risk_level(tool_name),
            "status": status,
            "elapsed_s": round(elapsed_s, 3),
            "input_summary": _summarize_input(tool_input),
            "output_length": len(str(tool_output)),
        }

        try:
            with open(AUDIT_LOG_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write audit log: {e}")

    def list_tools(self) -> list[dict]:
        """List all registered tools with their metadata."""
        return [
            {
                "name": name,
                "risk_level": tool["risk_level"],
                "availability": tool["availability"],
            }
            for name, tool in self._tools.items()
        ]

    def reload(self):
        """Reload tool definitions (for dynamic updates)."""
        self._tools.clear()
        self._load_tools()


def _summarize_input(tool_input: dict, max_len: int = 200) -> dict:
    """Summarize tool input for audit log (truncate long values)."""
    summary = {}
    for k, v in tool_input.items():
        v_str = str(v)
        summary[k] = v_str[:max_len] if len(v_str) > max_len else v_str
    return summary


# Convenience function — get the singleton registry
def get_registry() -> ToolRegistry:
    """Get or create the singleton ToolRegistry."""
    return ToolRegistry()


class PhaseViolationError(Exception):
    """Raised when a tool is called outside its allowed phase."""
    pass


class ToolExecutionError(Exception):
    """Raised when a tool execution fails."""
    pass
