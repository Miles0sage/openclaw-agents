"""
Tool-call schema validation for OpenClaw.

Validates tool name and argument schema BEFORE execution.
Rejects invalid calls with clear error messages — no execution happens.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger("openclaw.tool_validator")

TOOL_SCHEMAS: dict[str, dict] = {
    "file_read": {
        "required": ["path"],
        "types": {"path": str, "offset": int, "limit": int},
    },
    "file_write": {
        "required": ["path", "content"],
        "types": {"path": str, "content": str},
    },
    "file_edit": {
        "required": ["path", "old_string", "new_string"],
        "types": {"path": str, "old_string": str, "new_string": str},
    },
    "glob_files": {
        "required": ["pattern"],
        "types": {"pattern": str, "path": str},
    },
    "grep_search": {
        "required": ["pattern"],
        "types": {"pattern": str, "path": str, "include": str},
    },
    "shell_execute": {
        "required": ["command"],
        "types": {"command": str, "timeout": (int, float), "cwd": str},
    },
    "research_task": {
        "required": ["query"],
        "types": {"query": str, "depth": str},
    },
    "web_search": {
        "required": ["query"],
        "types": {"query": str, "max_results": int},
    },
    "git_status": {
        "required": [],
        "types": {"path": str},
    },
    "git_diff": {
        "required": [],
        "types": {"path": str, "staged": bool},
    },
    "git_commit": {
        "required": ["message"],
        "types": {"message": str, "files": list},
    },
    "git_log": {
        "required": [],
        "types": {"limit": int, "path": str},
    },
    "github_create_pr": {
        "required": ["title", "body", "branch"],
        "types": {"title": str, "body": str, "branch": str, "base": str},
    },
    "github_repo_info": {
        "required": [],
        "types": {"repo": str},
    },
}

DANGEROUS_SHELL_PATTERNS = [
    "rm -rf /", "rm -rf ~", "DROP TABLE", "DELETE FROM",
    "> /dev/sda", "mkfs", "dd if=",
]


class ToolValidationError(Exception):
    def __init__(self, tool_name: str, reason: str):
        self.tool_name = tool_name
        self.reason = reason
        super().__init__(f"Tool validation failed for '{tool_name}': {reason}")


class ToolValidator:
    def __init__(self, schemas: Optional[dict] = None):
        self._schemas = dict(TOOL_SCHEMAS)
        if schemas:
            self._schemas.update(schemas)
        self._stats = {"total": 0, "passed": 0, "failed": 0, "blocked_dangerous": 0}

    def register_schema(self, tool_name: str, required: list[str] = None,
                        types: dict[str, type] = None):
        self._schemas[tool_name] = {
            "required": required or [],
            "types": types or {},
        }

    def validate(self, tool_name: str, tool_args: dict[str, Any],
                 agent_allowlist: Optional[list[str]] = None) -> Optional[str]:
        """Returns None if valid, error string if invalid."""
        self._stats["total"] += 1

        if not tool_name or not isinstance(tool_name, str):
            self._stats["failed"] += 1
            return "Tool name must be a non-empty string"

        if not isinstance(tool_args, dict):
            self._stats["failed"] += 1
            return f"Tool args must be a dict, got {type(tool_args).__name__}"

        if agent_allowlist is not None and tool_name not in agent_allowlist:
            self._stats["failed"] += 1
            allowed = ', '.join(sorted(agent_allowlist)[:10])
            return f"Tool '{tool_name}' not in allowlist. Allowed: {allowed}"

        schema = self._schemas.get(tool_name)
        if schema:
            missing = [a for a in schema.get("required", []) if a not in tool_args]
            if missing:
                self._stats["failed"] += 1
                return f"Missing required arguments: {', '.join(missing)}"

            for arg_name, expected_type in schema.get("types", {}).items():
                if arg_name in tool_args:
                    value = tool_args[arg_name]
                    if not isinstance(value, expected_type):
                        self._stats["failed"] += 1
                        tname = expected_type.__name__ if isinstance(expected_type, type) else str(expected_type)
                        return f"Argument '{arg_name}': expected {tname}, got {type(value).__name__}"

        if tool_name == "shell_execute":
            cmd = tool_args.get("command", "")
            for pattern in DANGEROUS_SHELL_PATTERNS:
                if pattern in cmd:
                    self._stats["failed"] += 1
                    self._stats["blocked_dangerous"] += 1
                    return f"Blocked dangerous command pattern: '{pattern}'"

        self._stats["passed"] += 1
        return None

    def get_stats(self) -> dict:
        return dict(self._stats)


_validator: Optional[ToolValidator] = None

def init_tool_validator(**kwargs) -> ToolValidator:
    global _validator
    _validator = ToolValidator(**kwargs)
    return _validator

def get_tool_validator() -> ToolValidator:
    global _validator
    if _validator is None:
        _validator = ToolValidator()
    return _validator
