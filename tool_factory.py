"""
Dynamic Tool Factory — Runtime tool creation and registration for OpenClaw agents.

Allows agents to propose, test, approve, and execute new tools at runtime.
Tools are persisted in SQLite and include safety constraints (no rm, no dangerous
python, restricted HTTP, max 50 tools total).

Patterns: Composio (dynamic tool composition), OpenHands (tool registry),
Agent SDK (dynamic capability extension).
"""

import json
import logging
import os
import re
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
import hashlib

import httpx

logger = logging.getLogger("tool_factory")

# ═══════════════════════════════════════════════════════════════
# CONSTRAINTS & CONFIGURATION
# ═══════════════════════════════════════════════════════════════

# Destructive shell commands that are NEVER allowed
BLOCKED_SHELL_PATTERNS = [
    r"^rm\s+-rf",
    r"^rm\s+-f",
    r"^rm\s+/",
    r"^dd\s+",
    r"^mkfs",
    r"^shutdown",
    r"^reboot",
    r"^halt",
    r"^poweroff",
    r":\(\)\s*{\s*:\|:",  # fork bomb
]

# Python imports that are forbidden in snippets
FORBIDDEN_PYTHON_IMPORTS = {
    "os", "subprocess", "sys", "shutil", "threading", "multiprocessing",
    "socket", "ssl", "urllib", "requests", "popen",
}

# Internal IP ranges to block in HTTP requests
INTERNAL_IP_PATTERNS = [
    r"^127\.",
    r"^localhost",
    r"^192\.168\.",
    r"^10\.",
    r"^172\.1[6-9]\.",
    r"^172\.2[0-9]\.",
    r"^172\.3[0-1]\.",
    r"^169\.254\.",
    r"^::1",  # IPv6 loopback
    r"^fe80:",  # IPv6 link-local
]

MAX_DYNAMIC_TOOLS = 50
TOOL_TIMEOUT = 30
HTTP_TIMEOUT = 10

# Database path
DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "os.environ.get("OPENCLAW_DATA_DIR", "./data")")
DB_PATH = os.path.join(DATA_DIR, "dynamic_tools.db")


# ═══════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════

@dataclass
class DynamicTool:
    """Tool proposed and created by agents at runtime."""
    name: str
    description: str
    input_schema: Dict[str, Any]  # JSON Schema object
    implementation_type: str  # "shell_command", "http_request", "python_snippet"
    implementation: str  # The actual code/command/URL
    created_by: str  # Agent key (e.g., "coder_agent")
    created_at: str  # ISO8601 timestamp
    approved: bool = False
    test_passed: bool = False
    test_error: Optional[str] = None
    approval_notes: Optional[str] = None


class ToolFactoryError(Exception):
    """Base exception for tool factory errors."""
    pass


class ToolConflictError(ToolFactoryError):
    """Tool name conflicts with existing static tool."""
    pass


class ToolSafetyError(ToolFactoryError):
    """Tool violates safety constraints."""
    pass


class ToolTestError(ToolFactoryError):
    """Tool test failed during validation."""
    pass


# ═══════════════════════════════════════════════════════════════
# TOOL FACTORY
# ═══════════════════════════════════════════════════════════════

class ToolFactory:
    """Factory for proposing, testing, and executing dynamic tools."""

    def __init__(self, db_path: str = DB_PATH):
        """Initialize factory with database."""
        self.db_path = db_path
        self._ensure_db_exists()

    def _ensure_db_exists(self):
        """Create database and tables if they don't exist."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dynamic_tools (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL,
                input_schema TEXT NOT NULL,  -- JSON
                implementation_type TEXT NOT NULL,
                implementation TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                approved INTEGER NOT NULL DEFAULT 0,
                test_passed INTEGER NOT NULL DEFAULT 0,
                test_error TEXT,
                approval_notes TEXT,
                retired INTEGER NOT NULL DEFAULT 0,
                retired_at TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tools_name ON dynamic_tools(name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tools_approved ON dynamic_tools(approved)")
        conn.commit()
        conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _is_static_tool(self, tool_name: str) -> bool:
        """Check if tool exists in static tools."""
        # Import here to avoid circular dependency
        try:
            from agent_tools import AGENT_TOOLS
            return any(t["name"] == tool_name for t in AGENT_TOOLS)
        except ImportError:
            return False

    def _validate_shell_command(self, command: str):
        """Validate shell command for safety."""
        # Check against blocked patterns
        for pattern in BLOCKED_SHELL_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                raise ToolSafetyError(f"Command contains blocked pattern: {pattern}")

        # Warn on suspicious patterns (but allow)
        if any(
            x in command.lower()
            for x in ["eval", "exec", "system", "passthru", "shell_exec"]
        ):
            logger.warning(f"Command contains dangerous function: {command[:100]}")

    def _validate_python_snippet(self, code: str):
        """Validate Python snippet for safety."""
        # Check for forbidden imports
        import_pattern = r"^\s*(?:from|import)\s+(\w+)"
        for match in re.finditer(import_pattern, code, re.MULTILINE):
            module = match.group(1)
            if module in FORBIDDEN_PYTHON_IMPORTS:
                raise ToolSafetyError(
                    f"Python snippet cannot import forbidden module: {module}"
                )

        # Check for dangerous function calls
        dangerous_calls = ["exec", "eval", "compile", "open", "subprocess"]
        for call in dangerous_calls:
            if re.search(rf"\b{call}\s*\(", code):
                raise ToolSafetyError(f"Python snippet cannot use: {call}()")

    def _validate_http_request(self, url: str):
        """Validate HTTP request for safety."""
        # Check for internal IPs
        hostname = url.split("://")[-1].split("/")[0].split(":")[0]
        for pattern in INTERNAL_IP_PATTERNS:
            if re.search(pattern, hostname, re.IGNORECASE):
                raise ToolSafetyError(f"HTTP request to internal IP blocked: {hostname}")

    def propose_tool(self, agent_key: str, tool_def: Dict[str, Any]) -> DynamicTool:
        """
        Propose a new dynamic tool.

        Args:
            agent_key: ID of agent proposing the tool
            tool_def: {
                "name": str,
                "description": str,
                "input_schema": {...},  # JSON Schema
                "implementation_type": str,
                "implementation": str
            }

        Returns:
            DynamicTool object (not yet approved)

        Raises:
            ToolConflictError: Tool name conflicts with static tool
            ToolSafetyError: Tool violates safety constraints
        """
        name = tool_def["name"]

        # Check name conflict
        if self._is_static_tool(name):
            raise ToolConflictError(f"Tool '{name}' conflicts with static tool")

        # Check if already exists
        conn = self._get_conn()
        existing = conn.execute(
            "SELECT * FROM dynamic_tools WHERE name = ? AND retired = 0",
            (name,)
        ).fetchone()
        conn.close()

        if existing:
            raise ToolConflictError(f"Tool '{name}' already exists")

        # Check limit
        conn = self._get_conn()
        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM dynamic_tools WHERE retired = 0"
        ).fetchone()
        conn.close()

        if count["cnt"] >= MAX_DYNAMIC_TOOLS:
            raise ToolFactoryError(
                f"Cannot create more than {MAX_DYNAMIC_TOOLS} dynamic tools"
            )

        # Validate based on implementation type
        impl_type = tool_def["implementation_type"]
        if impl_type == "shell_command":
            self._validate_shell_command(tool_def["implementation"])
        elif impl_type == "python_snippet":
            self._validate_python_snippet(tool_def["implementation"])
        elif impl_type == "http_request":
            self._validate_http_request(tool_def["implementation"])
        else:
            raise ToolFactoryError(
                f"Unknown implementation_type: {impl_type}. "
                "Must be: shell_command, http_request, python_snippet"
            )

        # Validate input_schema is valid JSON
        try:
            if isinstance(tool_def["input_schema"], str):
                json.loads(tool_def["input_schema"])
            else:
                json.dumps(tool_def["input_schema"])
        except (json.JSONDecodeError, TypeError) as e:
            raise ToolFactoryError(f"Invalid input_schema JSON: {e}")

        # Create tool object
        tool = DynamicTool(
            name=name,
            description=tool_def["description"],
            input_schema=tool_def["input_schema"],
            implementation_type=impl_type,
            implementation=tool_def["implementation"],
            created_by=agent_key,
            created_at=datetime.now(timezone.utc).isoformat(),
            approved=False,
            test_passed=False,
        )

        # Store in database
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO dynamic_tools
            (name, description, input_schema, implementation_type, implementation,
             created_by, created_at, approved, test_passed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tool.name,
                tool.description,
                json.dumps(tool.input_schema),
                tool.implementation_type,
                tool.implementation,
                tool.created_by,
                tool.created_at,
                0,
                0,
            ),
        )
        conn.commit()
        conn.close()

        logger.info(f"Tool '{name}' proposed by {agent_key}")
        return tool

    def test_tool(self, tool_name: str, test_input: Optional[Dict[str, Any]] = None) -> bool:
        """
        Test a proposed tool with sample input.

        Args:
            tool_name: Name of tool to test
            test_input: Sample input to pass to tool (optional, uses empty dict if None)

        Returns:
            True if test passed

        Raises:
            ToolTestError: Test failed
            ToolFactoryError: Tool not found
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM dynamic_tools WHERE name = ? AND retired = 0",
            (tool_name,)
        ).fetchone()
        conn.close()

        if not row:
            raise ToolFactoryError(f"Tool '{tool_name}' not found")

        tool = DynamicTool(
            name=row["name"],
            description=row["description"],
            input_schema=json.loads(row["input_schema"]),
            implementation_type=row["implementation_type"],
            implementation=row["implementation"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            approved=bool(row["approved"]),
            test_passed=bool(row["test_passed"]),
            test_error=row["test_error"],
            approval_notes=row["approval_notes"],
        )

        test_input = test_input or {}

        try:
            result = self._execute_tool_impl(tool, test_input)
            logger.info(f"Tool '{tool_name}' test passed")

            # Mark as test_passed
            conn = self._get_conn()
            conn.execute(
                "UPDATE dynamic_tools SET test_passed = 1, test_error = NULL WHERE name = ?",
                (tool_name,),
            )
            conn.commit()
            conn.close()

            return True
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Tool '{tool_name}' test failed: {error_msg}")

            # Store error
            conn = self._get_conn()
            conn.execute(
                "UPDATE dynamic_tools SET test_passed = 0, test_error = ? WHERE name = ?",
                (error_msg, tool_name),
            )
            conn.commit()
            conn.close()

            raise ToolTestError(f"Tool test failed: {error_msg}") from e

    def approve_tool(self, tool_name: str, approval_notes: str = "") -> DynamicTool:
        """
        Approve a tool (requires test_passed=True).

        Args:
            tool_name: Name of tool to approve
            approval_notes: Optional notes about approval

        Returns:
            Approved DynamicTool

        Raises:
            ToolFactoryError: Tool not found or test not passed
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM dynamic_tools WHERE name = ? AND retired = 0",
            (tool_name,)
        ).fetchone()

        if not row:
            conn.close()
            raise ToolFactoryError(f"Tool '{tool_name}' not found")

        if not row["test_passed"]:
            conn.close()
            raise ToolFactoryError(
                f"Tool '{tool_name}' cannot be approved until test_passed = True"
            )

        conn.execute(
            "UPDATE dynamic_tools SET approved = 1, approval_notes = ? WHERE name = ?",
            (approval_notes or "", tool_name),
        )
        conn.commit()

        # Fetch updated row
        updated = conn.execute(
            "SELECT * FROM dynamic_tools WHERE name = ?",
            (tool_name,)
        ).fetchone()
        conn.close()

        tool = DynamicTool(
            name=updated["name"],
            description=updated["description"],
            input_schema=json.loads(updated["input_schema"]),
            implementation_type=updated["implementation_type"],
            implementation=updated["implementation"],
            created_by=updated["created_by"],
            created_at=updated["created_at"],
            approved=bool(updated["approved"]),
            test_passed=bool(updated["test_passed"]),
            test_error=updated["test_error"],
            approval_notes=updated["approval_notes"],
        )

        logger.info(f"Tool '{tool_name}' approved")
        return tool

    def execute_dynamic_tool(
        self, tool_name: str, tool_input: Dict[str, Any]
    ) -> str:
        """
        Execute an approved dynamic tool.

        Args:
            tool_name: Name of tool to execute
            tool_input: Input parameters for the tool

        Returns:
            Result as string

        Raises:
            ToolFactoryError: Tool not found, not approved, or execution failed
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM dynamic_tools WHERE name = ? AND retired = 0",
            (tool_name,)
        ).fetchone()
        conn.close()

        if not row:
            raise ToolFactoryError(f"Tool '{tool_name}' not found")

        if not row["approved"]:
            raise ToolFactoryError(f"Tool '{tool_name}' is not approved")

        tool = DynamicTool(
            name=row["name"],
            description=row["description"],
            input_schema=json.loads(row["input_schema"]),
            implementation_type=row["implementation_type"],
            implementation=row["implementation"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            approved=bool(row["approved"]),
            test_passed=bool(row["test_passed"]),
            test_error=row["test_error"],
            approval_notes=row["approval_notes"],
        )

        try:
            return self._execute_tool_impl(tool, tool_input)
        except Exception as e:
            raise ToolFactoryError(f"Tool execution failed: {e}") from e

    def _execute_tool_impl(
        self, tool: DynamicTool, tool_input: Dict[str, Any]
    ) -> str:
        """Execute tool implementation and return result."""
        impl_type = tool.implementation_type

        if impl_type == "shell_command":
            return self._execute_shell(tool.implementation, tool_input)
        elif impl_type == "python_snippet":
            return self._execute_python(tool.implementation, tool_input)
        elif impl_type == "http_request":
            return self._execute_http(tool.implementation, tool_input)
        else:
            raise ToolFactoryError(f"Unknown implementation_type: {impl_type}")

    def _execute_shell(self, command: str, tool_input: Dict[str, Any]) -> str:
        """Execute shell command with input substitution."""
        # Simple parameter substitution: {param_name} -> tool_input[param_name]
        for key, value in tool_input.items():
            command = command.replace(f"{{{key}}}", str(value))

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=TOOL_TIMEOUT,
                cwd="/root",
            )
            if result.returncode != 0:
                return f"Error: {result.stderr}"
            return result.stdout
        except subprocess.TimeoutExpired:
            raise ToolTestError(f"Command timed out after {TOOL_TIMEOUT}s")
        except Exception as e:
            raise ToolTestError(f"Command execution failed: {e}")

    def _execute_python(self, code: str, tool_input: Dict[str, Any]) -> str:
        """Execute Python snippet in restricted namespace."""
        # Build restricted globals
        restricted_globals = {
            "__builtins__": {
                "print": print,
                "str": str,
                "int": int,
                "float": float,
                "list": list,
                "dict": dict,
                "tuple": tuple,
                "set": set,
                "len": len,
                "range": range,
                "sum": sum,
                "max": max,
                "min": min,
                "sorted": sorted,
                "enumerate": enumerate,
                "zip": zip,
                "map": map,
                "filter": filter,
                "abs": abs,
                "round": round,
                "pow": pow,
            },
            "input_data": tool_input,
        }

        try:
            # Capture output
            output_buffer = []

            def safe_print(*args, **kwargs):
                output_buffer.append(" ".join(str(a) for a in args))

            restricted_globals["__builtins__"]["print"] = safe_print

            exec(code, restricted_globals)

            # Try to return result or captured output
            if "result" in restricted_globals:
                return str(restricted_globals["result"])
            elif output_buffer:
                return "\n".join(output_buffer)
            else:
                return "OK"

        except Exception as e:
            raise ToolTestError(f"Python execution failed: {e}")

    def _execute_http(self, url: str, tool_input: Dict[str, Any]) -> str:
        """Execute HTTP request."""
        # Simple parameter substitution
        for key, value in tool_input.items():
            url = url.replace(f"{{{key}}}", str(value))

        try:
            # Determine method (default GET, or POST if input contains data)
            method = tool_input.get("method", "GET").upper()
            if method not in ["GET", "POST"]:
                raise ToolSafetyError(f"HTTP method not allowed: {method}")

            headers = tool_input.get("headers", {})
            if method == "GET":
                response = httpx.get(url, headers=headers, timeout=HTTP_TIMEOUT)
            else:
                data = tool_input.get("data", {})
                response = httpx.post(
                    url, json=data, headers=headers, timeout=HTTP_TIMEOUT
                )

            response.raise_for_status()
            return response.text

        except httpx.HTTPError as e:
            raise ToolTestError(f"HTTP request failed: {e}")
        except Exception as e:
            raise ToolTestError(f"HTTP execution failed: {e}")

    def list_dynamic_tools(self, approved_only: bool = True) -> List[DynamicTool]:
        """
        List all dynamic tools.

        Args:
            approved_only: If True, only return approved tools

        Returns:
            List of DynamicTool objects
        """
        conn = self._get_conn()

        if approved_only:
            rows = conn.execute(
                "SELECT * FROM dynamic_tools WHERE approved = 1 AND retired = 0"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM dynamic_tools WHERE retired = 0"
            ).fetchall()

        conn.close()

        return [
            DynamicTool(
                name=row["name"],
                description=row["description"],
                input_schema=json.loads(row["input_schema"]),
                implementation_type=row["implementation_type"],
                implementation=row["implementation"],
                created_by=row["created_by"],
                created_at=row["created_at"],
                approved=bool(row["approved"]),
                test_passed=bool(row["test_passed"]),
                test_error=row["test_error"],
                approval_notes=row["approval_notes"],
            )
            for row in rows
        ]

    def retire_tool(self, tool_name: str) -> bool:
        """
        Deactivate a tool (soft delete).

        Args:
            tool_name: Name of tool to retire

        Returns:
            True if successful

        Raises:
            ToolFactoryError: Tool not found
        """
        conn = self._get_conn()
        result = conn.execute(
            "UPDATE dynamic_tools SET retired = 1, retired_at = ? WHERE name = ?",
            (datetime.now(timezone.utc).isoformat(), tool_name),
        )
        conn.commit()
        conn.close()

        if result.rowcount == 0:
            raise ToolFactoryError(f"Tool '{tool_name}' not found")

        logger.info(f"Tool '{tool_name}' retired")
        return True

    def get_tool(self, tool_name: str) -> Optional[DynamicTool]:
        """Get a tool by name."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM dynamic_tools WHERE name = ? AND retired = 0",
            (tool_name,)
        ).fetchone()
        conn.close()

        if not row:
            return None

        return DynamicTool(
            name=row["name"],
            description=row["description"],
            input_schema=json.loads(row["input_schema"]),
            implementation_type=row["implementation_type"],
            implementation=row["implementation"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            approved=bool(row["approved"]),
            test_passed=bool(row["test_passed"]),
            test_error=row["test_error"],
            approval_notes=row["approval_notes"],
        )


# ═══════════════════════════════════════════════════════════════
# SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════

_factory_instance: Optional[ToolFactory] = None


def get_factory(db_path: str = DB_PATH) -> ToolFactory:
    """Get or create singleton ToolFactory instance."""
    global _factory_instance
    if _factory_instance is None:
        _factory_instance = ToolFactory(db_path)
    return _factory_instance
