"""
Agent Tools — Full execution capabilities for OpenClaw agents
GitHub, git, shell, Vercel, file I/O, web scraping, package install, research
Available to agents via Claude tool_use in /api/chat, Slack, and Telegram
"""

import os
import re
import subprocess
import json
import logging
import shutil
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import httpx

try:
    from diff_view import format_edit_result
    HAS_DIFF_VIEW = True
except ImportError:
    HAS_DIFF_VIEW = False

logger = logging.getLogger("agent_tools")

# ═══════════════════════════════════════════════════════════════
# SAFETY: Sandboxed shell execution with allowlists
# ═══════════════════════════════════════════════════════════════

# Commands that are safe to run (no rm -rf, no format, etc.)
SAFE_COMMAND_PREFIXES = [
    "git ", "gh ", "npm ", "npx ", "pnpm ", "bun ", "pip ", "pip3 ",
    "python3 ", "python ", "node ", "deno ", "cargo ",
    "ls ", "cat ", "head ", "tail ", "wc ", "grep ", "find ", "tree ",
    "curl ", "wget ", "jq ", "yq ",
    "vercel ", "wrangler ", "netlify ",
    "docker ", "docker-compose ",
    "oxo ",
    "mkdir ", "cp ", "mv ", "touch ", "chmod ",
    "pytest ", "jest ", "vitest ", "mocha ",
    "tsc ", "eslint ", "prettier ",
    "echo ", "pwd", "whoami", "date", "env ",
    "tar ", "zip ", "unzip ", "gzip ",
    "polymarket ",
    "cd ",
]

# Commands that are NEVER allowed
BLOCKED_COMMANDS = [
    "rm -rf /", "rm -rf /*", "mkfs", "dd if=", ":(){ :|:& };:",
    "shutdown", "reboot", "halt", "poweroff",
    "> /dev/sd", "chmod -R 777 /",
    # Interpreter inline-execution bypasses
    "python3 -c", "python -c",
    "node -e", "node --eval",
    "perl -e", "perl -E",
    "ruby -e",
    "bash -c", "sh -c", "zsh -c",
    # Dangerous file targets
    "/etc/shadow", "/etc/passwd",
    "~/.ssh", "/root/.ssh",
]

# Patterns for subshell / backtick injection with dangerous payloads
_DANGEROUS_SUBSHELL_PATTERNS = [
    re.compile(r'\$\(.*(?:rm|mkfs|dd|shutdown|reboot|halt|poweroff|chmod\s+-R|curl.*\|\s*(?:bash|sh)).*\)', re.IGNORECASE),
    re.compile(r'`.*(?:rm|mkfs|dd|shutdown|reboot|halt|poweroff|chmod\s+-R|curl.*\|\s*(?:bash|sh)).*`', re.IGNORECASE),
]

# Directories agents can write to
ALLOWED_WRITE_DIRS = [
    "/root/", "/tmp/", "/home/",
]

# Max output size from shell commands (chars)
MAX_SHELL_OUTPUT = 10000

# Max file read size
MAX_FILE_READ = 50000

# Tool definitions for Claude API
AGENT_TOOLS = [
    {
        "name": "github_repo_info",
        "description": "Get info about a GitHub repository (issues, PRs, status). Use this when the user asks about repo status, open issues, or PRs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/name format, e.g. 'Miles0sage/Barber-CRM'"
                },
                "action": {
                    "type": "string",
                    "enum": ["issues", "prs", "status", "commits"],
                    "description": "What to fetch: issues, prs, status (general info), or recent commits"
                }
            },
            "required": ["repo", "action"],
            "additionalProperties": False
        }
    },
    {
        "name": "github_create_issue",
        "description": "Create a GitHub issue on a repository. Use when asked to file a bug, feature request, or task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/name format"
                },
                "title": {
                    "type": "string",
                    "description": "Issue title"
                },
                "body": {
                    "type": "string",
                    "description": "Issue body/description"
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels to apply"
                }
            },
            "required": ["repo", "title"],
            "additionalProperties": False
        }
    },
    {
        "name": "web_search",
        "description": "Search the web for current information. Use when the user asks about recent events, documentation, tutorials, or anything requiring up-to-date info.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                }
            },
            "required": ["query"],
            "additionalProperties": False
        }
    },
    {
        "name": "create_job",
        "description": "Create a new job in the agency job queue. Use when someone asks to create a task, fix a bug, build a feature, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project name: barber-crm, openclaw, delhi-palace, prestress-calc, concrete-canoe"
                },
                "task": {
                    "type": "string",
                    "description": "Description of the task"
                },
                "priority": {
                    "type": "string",
                    "enum": ["P0", "P1", "P2", "P3"],
                    "description": "Priority: P0=critical, P1=high, P2=medium, P3=low"
                }
            },
            "required": ["project", "task"],
            "additionalProperties": False
        }
    },
    {
        "name": "list_jobs",
        "description": "List jobs in the agency queue, optionally filtered by status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "analyzing", "pr_ready", "approved", "done", "all"],
                    "description": "Filter by status, or 'all' to see everything"
                }
            },
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "create_proposal",
        "description": "Create a proposal that goes through auto-approval. Use this for non-trivial tasks that need cost estimation and approval before execution.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title for the proposal"},
                "description": {"type": "string", "description": "What needs to be done"},
                "agent_pref": {"type": "string", "enum": ["project_manager", "coder_agent", "hacker_agent", "database_agent"], "description": "Which agent should handle this"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags: routing, security, fix, feature, maintenance, etc."},
                "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"], "description": "Priority level"}
            },
            "required": ["title", "description"],
            "additionalProperties": False
        }
    },
    {
        "name": "get_cost_summary",
        "description": "Get current API cost summary and budget status. Use when asked about spending, budget, or costs.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "approve_job",
        "description": "Approve a job that's in pr_ready status for execution.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "The job ID to approve"}
            },
            "required": ["job_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "web_fetch",
        "description": "Fetch content from a URL and return readable text. Use for reading docs, articles, API responses.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"},
                "extract": {"type": "string", "enum": ["text", "links", "all"], "description": "What to extract: text content, links, or everything"}
            },
            "required": ["url"],
            "additionalProperties": False
        }
    },
    {
        "name": "get_events",
        "description": "Get recent system events (job completions, proposals, alerts). Use when asked about what's happening or recent activity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of events to return (default 10)"},
                "event_type": {"type": "string", "description": "Filter by type: job.created, job.completed, job.failed, proposal.created, cost.alert"}
            },
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "save_memory",
        "description": "Save an important fact, decision, or preference to long-term memory. Use when the user tells you something worth remembering across conversations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The fact or information to remember"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for categorization: project name, topic, etc."},
                "importance": {"type": "integer", "description": "1-10 scale. 10=critical decision, 7=preference, 5=useful fact, 3=minor detail"}
            },
            "required": ["content"],
            "additionalProperties": False
        }
    },
    {
        "name": "search_memory",
        "description": "Search through saved memories for relevant context. Use when you need to recall past decisions, preferences, or facts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
                "limit": {"type": "integer", "description": "Max results (default 5)"}
            },
            "required": ["query"],
            "additionalProperties": False
        }
    },
    {
        "name": "rebuild_semantic_index",
        "description": "Rebuild the semantic memory search index. Call after adding many new memories or memory files.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "flush_memory_before_compaction",
        "description": "Flush pending important facts to MEMORY.md before context compaction. Call when you detect context is >50% and want to preserve critical decisions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of important facts/decisions to save"
                }
            },
            "required": ["items"],
            "additionalProperties": False
        }
    },
    {
        "name": "recall_memory",
        "description": "Unified memory recall across all sources (semantic index, reflexion learnings, MEMORY.md topics, Supabase persistent store). Returns combined results ranked by relevance + importance. Use to access past knowledge, learnings, and context before starting complex tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (meaning-based retrieval)"},
                "limit": {"type": "integer", "description": "Max results per source (default: 5)"},
                "memory_sources": {"type": "array", "items": {"type": "string"}, "enum": ["semantic", "reflexion", "topics", "supabase"], "description": "Which sources to search (default: all)"},
                "project": {"type": "string", "description": "Project context for reflexion filtering (optional)"},
                "department": {"type": "string", "description": "Department context for reflexion filtering (optional)"}
            },
            "required": ["query"],
            "additionalProperties": False
        }
    },
    {
        "name": "send_slack_message",
        "description": "Send a message to a Slack channel. Use to proactively notify the team about important updates, completions, or alerts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The message to send"},
                "channel": {"type": "string", "description": "Channel ID (default: report channel C0AFE4QHKH7)"}
            },
            "required": ["message"],
            "additionalProperties": False
        }
    },
    {
        "name": "email_triage",
        "description": "Triage unread emails by urgency. Scores each email 1-10, categorizes (urgent/important/normal/low), and optionally drafts replies. Uses AI to analyze sender importance and content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_emails": {
                    "type": "integer",
                    "description": "Maximum number of emails to triage (default: 20)",
                    "default": 20
                },
                "auto_draft": {
                    "type": "boolean",
                    "description": "Whether to draft replies for urgent emails (default: false)",
                    "default": False
                },
                "vip_senders": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Email addresses to always mark as urgent"
                }
            },
            "required": [],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    # AGENCY MANAGEMENT TOOLS
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "kill_job",
        "description": "Cancel a running or pending job. Sets kill flag and terminates any tmux agent running it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "The job ID to cancel"}
            },
            "required": ["job_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "agency_status",
        "description": "Get combined agency overview: active jobs, recent completions, costs, active agents, alerts.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "manage_reactions",
        "description": "Manage auto-reaction rules (list, add, update, delete, get triggers history).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "add", "update", "delete", "triggers"], "description": "Action to perform"},
                "rule_id": {"type": "string", "description": "Rule ID (for update/delete)"},
                "rule_data": {"type": "object", "description": "Rule fields (for add/update)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    # EXECUTION TOOLS — Shell, Git, Vercel, File I/O, Packages
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "shell_execute",
        "description": "Execute a shell command on the server. Sandboxed to safe commands only (git, npm, python, node, curl, docker, vercel, etc). Use for building, testing, deploying, and system operations. Returns stdout/stderr.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run (e.g. 'npm run build', 'python3 test.py', 'git status')"},
                "cwd": {"type": "string", "description": "Working directory (default: /root)"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 60, max: 300)"}
            },
            "required": ["command"],
            "additionalProperties": False
        }
    },
    {
        "name": "git_operations",
        "description": "Perform git operations: status, add, commit, push, pull, branch, log, diff. Use for version control and deploying code to GitHub.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "add", "commit", "push", "pull", "branch", "log", "diff", "clone", "checkout"],
                    "description": "Git action to perform"
                },
                "repo_path": {"type": "string", "description": "Path to git repo (default: .)"},
                "args": {"type": "string", "description": "Additional arguments (e.g. commit message, branch name, file paths)"},
                "files": {"type": "array", "items": {"type": "string"}, "description": "Files to add (for 'add' action)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "vercel_deploy",
        "description": "Deploy a project to Vercel. Supports deploy, list deployments, set env vars, and check status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["deploy", "list", "env-set", "status", "logs"],
                    "description": "Vercel action"
                },
                "project_path": {"type": "string", "description": "Path to project to deploy"},
                "project_name": {"type": "string", "description": "Vercel project name (for status/logs)"},
                "env_key": {"type": "string", "description": "Environment variable key (for env-set)"},
                "env_value": {"type": "string", "description": "Environment variable value (for env-set)"},
                "production": {"type": "boolean", "description": "Deploy to production (default: true)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "file_read",
        "description": "Read contents of a file. Use to inspect code, configs, logs, or any text file on the server.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to file"},
                "lines": {"type": "integer", "description": "Max lines to read (default: all, max: 500)"},
                "offset": {"type": "integer", "description": "Start from this line number (0-based)"}
            },
            "required": ["path"],
            "additionalProperties": False
        }
    },
    {
        "name": "file_write",
        "description": "Write or append to a file. Use to create new files, edit configs, or save output. Restricted to allowed directories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to file"},
                "content": {"type": "string", "description": "Content to write"},
                "mode": {"type": "string", "enum": ["write", "append"], "description": "Write mode (default: write)"}
            },
            "required": ["path", "content"],
            "additionalProperties": False
        }
    },
    {
        "name": "install_package",
        "description": "Install a package or tool. Supports npm, pip, apt, and binary installs. Auto-detects if tool is already installed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Package name (e.g. 'express', 'requests', 'vercel')"},
                "manager": {"type": "string", "enum": ["npm", "pip", "apt", "binary"], "description": "Package manager to use"},
                "global_install": {"type": "boolean", "description": "Install globally (default: true for CLI tools)"}
            },
            "required": ["name", "manager"],
            "additionalProperties": False
        }
    },
    {
        "name": "research_task",
        "description": "Research a topic before executing. Searches the web, fetches relevant docs, and returns a synthesis. Use this BEFORE attempting complex tasks to gather context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "What to research (e.g. 'Next.js 16 deployment to Vercel', 'Supabase RLS best practices')"},
                "depth": {"type": "string", "enum": ["quick", "medium", "deep"], "description": "Research depth (default: medium)"}
            },
            "required": ["topic"],
            "additionalProperties": False
        }
    },
    {
        "name": "web_scrape",
        "description": "Scrape structured data from a webpage. Extracts text, links, headings, code blocks, or specific CSS selectors.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to scrape"},
                "extract": {"type": "string", "enum": ["text", "links", "headings", "code", "tables", "all"], "description": "What to extract (default: text)"},
                "selector": {"type": "string", "description": "CSS selector to target specific elements (optional)"}
            },
            "required": ["url"],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    # CODE EDITING TOOLS — Edit, Glob, Grep, Process, Env
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "file_edit",
        "description": "Edit a file by finding and replacing a specific string. Like surgical find-replace — doesn't overwrite the whole file. Use this to modify existing code, fix bugs, update configs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to file"},
                "old_string": {"type": "string", "description": "The exact string to find (must be unique in the file)"},
                "new_string": {"type": "string", "description": "The replacement string"},
                "replace_all": {"type": "boolean", "description": "Replace all occurrences (default: false, only first)"}
            },
            "required": ["path", "old_string", "new_string"],
            "additionalProperties": False
        }
    },
    {
        "name": "glob_files",
        "description": "Find files matching a glob pattern. Use to discover project structure, find all files of a type, locate configs. Returns file paths sorted by modification time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g. '**/*.py', 'src/**/*.ts', '*.json')"},
                "path": {"type": "string", "description": "Root directory to search in (default: /root)"},
                "max_results": {"type": "integer", "description": "Max files to return (default: 50)"}
            },
            "required": ["pattern"],
            "additionalProperties": False
        }
    },
    {
        "name": "grep_search",
        "description": "Search file contents using regex patterns. Find function definitions, variable usage, imports, error messages, etc. across a codebase.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for (e.g. 'def main', 'import.*fastapi', 'TODO|FIXME')"},
                "path": {"type": "string", "description": "File or directory to search in (default: /root)"},
                "file_pattern": {"type": "string", "description": "Filter files by glob (e.g. '*.py', '*.ts')"},
                "context_lines": {"type": "integer", "description": "Lines of context around matches (default: 2)"},
                "max_results": {"type": "integer", "description": "Max matches to return (default: 20)"}
            },
            "required": ["pattern"],
            "additionalProperties": False
        }
    },
    {
        "name": "process_manage",
        "description": "Manage running processes: list, kill, check ports. Use to manage servers, check what's running, free up ports.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "kill", "check_port", "top"],
                    "description": "Action: list processes, kill by PID/name, check what's on a port, or show top resource users"
                },
                "target": {"type": "string", "description": "PID, process name, or port number depending on action"},
                "signal": {"type": "string", "enum": ["TERM", "KILL", "HUP"], "description": "Signal for kill (default: TERM)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "env_manage",
        "description": "Manage environment variables and .env files. Read, set, list env vars. Load/save .env files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "set", "list", "load_dotenv", "save_dotenv"],
                    "description": "Action to perform"
                },
                "key": {"type": "string", "description": "Env var name (for get/set)"},
                "value": {"type": "string", "description": "Value to set (for set)"},
                "env_file": {"type": "string", "description": "Path to .env file (default: /root/.env)"},
                "filter": {"type": "string", "description": "Filter pattern for list (e.g. 'API', 'TOKEN')"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },

    # ═══════════════════════════════════════════════════════════════
    # TEST TOOLS — Automated testing, coverage, failure analysis
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "auto_test",
        "description": "Auto-Test Runner — Automatically run tests, detect failures, suggest fixes. Supports pytest, jest, vitest, go test, cargo test, mocha.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["run", "analyze", "watch", "coverage"],
                    "description": "Action: run (execute tests), analyze (parse failures), watch (run and suggest fixes), coverage (generate report)"
                },
                "project_path": {
                    "type": "string",
                    "description": "Path to project directory"
                },
                "framework": {
                    "type": "string",
                    "enum": ["auto", "pytest", "jest", "vitest", "go", "cargo", "mocha"],
                    "description": "Test framework (default: auto-detect)"
                },
                "test_pattern": {
                    "type": "string",
                    "description": "Glob pattern or specific test file to run (optional)"
                },
                "error_output": {
                    "type": "string",
                    "description": "Error message to analyze (for 'analyze' action)"
                },
                "test_file": {
                    "type": "string",
                    "description": "Path to failing test file (for 'analyze' action)"
                }
            },
            "required": ["action", "project_path"],
            "additionalProperties": False
        }
    },

    # ═══════════════════════════════════════════════════════════════
    # COMPUTE TOOLS — Precise algorithms, math, data processing
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "compute_sort",
        "description": "Sort a list of numbers or strings using O(n log n) algorithms. Returns sorted result with timing. Use when the user needs data sorted precisely — never approximate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "data": {"type": "array", "description": "List of numbers or strings to sort"},
                "algorithm": {
                    "type": "string",
                    "enum": ["auto", "mergesort", "heapsort", "quicksort", "timsort"],
                    "description": "Sorting algorithm (default: auto picks optimal)"
                },
                "reverse": {"type": "boolean", "description": "Sort descending (default: false)"},
                "key": {"type": "string", "description": "For dicts: key to sort by (e.g. 'price', 'name')"}
            },
            "required": ["data"],
            "additionalProperties": False
        }
    },
    {
        "name": "compute_stats",
        "description": "Calculate statistics on a list of numbers: mean, median, mode, std dev, variance, percentiles, min, max, sum. Precise — no LLM approximation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "data": {"type": "array", "items": {"type": "number"}, "description": "List of numbers"},
                "percentiles": {"type": "array", "items": {"type": "number"}, "description": "Percentiles to calculate (e.g. [25, 50, 75, 90, 99])"}
            },
            "required": ["data"],
            "additionalProperties": False
        }
    },
    {
        "name": "compute_math",
        "description": "Evaluate mathematical expressions precisely. Supports arithmetic, trig, log, factorial, combinations, GCD, LCM, modular arithmetic. Use instead of mental math.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Math expression (e.g. '2**64 - 1', 'math.factorial(20)', 'math.gcd(48, 18)')"},
                "precision": {"type": "integer", "description": "Decimal places for float results (default: 10)"}
            },
            "required": ["expression"],
            "additionalProperties": False
        }
    },
    {
        "name": "compute_search",
        "description": "Search/filter data using binary search, linear scan, or regex. O(log n) for sorted data. Use to find items in large datasets precisely.",
        "input_schema": {
            "type": "object",
            "properties": {
                "data": {"type": "array", "description": "Data to search through"},
                "target": {"description": "Value to find"},
                "method": {
                    "type": "string",
                    "enum": ["binary", "linear", "filter", "regex"],
                    "description": "Search method (binary requires sorted data)"
                },
                "condition": {"type": "string", "description": "For filter: Python expression using 'x' (e.g. 'x > 50', 'x % 2 == 0')"}
            },
            "required": ["data"],
            "additionalProperties": False
        }
    },
    {
        "name": "compute_matrix",
        "description": "Matrix operations: multiply, transpose, determinant, inverse, eigenvalues. For linear algebra computations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["multiply", "transpose", "determinant", "inverse", "eigenvalues", "solve"],
                    "description": "Matrix operation"
                },
                "matrix_a": {"type": "array", "description": "First matrix (2D array of numbers)"},
                "matrix_b": {"type": "array", "description": "Second matrix (for multiply) or vector (for solve)"}
            },
            "required": ["action", "matrix_a"],
            "additionalProperties": False
        }
    },
    {
        "name": "compute_prime",
        "description": "Prime number operations: factorize, primality test, generate primes, find nth prime. Exact integer arithmetic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["factorize", "is_prime", "generate", "nth_prime"],
                    "description": "What to compute"
                },
                "n": {"type": "integer", "description": "The number to test/factorize, or count of primes to generate"},
                "limit": {"type": "integer", "description": "Upper bound for 'generate' action"}
            },
            "required": ["action", "n"],
            "additionalProperties": False
        }
    },
    {
        "name": "compute_hash",
        "description": "Compute cryptographic hashes: SHA-256, SHA-512, MD5, BLAKE2. For data integrity verification and checksums.",
        "input_schema": {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "String to hash"},
                "algorithm": {
                    "type": "string",
                    "enum": ["sha256", "sha512", "md5", "blake2b", "sha1"],
                    "description": "Hash algorithm (default: sha256)"
                },
                "file_path": {"type": "string", "description": "Hash a file instead of a string"}
            },
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "compute_convert",
        "description": "Unit and base conversions: number bases (bin/oct/hex), temperatures, distances, data sizes, timestamps. Precise conversions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "value": {"description": "Value to convert"},
                "from_unit": {"type": "string", "description": "Source unit/base (e.g. 'celsius', 'hex', 'bytes', 'unix_timestamp')"},
                "to_unit": {"type": "string", "description": "Target unit/base (e.g. 'fahrenheit', 'decimal', 'gb', 'iso8601')"}
            },
            "required": ["value", "from_unit", "to_unit"],
            "additionalProperties": False
        }
    },
    {
        "name": "tmux_agents",
        "description": "Manage parallel Claude Code agents in tmux panes. Spawn agents with optional git worktree isolation, monitor status, collect output, kill agents. Elvis-pattern multi-agent orchestration.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["spawn", "spawn_parallel", "list", "output", "kill", "kill_all", "cleanup"],
                    "description": "Action: spawn a single agent, spawn multiple in parallel, list running agents, get output, kill one/all, or cleanup worktree"
                },
                "job_id": {"type": "string", "description": "Job identifier (for spawn, output, kill, cleanup)"},
                "prompt": {"type": "string", "description": "Agent prompt/instruction (for spawn)"},
                "pane_id": {"type": "string", "description": "Tmux pane ID (for output, kill)"},
                "jobs": {
                    "type": "array",
                    "description": "List of job dicts for spawn_parallel. Each needs: job_id, prompt. Optional: worktree_repo, cwd",
                    "items": {"type": "object"}
                },
                "worktree_repo": {"type": "string", "description": "Git repo path to create worktree from (for spawn)"},
                "use_worktree": {"type": "boolean", "description": "Create isolated git worktree (default: false)"},
                "cwd": {"type": "string", "description": "Working directory override (for spawn)"},
                "timeout_minutes": {"type": "integer", "description": "Kill agent after N minutes (default: 30, 0=no limit)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "security_scan",
        "description": "Run an OXO security scan against a target (IP, domain, or URL). Profiles: quick (Nmap only), full (Nmap+Nuclei), web (Nmap+Nuclei+ZAP). Returns scan results as text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target to scan: IP address, domain, or URL"},
                "scan_type": {
                    "type": "string",
                    "enum": ["quick", "full", "web"],
                    "description": "Scan profile: quick (Nmap), full (Nmap+Nuclei), web (Nmap+Nuclei+ZAP). Default: quick"
                },
                "agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Override: explicit list of OXO agent keys to run (e.g. ['agent/ostorlab/nmap'])"
                }
            },
            "required": ["target"],
            "additionalProperties": False
        }
    },
    {
        "name": "prediction_market",
        "description": "Query Polymarket prediction markets. Search markets, get details, list events. Use for checking probabilities on current events, elections, tech, crypto, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["search", "get_market", "list_markets", "list_events"],
                    "description": "Action: search markets, get specific market, list markets, list events"
                },
                "query": {"type": "string", "description": "Search query (for search action)"},
                "market_id": {"type": "string", "description": "Market ID or slug (for get_market action)"},
                "tag": {"type": "string", "description": "Event tag filter (for list_events, e.g. 'politics', 'crypto')"},
                "limit": {"type": "integer", "description": "Max results to return (default: 10)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "polymarket_prices",
        "description": "Get real-time Polymarket price data. Snapshot gives midpoint+spread+last trade for YES and NO with mispricing flag. Granular: spread, midpoint, book, last_trade, history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["snapshot", "spread", "midpoint", "book", "last_trade", "history"],
                    "description": "Action: snapshot (full overview), spread, midpoint, book (order book), last_trade, history (price chart)"
                },
                "market_id": {"type": "string", "description": "Market slug or numeric ID (e.g. 'will-trump-win-2024' or '12345')"},
                "token_id": {"type": "string", "description": "CLOB token ID (0x...) for granular queries — if omitted, auto-resolved from market_id"},
                "interval": {"type": "string", "description": "Price history interval: 1m, 1h, 6h, 1d, 1w, max (default: 1d)"},
                "fidelity": {"type": "integer", "description": "Number of data points for history (default: auto)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "polymarket_monitor",
        "description": "Monitor Polymarket markets and detect arbitrage. Mispricing detector checks if YES+NO sum deviates from $1.00. Also: open interest, volume, top holders, trader leaderboard, API health.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["mispricing", "open_interest", "volume", "holders", "leaderboard", "health"],
                    "description": "Action: mispricing (arb detector), open_interest, volume, holders, leaderboard, health"
                },
                "market_id": {"type": "string", "description": "Market slug or numeric ID"},
                "condition_id": {"type": "string", "description": "Market condition ID (0x...) for on-chain queries"},
                "event_id": {"type": "string", "description": "Event ID for volume queries"},
                "period": {"type": "string", "description": "Leaderboard period: day, week, month, all (default: week)"},
                "order_by": {"type": "string", "description": "Leaderboard order: pnl or vol (default: pnl)"},
                "limit": {"type": "integer", "description": "Max results (default: 10)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "polymarket_portfolio",
        "description": "View any Polymarket wallet's positions, trades, and on-chain activity (read-only). No wallet connection needed — works with any public address.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["positions", "closed", "trades", "value", "activity", "profile"],
                    "description": "Action: positions (open), closed, trades (history), value (total), activity (on-chain), profile"
                },
                "address": {"type": "string", "description": "Wallet address (0x...)"},
                "limit": {"type": "integer", "description": "Max results (default: 25)"}
            },
            "required": ["action", "address"],
            "additionalProperties": False
        }
    },
    {
        "name": "get_reflections",
        "description": "Get past job reflections (learnings from completed/failed jobs). Returns stats, recent reflections, or searches for reflections relevant to a task. Use to learn from past experience before starting work.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["stats", "list", "search"],
                    "description": "Action: stats (summary), list (recent reflections), search (find relevant reflections for a task)"
                },
                "task": {"type": "string", "description": "Task description to search for (required for search action)"},
                "project": {"type": "string", "description": "Filter by project name (optional)"},
                "limit": {"type": "integer", "description": "Max reflections to return (default: 5)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "create_event",
        "description": "Create/emit an event to the OpenClaw event engine. Use for logging custom events, milestones, or triggers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_type": {"type": "string", "description": "Event type: job.created, job.completed, job.failed, deploy.complete, cost.alert, custom, etc."},
                "data": {"type": "object", "description": "Event payload data (any key-value pairs)"}
            },
            "required": ["event_type"],
            "additionalProperties": False
        }
    },
    {
        "name": "plan_my_day",
        "description": "Plan the user's day: fetches calendar events, pending jobs, agency status, and emails to create a prioritized daily plan.",
        "input_schema": {
            "type": "object",
            "properties": {
                "focus": {"type": "string", "description": "Optional focus area: work, personal, or all (default: all)"}
            },
            "additionalProperties": False
        }
    },
    {
        "name": "morning_briefing",
        "description": "Generate a comprehensive morning briefing. Pulls calendar events, top emails, overdue tasks, industry news, and weather. Sends summary to Slack.",
        "input_schema": {
            "type": "object",
            "properties": {
                "send_to_slack": {"type": "boolean", "description": "Send briefing to Slack (default: true)"},
                "include_news": {"type": "boolean", "description": "Include AI/tech news headlines (default: true)"}
            },
            "required": [],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    # NEWS & SOCIAL MEDIA TOOLS
    # ═══════════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════════
    # PERPLEXITY RESEARCH
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "perplexity_research",
        "description": "Deep research using Perplexity Sonar — returns AI-synthesized answers with web citations. Better than web_search for complex questions requiring synthesis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Research question"},
                "model": {"type": "string", "enum": ["sonar", "sonar-pro"], "description": "Model: sonar (fast, cheap $1/M) or sonar-pro (deeper, $3/$15 per M). Default: sonar"},
                "focus": {"type": "string", "enum": ["web", "academic", "news"], "description": "Search focus: web (general), academic (papers/research), news (recent events). Default: web"}
            },
            "required": ["query"],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    # NEWS & SOCIAL MEDIA TOOLS
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "read_ai_news",
        "description": "Fetch RSS feeds from major AI news sources and return article summaries. Great for staying up to date on AI research, product launches, and industry news.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max articles to return (default: 10)"},
                "source": {"type": "string", "description": "Filter to specific source: openai, deepmind, huggingface, arxiv, verge, arstechnica, techcrunch, hackernews, mittech"},
                "hours": {"type": "integer", "description": "Only return articles from last N hours (default: 24)"}
            },
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "read_tweets",
        "description": "Read recent AI community posts and social media. Tries Reddit AI subs (primary), then Bluesky, then RSSHub Twitter, then Nitter, then web search. Returns posts with text, links, and platform.",
        "input_schema": {
            "type": "object",
            "properties": {
                "account": {"type": "string", "description": "Twitter username to read (without @). Default: reads from a list of top AI accounts"},
                "limit": {"type": "integer", "description": "Max tweets per account (default: 5)"},
            },
            "required": [],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    # TRADING ENGINE — Phase 2 (Kalshi + Polymarket + Arb + Safety)
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "kalshi_markets",
        "description": "Search and view Kalshi prediction market data. Read-only — no auth needed. Actions: search (by keyword), get (specific ticker), orderbook, trades, candlesticks (price history), events (categories).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["search", "get", "orderbook", "trades", "candlesticks", "events"], "description": "Action to perform"},
                "ticker": {"type": "string", "description": "Market ticker (for get, orderbook, trades, candlesticks)"},
                "query": {"type": "string", "description": "Search keyword (for search action)"},
                "event_ticker": {"type": "string", "description": "Event ticker to filter markets"},
                "status": {"type": "string", "description": "Market status filter: open, closed, settled"},
                "limit": {"type": "integer", "description": "Max results (default: 20)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "kalshi_trade",
        "description": "Place, cancel, and manage Kalshi orders. Safety-checked with dry-run default. Actions: buy, sell, market_buy, market_sell, cancel, cancel_all, list_orders. All amounts in cents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["buy", "sell", "market_buy", "market_sell", "cancel", "cancel_all", "list_orders"], "description": "Trading action"},
                "ticker": {"type": "string", "description": "Market ticker"},
                "side": {"type": "string", "enum": ["yes", "no"], "description": "Side: yes or no"},
                "price": {"type": "integer", "description": "Price in cents (1-99)"},
                "count": {"type": "integer", "description": "Number of contracts"},
                "order_id": {"type": "string", "description": "Order ID (for cancel)"},
                "dry_run": {"type": "boolean", "description": "Simulate without placing real order (default: true)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "kalshi_portfolio",
        "description": "View Kalshi portfolio — balance, positions, fills, settlements. Requires API credentials. Actions: balance, positions, fills, settlements, summary.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["balance", "positions", "fills", "settlements", "summary"], "description": "Portfolio action"},
                "limit": {"type": "integer", "description": "Max results (default: 50)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "polymarket_trade",
        "description": "Place, cancel, and manage Polymarket orders. Routes through Cloudflare proxy to bypass US geoblock. Safety-checked with dry-run default. Actions: buy, sell, market_buy, market_sell, cancel, cancel_all, list_orders.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["buy", "sell", "market_buy", "market_sell", "cancel", "cancel_all", "list_orders"], "description": "Trading action"},
                "market_id": {"type": "string", "description": "Market slug or ID"},
                "side": {"type": "string", "enum": ["yes", "no"], "description": "Side: yes or no"},
                "price": {"type": "number", "description": "Price (0.01-0.99)"},
                "size": {"type": "number", "description": "Number of shares"},
                "order_id": {"type": "string", "description": "Order ID (for cancel)"},
                "dry_run": {"type": "boolean", "description": "Simulate without placing real order (default: true)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "arb_scanner",
        "description": "Cross-platform arbitrage scanner for Polymarket + Kalshi. Actions: scan (auto-find matching events, compare prices), compare (specific keyword), bonds (high-probability >90% contracts), mispricing (YES+NO != $1.00).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["scan", "compare", "bonds", "mispricing"], "description": "Scanner action"},
                "query": {"type": "string", "description": "Search keyword to filter markets"},
                "min_edge": {"type": "number", "description": "Minimum price edge to report (default: 0.02 = 2 cents)"},
                "max_results": {"type": "integer", "description": "Max results (default: 10)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "trading_strategies",
        "description": "Automated trading opportunity scanners across Polymarket and Kalshi. Actions: bonds (>90% contracts), mispricing (price gaps), whale_alerts (top wallet moves), trending (volume spikes), expiring (closing soon), summary (run all).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["bonds", "mispricing", "whale_alerts", "trending", "expiring", "summary"], "description": "Strategy action"},
                "params": {"type": "object", "description": "Strategy-specific parameters (query, limit, min_edge, hours, etc.)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "trading_safety",
        "description": "Manage trading safety configuration — dry-run toggle, kill switch, position limits, trade audit log. Actions: status, get_config, set_config, trade_log, kill_switch, reset.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "get_config", "set_config", "trade_log", "kill_switch", "reset"], "description": "Safety action"},
                "config": {"type": "object", "description": "Config fields to update (for set_config). Keys: dry_run, kill_switch, confirm_threshold_cents, max_per_market_cents, max_total_exposure_cents"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    # ═ Money Engine — Unified scanner (Phase 4)
    {
        "name": "money_engine",
        "description": "Unified money-making scanner — sports +EV, prediction market arb, crypto signals. Proven strategies with mathematical edge. Actions: scan (full scan all), sports (XGBoost +EV, arb), prediction (bonds, arb, mispricing), crypto (fear/greed, movers), dashboard (quick picks), explain (strategy details).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["scan", "sports", "prediction", "crypto", "dashboard", "explain"], "description": "Engine action"},
                "params": {"type": "object", "description": "Optional params: {sport, hours, limit}"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    # ═ Betting Brain — Intelligent Research + Prediction (Phase 4)
    {
        "name": "betting_brain",
        "description": "Intelligent betting research agent — reads news, injuries, line movements, understands HOW sportsbooks set lines and WHERE they're wrong. Combines XGBoost model + market context for informed picks. Actions: research (full report), find_value (model vs odds + context), line_analysis (line movement analysis), prediction_research (prediction markets with context), how_lines_work (educational).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["research", "find_value", "line_analysis", "prediction_research", "how_lines_work"], "description": "Brain action"},
                "params": {"type": "object", "description": "Optional params: {sport, sport_key}"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    # ═ Sportsbook Odds + Betting Engine (Phase 3)
    {
        "name": "sportsbook_odds",
        "description": "Live sportsbook odds from 200+ bookmakers via The Odds API. Actions: sports (list in-season), odds (live odds for a sport), event (all markets for one game), compare (side-by-side bookmaker comparison), best_odds (best line for each outcome), player_props (player prop odds: points, rebounds, assists, etc. — less efficient market, higher edge potential).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["sports", "odds", "event", "compare", "best_odds", "player_props"], "description": "Odds action"},
                "sport": {"type": "string", "description": "Sport key (e.g. basketball_nba, americanfootball_nfl). Use action=sports to list."},
                "market": {"type": "string", "description": "Market type: h2h (moneyline), spreads, totals. Default: h2h"},
                "bookmakers": {"type": "string", "description": "Comma-separated bookmaker keys to filter (e.g. draftkings,fanduel)"},
                "event_id": {"type": "string", "description": "Event ID for action=event"},
                "limit": {"type": "integer", "description": "Max results (default: 10)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "sportsbook_arb",
        "description": "Sportsbook arbitrage + EV scanner. Actions: scan (find arbs where implied probs < 100%), calculate (optimal stake allocation for a specific arb), ev_scan (compare soft book odds vs Pinnacle sharp line, flag +EV bets).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["scan", "calculate", "ev_scan"], "description": "Scanner action"},
                "sport": {"type": "string", "description": "Sport key (default: basketball_nba)"},
                "event_id": {"type": "string", "description": "Event ID for action=calculate"},
                "min_profit": {"type": "number", "description": "Minimum arb profit % to report (default: 0)"},
                "min_ev": {"type": "number", "description": "Minimum EV to flag (default: 0.01 = 1%)"},
                "limit": {"type": "integer", "description": "Max results (default: 10)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "sports_predict",
        "description": "XGBoost-powered NBA game predictions. Actions: predict (today's games with win probabilities), evaluate (model accuracy + Brier score), train (retrain on 3 seasons), features (model feature weights), compare (predictions vs current odds → +EV recommendations).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["predict", "evaluate", "train", "features", "compare"], "description": "Prediction action"},
                "sport": {"type": "string", "description": "Sport: nba (default, only supported currently)"},
                "team": {"type": "string", "description": "Team name or abbreviation (for team-specific queries)"},
                "date": {"type": "string", "description": "Date for predictions (YYYY-MM-DD, default: today)"},
                "limit": {"type": "integer", "description": "Max results (default: 10)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "sports_betting",
        "description": "Full betting pipeline: XGBoost predictions + live odds + EV calculation + Kelly sizing. Actions: recommend (full pipeline with picks), bankroll (Kelly-sized recommendations), dashboard (multi-sport opportunity summary).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["recommend", "bankroll", "dashboard"], "description": "Betting action"},
                "sport": {"type": "string", "description": "Sport: nba (default)"},
                "bankroll": {"type": "number", "description": "Bankroll amount in USD (default: 100)"},
                "min_ev": {"type": "number", "description": "Minimum EV threshold (default: 0.01 = 1%)"},
                "limit": {"type": "integer", "description": "Max results (default: 10)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "prediction_tracker",
        "description": "Track sports predictions and results over time. Actions: log (save today's predictions before games), check (grade a day's predictions against actual scores), record (overall track record across all days), yesterday (grade yesterday + show results).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["log", "check", "record", "yesterday"], "description": "Tracker action"},
                "date": {"type": "string", "description": "Date to check (YYYY-MM-DD, default: yesterday for check, today for log)"},
                "bankroll": {"type": "number", "description": "Bankroll for logging recommendations (default: 100)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "bet_tracker",
        "description": "Bet tracking + P&L system. Tracks every bet recommendation, whether it was placed, and the result. Stores in data/betting/bet_ledger.json. Actions: log (log new bet), settle (settle bet), pending (show unsettled bets), history (show last N settled bets), pnl (P&L summary), daily (today's P&L), streak (win/loss streak).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["log", "settle", "pending", "history", "pnl", "daily", "streak"], "description": "Bet tracker action"},
                "params": {"type": "object", "description": "Action parameters: log needs game/side/odds/model_prob/edge_pct/book/stake_usd/market; settle needs bet_id/result; history needs limit"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    # DEEP RESEARCH ENGINE
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "deep_research",
        "description": "Multi-step autonomous deep research. Breaks a complex question into sub-questions, researches each in parallel via Perplexity Sonar, then synthesizes into a structured Markdown report with citations. Modes: general, market, technical, academic, news, due_diligence. Depth: quick (3 sub-Qs), medium (5), deep (8).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The research question or topic to investigate"},
                "depth": {"type": "string", "enum": ["quick", "medium", "deep"], "description": "Research depth: quick (3 sub-questions, ~30s), medium (5, ~1min), deep (8, ~2min). Default: medium"},
                "mode": {"type": "string", "enum": ["general", "market", "technical", "academic", "news", "due_diligence"], "description": "Domain mode: general (balanced), market (competitors/sizing/trends), technical (architecture/benchmarks), academic (papers/citations), news (recent events), due_diligence (red flags/risks). Default: general"},
                "max_sources": {"type": "integer", "description": "Override max Perplexity API calls (default: auto based on depth, max 8)"},
            },
            "required": ["query"],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    # PROPOSAL GENERATOR
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "generate_proposal",
        "description": "Generate a branded HTML client proposal for OpenClaw. Creates a professional proposal document with executive summary, service details, pricing, case studies, timeline, and terms. Saves to data/proposals/. Use when a potential client needs a formal proposal.",
        "input_schema": {
            "type": "object",
            "properties": {
                "business_name": {"type": "string", "description": "Name of the client's business"},
                "business_type": {"type": "string", "enum": ["restaurant", "barbershop", "dental", "auto", "realestate", "other"], "description": "Type of business (used to tailor the proposal content)"},
                "owner_name": {"type": "string", "description": "Name of the business owner"},
                "selected_services": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["receptionist", "website", "crm", "full_package"]},
                    "description": "Services to include: receptionist ($1500), website ($2500), crm ($3000), full_package ($5500 bundle)"
                },
                "custom_notes": {"type": "string", "description": "Optional custom notes or special requirements to include in the proposal"},
            },
            "required": ["business_name", "business_type", "owner_name", "selected_services"],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "find_leads",
        "description": "Search Google Maps and web for real local businesses. Finds restaurants, barbershops, dental offices, auto shops, real estate agencies etc. Returns business name, phone, address, website, rating. Saves leads automatically. Use when Miles wants to find potential clients to reach out to.",
        "input_schema": {
            "type": "object",
            "properties": {
                "business_type": {"type": "string", "description": "Type of business to search for: restaurants, barbershops, dental offices, auto repair shops, real estate agencies, etc."},
                "location": {"type": "string", "description": "City and state to search in. Default: Flagstaff, AZ"},
                "limit": {"type": "integer", "description": "Max number of leads to find. Default: 10"},
                "save": {"type": "boolean", "description": "Save leads to disk. Default: true"},
            },
            "required": ["business_type"],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "sales_call",
        "description": "Make an AI outbound sales call to a business lead using Vapi + ElevenLabs. The AI introduces OpenClaw, pitches services based on business type, handles objections, and tries to book a meeting. Use when Miles wants to call leads or prospects.",
        "input_schema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "Phone number to call"},
                "business_name": {"type": "string", "description": "Name of the business"},
                "business_type": {"type": "string", "description": "Type: restaurant, barbershop, dental, auto, real_estate"},
                "owner_name": {"type": "string", "description": "Owner's name if known"},
            },
            "required": ["phone", "business_name"],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    # Blackboard shared state tools
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "blackboard_read",
        "description": "Read a shared state entry from the blackboard. Use to check context from previous jobs (files changed, patterns, outcomes).",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Entry key to read"},
                "project": {"type": "string", "description": "Project scope (e.g. 'openclaw', 'barber-crm')"},
            },
            "required": ["key"],
            "additionalProperties": False
        }
    },
    {
        "name": "blackboard_write",
        "description": "Write a shared state entry to the blackboard. Use to share findings (files changed, patterns discovered, outcomes) with future jobs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Entry key (e.g. 'auth_pattern', 'files_changed')"},
                "value": {"type": "string", "description": "Entry value (any string, often JSON)"},
                "project": {"type": "string", "description": "Project scope"},
                "ttl_seconds": {"type": "integer", "description": "Auto-expire after this many seconds (0 = never, default: 604800 = 7 days)"},
            },
            "required": ["key", "value"],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    # SMS TOOLS (Twilio)
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "send_sms",
        "description": "Send an SMS text message via Twilio. Use to notify Miles, send alerts, or communicate with clients. Rate limited to 10/hour.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Phone number in E.164 format (e.g. +15551234567)"},
                "body": {"type": "string", "description": "Message text (max 1600 chars)"},
            },
            "required": ["to", "body"],
            "additionalProperties": False
        }
    },
    {
        "name": "sms_history",
        "description": "Get recent SMS messages sent or received. Use to check delivery status or see conversation history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["sent", "received", "all"], "description": "Filter by direction (default: all)"},
                "limit": {"type": "integer", "description": "Max messages to return (default: 10)"},
            },
            "required": [],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════════════
    # PinchTab — Browser Automation for AI Agents
    # ═══════════════════════════════════════════════════════════════════════
    {
        "name": "browser_navigate",
        "description": "Navigate the browser to a URL. Opens the page and returns the accessibility tree snapshot for agent interaction.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to navigate to"},
            },
            "required": ["url"],
            "additionalProperties": False
        }
    },
    {
        "name": "browser_snapshot",
        "description": "Get the accessibility tree of the current browser page. Returns structured refs (e0, e1...) for clicking/typing. Primary way to 'see' the page.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "browser_action",
        "description": "Perform a browser action: click, type, fill, press, hover, select, scroll. Use refs from snapshot (e.g. 'e5') or CSS selectors.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["click", "type", "fill", "press", "hover", "select", "scroll", "focus", "humanClick", "humanType"], "description": "Action to perform (humanClick/humanType simulate real user behavior)"},
                "ref": {"type": "string", "description": "Element ref from snapshot (e.g. 'e5') or CSS selector"},
                "value": {"type": "string", "description": "Value for type/fill/press/select actions"},
            },
            "required": ["action", "ref"],
            "additionalProperties": False
        }
    },
    {
        "name": "browser_text",
        "description": "Extract readable text from the current page. Strips nav/ads in readability mode, or returns raw full text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["readability", "raw"], "description": "Extraction mode (default: readability)"},
            },
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "browser_screenshot",
        "description": "Take a JPEG screenshot of the current browser page. Returns base64-encoded image.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "browser_tabs",
        "description": "List open browser tabs, or open/close a tab.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "open", "close"], "description": "Tab action (default: list)"},
                "url": {"type": "string", "description": "URL to open (for 'open' action)"},
                "tab_id": {"type": "string", "description": "Tab ID to close (for 'close' action)"},
            },
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "browser_evaluate",
        "description": "Execute JavaScript in the current browser tab. Escape hatch for any workflow gap.",
        "input_schema": {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "JavaScript code to execute"},
            },
            "required": ["script"],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    # NOTION TOOLS — Page & Database Management
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "notion_search",
        "description": "Search across all Notion content. Use to find pages, databases, or specific content by keyword.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (e.g. 'meeting notes', 'project status')"},
                "limit": {"type": "integer", "description": "Max results to return (default: 10)"},
            },
            "required": ["query"],
            "additionalProperties": False
        }
    },
    {
        "name": "notion_query",
        "description": "Query a Notion database with filters. Use to fetch records from a database with optional filtering, sorting, and pagination.",
        "input_schema": {
            "type": "object",
            "properties": {
                "database_id": {"type": "string", "description": "The ID of the Notion database (UUID with or without dashes)"},
                "filter": {"type": "string", "description": "Filter criteria as JSON (e.g. {\"property\": \"Status\", \"select\": {\"equals\": \"Done\"}})"},
                "sorts": {"type": "string", "description": "Sort criteria as JSON (e.g. [{\"property\": \"Due Date\", \"direction\": \"ascending\"}])"},
                "limit": {"type": "integer", "description": "Max results (default: 10)"},
            },
            "required": ["database_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "notion_create_page",
        "description": "Create a new page in a Notion database. Use to add a record with properties and optional content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "database_id": {"type": "string", "description": "The ID of the Notion database"},
                "properties": {"type": "string", "description": "Page properties as JSON (e.g. {\"Name\": {\"title\": [{\"text\": {\"content\": \"Title\"}}]}, \"Status\": {\"select\": {\"name\": \"Done\"}}})"},
                "content": {"type": "string", "description": "Page content in Notion block format (optional)"},
            },
            "required": ["database_id", "properties"],
            "additionalProperties": False
        }
    },
    {
        "name": "notion_update_page",
        "description": "Update properties on an existing Notion page. Use to change page status, dates, text fields, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "The ID of the Notion page to update"},
                "properties": {"type": "string", "description": "Properties to update as JSON (e.g. {\"Status\": {\"select\": {\"name\": \"In Progress\"}}})"},
            },
            "required": ["page_id", "properties"],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    # CLAUDE CODE HEADLESS — Spawn Claude Code agents programmatically
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "claude_headless",
        "description": "Spawn Claude Code agent programmatically for complex tasks. RESTRICTED: Overseer only. Actions: run (execute prompt), review_pr (code review), fix_test (auto-fix failing test), build_feature (implement from spec), debug_issue (debug and propose fix), audit_code (security/performance audit).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["run", "review_pr", "fix_test", "build_feature", "debug_issue", "audit_code"], "description": "Action to perform"},
                "prompt": {"type": "string", "description": "Task prompt (for 'run' action)"},
                "repo_path": {"type": "string", "description": "Repository path (for review_pr, debug_issue, audit_code)"},
                "branch": {"type": "string", "description": "Branch to review (for review_pr)"},
                "pr_number": {"type": "integer", "description": "PR number for context (optional)"},
                "test_file": {"type": "string", "description": "Path to failing test (for fix_test)"},
                "error": {"type": "string", "description": "Test error message or issue description"},
                "spec": {"type": "string", "description": "Feature specification (for build_feature)"},
                "project_path": {"type": "string", "description": "Root project path (default: .)"},
                "focus": {"type": "string", "enum": ["security", "performance", "maintainability"], "description": "Audit focus (for audit_code)"},
                "cwd": {"type": "string", "description": "Working directory override"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 300)"},
                "model": {"type": "string", "description": "Model override (e.g. 'opus', 'sonnet')"},
                "max_turns": {"type": "integer", "description": "Maximum turns (default: varies by action)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "dispatch_pc_code",
        "description": "Dispatch a coding task to Miles' Windows PC via SSH over Tailscale. Runs Claude Code headless on the PC. Returns job_id for status tracking.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "The task to execute on the PC (e.g. 'Fix button styling', 'Add login feature')"},
                "timeout": {"type": "integer", "description": "Job timeout in seconds (default: 300)"},
                "metadata": {"type": "object", "description": "Optional metadata like project name"}
            },
            "required": ["prompt"],
            "additionalProperties": False
        }
    },
    {
        "name": "dispatch_pc_ollama",
        "description": "Dispatch an inference request to Ollama on Miles' PC. Uses qwen2.5-coder:7b by default for local LLM inference.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "The prompt to send to Ollama"},
                "model": {"type": "string", "description": "Model name (default: qwen2.5-coder:7b)"},
                "timeout": {"type": "integer", "description": "Job timeout in seconds (default: 300)"}
            },
            "required": ["prompt"],
            "additionalProperties": False
        }
    },
    {
        "name": "check_pc_health",
        "description": "Check if Miles' PC is reachable and ready. Verifies SSH connectivity, Claude availability, and Ollama availability.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "get_dispatch_status",
        "description": "Get status of a dispatched PC job. Use job_id returned from dispatch_pc_code or dispatch_pc_ollama.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID returned from dispatch (e.g. 'pc_abc123def456')"}
            },
            "required": ["job_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "list_dispatch_jobs",
        "description": "List all PC dispatch jobs, optionally filtered by status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["pending", "running", "completed", "failed"], "description": "Filter by job status (optional)"}
            },
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "claude_code_build",
        "description": "Run Claude Code headless to build features, fix bugs, or refactor code in any repo on this VPS. Uses Max subscription (no API cost). Claude Code reads the codebase, writes code, runs tests, and commits. For complex coding tasks that need full codebase awareness.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the repo, e.g. '/root/roomcraft' or '.'"
                },
                "prompt": {
                    "type": "string",
                    "description": "Detailed instruction for what to build/fix/change. Be specific about files, features, and expected behavior."
                },
                "max_budget_usd": {
                    "type": "number",
                    "description": "Max spend in USD for this session (default 2.00, max 10.00)"
                },
                "model": {
                    "type": "string",
                    "enum": ["opus", "sonnet"],
                    "description": "Model to use: 'opus' for complex tasks, 'sonnet' for simple tasks (default: sonnet)"
                },
                "commit": {
                    "type": "boolean",
                    "description": "Whether to commit changes after completion (default: false)"
                }
            },
            "required": ["repo_path", "prompt"],
            "additionalProperties": False
        }
    },
    {
        "name": "claude_code_github_issue",
        "description": "Create a GitHub issue with the 'claude' label to trigger the Claude Code GitHub Action. The action will autonomously read the codebase, implement the feature, and create a PR. Uses Max subscription OAuth. Best for repos with the claude.yml workflow installed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/name format, e.g. 'Miles0sage/roomcraft'"
                },
                "title": {
                    "type": "string",
                    "description": "Issue title describing the feature/fix"
                },
                "body": {
                    "type": "string",
                    "description": "Detailed description of what to build. Include file paths, expected behavior, and acceptance criteria."
                }
            },
            "required": ["repo", "title", "body"],
            "additionalProperties": False
        }
    },
    # ── Codex CLI (GPT-5) Tools ──────────────────────────────
    {
        "name": "codex_build",
        "description": "Run Codex CLI (GPT-5) headless to build features, fix bugs, or refactor code in any repo on this VPS. Uses ChatGPT Plus subscription ($20/mo, no API cost). Codex reads the codebase, writes code, runs tests. For coding tasks where you want GPT-5 instead of Claude.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the repo, e.g. '/root/roomcraft'"
                },
                "prompt": {
                    "type": "string",
                    "description": "Detailed instruction for what to build/fix/change."
                },
                "model": {
                    "type": "string",
                    "enum": ["gpt-5", "gpt-5.4", "o3"],
                    "description": "Model to use (default: gpt-5)"
                },
                "sandbox": {
                    "type": "string",
                    "enum": ["read-only", "workspace-write", "danger-full-access"],
                    "description": "Sandbox mode (default: workspace-write)"
                }
            },
            "required": ["repo_path", "prompt"],
            "additionalProperties": False
        }
    },
    {
        "name": "codex_query",
        "description": "Query GPT-5 for reasoning, analysis, or second opinions without file system access. Uses ChatGPT Plus subscription. Good for: validating Claude's output, getting alternative approaches, research synthesis, code review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Question or analysis task for GPT-5"
                },
                "model": {
                    "type": "string",
                    "enum": ["gpt-5", "gpt-5.4", "o3"],
                    "description": "Model to use (default: gpt-5)"
                }
            },
            "required": ["prompt"],
            "additionalProperties": False
        }
    },
    {
        "name": "codex_github_issue",
        "description": "Create a GitHub issue with the 'codex' label to trigger the Codex CLI cron pipeline. Codex will autonomously implement the feature, run tests, and create a PR. Uses ChatGPT Plus subscription. For repos with codex-cron.sh installed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/name format, e.g. 'Miles0sage/Mathcad-Scripts'"
                },
                "title": {
                    "type": "string",
                    "description": "Issue title describing the feature/fix"
                },
                "body": {
                    "type": "string",
                    "description": "Detailed description of what to build."
                }
            },
            "required": ["repo", "title", "body"],
            "additionalProperties": False
        }
    },
    {
        "name": "propose_tool",
        "description": "Propose a new dynamic tool to the tool factory. Defines tool name, description, and input schema. Tool will be validated against safety constraints (shell patterns, forbidden imports, IP blocking) and stored for approval/execution.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Unique name for the tool (alphanumeric, underscores, hyphens only)"
                },
                "description": {
                    "type": "string",
                    "description": "Clear description of what the tool does"
                },
                "input_schema": {
                    "type": "object",
                    "description": "JSON Schema for tool input parameters"
                },
                "implementation": {
                    "type": "string",
                    "description": "Python function body (def handler(params: dict) -> str: ...)"
                },
                "category": {
                    "type": "string",
                    "enum": ["data", "integration", "automation", "analysis", "utility"],
                    "description": "Tool category for organization"
                }
            },
            "required": ["name", "description", "input_schema", "implementation"],
            "additionalProperties": False
        }
    },
    # ── Free Coding Tools — Fallback Chain ────────────────
    {
        "name": "aider_build",
        "description": "Run Aider headless to edit code. Aider is an AI pair programmer that edits code using Claude/Gemini. Free tier uses Gemini 2.5 Flash by default.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the repo"
                },
                "prompt": {
                    "type": "string",
                    "description": "Detailed instruction for what to build/fix/change."
                },
                "model": {
                    "type": "string",
                    "description": "Model to use (default: gemini/gemini-2.5-flash). Can also use claude-3-5-sonnet, gpt-4, etc."
                }
            },
            "required": ["repo_path", "prompt"],
            "additionalProperties": False
        }
    },
    {
        "name": "gemini_cli_build",
        "description": "Run Gemini CLI headless for coding tasks. Google's Gemini CLI provides free-tier access to Gemini 2.5 Flash.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the repo"
                },
                "prompt": {
                    "type": "string",
                    "description": "Detailed instruction for what to build/fix/change."
                }
            },
            "required": ["repo_path", "prompt"],
            "additionalProperties": False
        }
    },
    {
        "name": "goose_build",
        "description": "Run Goose headless for coding tasks. Goose is a universal AI agent framework supporting multiple LLM providers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the repo"
                },
                "prompt": {
                    "type": "string",
                    "description": "Detailed instruction for what to build/fix/change."
                }
            },
            "required": ["repo_path", "prompt"],
            "additionalProperties": False
        }
    },
    {
        "name": "opencode_build",
        "description": "Run OpenCode headless for coding tasks. OpenCode is a terminal-based AI assistant for software development.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the repo"
                },
                "prompt": {
                    "type": "string",
                    "description": "Detailed instruction for what to build/fix/change."
                }
            },
            "required": ["repo_path", "prompt"],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    # FINANCIAL TRACKING TOOLS
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "track_expense",
        "description": "Track an expense or income. Stores to Supabase finance_transactions table. Categories: food, transport, housing, utilities, entertainment, health, business, software, subscriptions, other.",
        "input_schema": {
            "type": "object",
            "properties": {
                "amount": {
                    "type": "number",
                    "description": "Amount in USD"
                },
                "category": {
                    "type": "string",
                    "enum": ["food", "transport", "housing", "utilities", "entertainment", "health", "business", "software", "subscriptions", "other"],
                    "description": "Transaction category"
                },
                "description": {
                    "type": "string",
                    "description": "Transaction description"
                },
                "type": {
                    "type": "string",
                    "enum": ["expense", "income"],
                    "description": "Transaction type (default: expense)"
                },
                "date": {
                    "type": "string",
                    "description": "Transaction date in YYYY-MM-DD format (optional, defaults to today)"
                }
            },
            "required": ["amount", "category", "description"],
            "additionalProperties": False
        }
    },
    {
        "name": "financial_summary",
        "description": "Get financial summary for a period. Shows income, expenses by category, net, and top spending areas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "week", "month", "year"],
                    "description": "Time period for summary (default: month)"
                }
            },
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "process_document",
        "description": "Process documents (receipts, invoices, contracts) via OCR. Extracts text, identifies key fields (amounts, dates, vendor names), and categorizes. Supports images and PDFs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to document file (image or PDF)"
                },
                "doc_type": {
                    "type": "string",
                    "enum": ["receipt", "invoice", "contract", "general"],
                    "description": "Document type (default: general)"
                },
                "extract_fields": {
                    "type": "boolean",
                    "description": "Whether to extract structured data (default: true)"
                }
            },
            "required": ["file_path"],
            "additionalProperties": False
        }
    },
    {
        "name": "invoice_tracker",
        "description": "Track invoices sent to clients. Create, update status (sent/paid/overdue), list outstanding.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "update_status", "list_outstanding"],
                    "description": "Action to perform"
                },
                "client_name": {
                    "type": "string",
                    "description": "Client name (required for create)"
                },
                "amount": {
                    "type": "number",
                    "description": "Invoice amount in USD (required for create)"
                },
                "status": {
                    "type": "string",
                    "enum": ["draft", "sent", "paid", "overdue"],
                    "description": "Invoice status"
                },
                "invoice_id": {
                    "type": "string",
                    "description": "Invoice ID (required for update_status)"
                }
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
]


# ═══════════════════════════════════════════════════════════════
# EMAIL TRIAGE IMPLEMENTATION
# ═══════════════════════════════════════════════════════════════

def _email_triage(max_emails: int = 20, auto_draft: bool = False, vip_senders: list = None) -> str:
    """Triage unread emails by urgency score and category."""
    if vip_senders is None:
        vip_senders = []

    HARDCODED_VIP = [
        "miles@<your-domain>",
        "info@openai.com",
        "support@github.com",
        "noreply@github.com",
    ]
    all_vip = HARDCODED_VIP + vip_senders

    try:
        cmd = ["gws", "gmail:v1", "+triage", "--max", str(max_emails), "--format", "json"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout
            if "No credentials found" in error_msg or "auth failed" in error_msg:
                return "⚠️  Gmail authentication not configured. Run `gws auth setup` to enable email triage."
            return f"Error calling gws: {error_msg[:500]}"

        try:
            emails = json.loads(result.stdout)
            if not emails:
                return "No unread emails found."
        except json.JSONDecodeError as e:
            return f"Error parsing gws output: {str(e)[:500]}"

        scored_emails = []
        for email in emails:
            sender = email.get("from", "unknown").lower()
            subject = email.get("subject", "").lower()

            score = 3
            if any(vip.lower() in sender for vip in all_vip):
                score = 10
            elif any(word in subject for word in ["urgent", "asap", "deadline", "payment", "invoice"]):
                score = 8
            elif any(word in subject for word in ["meeting", "review", "approval", "decision"]):
                score = 6
            elif any(word in subject for word in ["newsletter", "unsubscribe", "promotion", "discount", "sale"]):
                score = 1

            if score >= 9:
                category = "URGENT"
            elif score >= 7:
                category = "URGENT"
            elif score >= 5:
                category = "IMPORTANT"
            elif score >= 3:
                category = "NORMAL"
            else:
                category = "LOW"

            scored_emails.append({
                "from": email.get("from", "unknown"),
                "subject": email.get("subject", "(no subject)"),
                "date": email.get("date", ""),
                "snippet": email.get("snippet", "")[:100],
                "score": score,
                "category": category,
            })

        scored_emails.sort(key=lambda x: x["score"], reverse=True)

        lines = [f"Email Triage Report ({len(scored_emails)} unread emails):\n"]

        for category in ["URGENT", "IMPORTANT", "NORMAL", "LOW"]:
            category_emails = [e for e in scored_emails if e["category"] == category]
            if not category_emails:
                continue
            lines.append(f"\n[{category}] ({len(category_emails)} emails)")
            for email in category_emails:
                lines.append(f"  [{email['score']}/10] From: {email['from']} | Subject: {email['subject']}")
                if email.get("snippet"):
                    lines.append(f"           Preview: {email['snippet']}")

        if auto_draft:
            urgent_emails = [e for e in scored_emails if e["score"] >= 8][:3]
            if urgent_emails:
                lines.append("\n--- AUTO-DRAFTED REPLIES ---\n")
                for email in urgent_emails:
                    lines.append(f"To: {email['from']}")
                    lines.append(f"Subject: RE: {email['subject']}")
                    lines.append("Thanks for reaching out. I've received your message and will follow up shortly.")
                    lines.append("")

        return "\n".join(lines)

    except subprocess.TimeoutExpired:
        return "⏱️  Email triage timed out after 30s"
    except Exception as e:
        return f"Error in email_triage: {str(e)[:500]}"



def _process_document(file_path: str, doc_type: str = "general", extract_fields: bool = True) -> str:
    """
    Process documents (receipts, invoices, contracts) via OCR.
    Extracts text and optionally structured fields.
    """
    import os
    from pathlib import Path

    # Validate file exists
    if not os.path.exists(file_path):
        return json.dumps({
            "error": "File not found",
            "file_path": file_path
        })

    # Check file extension
    file_ext = Path(file_path).suffix.lower()
    supported_exts = {".pdf", ".png", ".jpg", ".jpeg", ".tiff"}
    if file_ext not in supported_exts:
        return json.dumps({
            "error": f"Unsupported file format: {file_ext}. Supported: {supported_exts}",
            "file_path": file_path
        })

    try:
        import pytesseract
        from PIL import Image
        from pdf2image import convert_from_path
    except ImportError as e:
        return json.dumps({
            "error": f"Missing OCR dependencies: {e}. Install: pip install pytesseract Pillow pdf2image",
            "note": "Also requires tesseract-ocr: apt-get install tesseract-ocr"
        })

    # Check if tesseract is installed
    try:
        pytesseract.pytesseract.get_tesseract_version()
    except Exception as e:
        return json.dumps({
            "error": f"Tesseract not installed or not found: {e}",
            "fix": "Run: apt-get install -y tesseract-ocr"
        })

    raw_text = ""
    page_count = 1

    try:
        # Handle PDF files
        if file_ext == ".pdf":
            try:
                pages = convert_from_path(file_path, dpi=150)
                page_count = len(pages)
                page_texts = []

                for i, page in enumerate(pages):
                    try:
                        text = pytesseract.image_to_string(page)
                        page_texts.append(text)
                    except Exception as e:
                        page_texts.append(f"[Error processing page {i+1}: {e}]")

                raw_text = "\n\n---PAGE BREAK---\n\n".join(page_texts)
            except Exception as e:
                return json.dumps({
                    "error": f"PDF conversion failed: {e}",
                    "note": "Ensure pdf2image is installed: pip install pdf2image"
                })

        # Handle image files
        else:
            try:
                image = Image.open(file_path)
                raw_text = pytesseract.image_to_string(image)
            except Exception as e:
                return json.dumps({
                    "error": f"Image OCR failed: {e}"
                })

        # Extract structured fields if requested
        extracted_fields = {}
        confidence_score = 0.5  # base confidence

        if extract_fields and raw_text:
            # Common patterns
            amount_pattern = r'\$?\s*(\d+\.?\d*)\s*(?:dollars?|usd|total|amount)?'
            date_pattern = r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})'

            # Receipt-specific extraction
            if doc_type == "receipt":
                # Find total amount
                amounts = re.findall(amount_pattern, raw_text, re.IGNORECASE)
                if amounts:
                    # Take last occurrence (usually total)
                    extracted_fields["total_amount"] = float(amounts[-1])
                    confidence_score += 0.2

                # Find date
                dates = re.findall(date_pattern, raw_text)
                if dates:
                    extracted_fields["date"] = f"{dates[0][0]}/{dates[0][1]}/{dates[0][2]}"
                    confidence_score += 0.1

                # Find vendor (first line with meaningful text)
                lines = [l.strip() for l in raw_text.split('\n') if l.strip() and len(l.strip()) > 3]
                if lines:
                    extracted_fields["vendor_name"] = lines[0][:100]  # First 100 chars
                    confidence_score += 0.15

                # Find items (lines with amounts)
                item_lines = []
                for line in lines[1:10]:  # Check first 10 lines
                    if any(char.isdigit() for char in line) and len(line) > 5:
                        item_lines.append(line[:80])

                if item_lines:
                    extracted_fields["items"] = item_lines
                    confidence_score += 0.1

            # Invoice-specific extraction
            elif doc_type == "invoice":
                # Find invoice number
                inv_match = re.search(r'invoice\s*#?:?\s*(\w+[-\w]*)', raw_text, re.IGNORECASE)
                if inv_match:
                    extracted_fields["invoice_number"] = inv_match.group(1)
                    confidence_score += 0.15

                # Find amounts
                amounts = re.findall(amount_pattern, raw_text, re.IGNORECASE)
                if amounts:
                    extracted_fields["amount"] = float(amounts[-1])
                    confidence_score += 0.2

                # Find dates
                dates = re.findall(date_pattern, raw_text)
                if dates:
                    extracted_fields["date"] = f"{dates[0][0]}/{dates[0][1]}/{dates[0][2]}"
                    confidence_score += 0.1
                    if len(dates) > 1:
                        extracted_fields["due_date"] = f"{dates[1][0]}/{dates[1][1]}/{dates[1][2]}"
                        confidence_score += 0.05

                # Find client name
                lines = [l.strip() for l in raw_text.split('\n') if l.strip() and len(l.strip()) > 3]
                if lines:
                    extracted_fields["client_name"] = lines[0][:100]
                    confidence_score += 0.15

            # Normalize confidence score to 0-1
            confidence_score = min(confidence_score, 1.0)

    except Exception as e:
        return json.dumps({
            "error": f"Unexpected error during document processing: {e}",
            "doc_type": doc_type,
            "file_path": file_path
        })

    result = {
        "status": "success",
        "file_path": file_path,
        "doc_type": doc_type,
        "page_count": page_count,
        "raw_text": raw_text[:2000],  # Limit output
        "raw_text_length": len(raw_text),
        "confidence_score": round(confidence_score, 2)
    }

    if extract_fields and extracted_fields:
        result["extracted_fields"] = extracted_fields

    return json.dumps(result, indent=2)

def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool and return the result as a string."""
    try:
        if tool_name == "github_repo_info":
            return _github_repo_info(tool_input["repo"], tool_input["action"])
        elif tool_name == "github_create_issue":
            return _github_create_issue(
                tool_input["repo"],
                tool_input["title"],
                tool_input.get("body", ""),
                tool_input.get("labels", [])
            )
        elif tool_name == "claude_code_build":
            return _claude_code_build(
                tool_input["repo_path"],
                tool_input["prompt"],
                tool_input.get("max_budget_usd", 2.0),
                tool_input.get("model", "sonnet"),
                tool_input.get("commit", False)
            )
        elif tool_name == "claude_code_github_issue":
            return _claude_code_github_issue(
                tool_input["repo"],
                tool_input["title"],
                tool_input["body"]
            )
        elif tool_name == "web_search":
            return _web_search(tool_input["query"])
        elif tool_name == "create_job":
            return _create_job(
                tool_input["project"],
                tool_input["task"],
                tool_input.get("priority", "P1")
            )
        elif tool_name == "list_jobs":
            return _list_jobs(tool_input.get("status", "all"))
        elif tool_name == "create_proposal":
            return _create_proposal_tool(
                tool_input["title"],
                tool_input["description"],
                tool_input.get("agent_pref", "project_manager"),
                tool_input.get("tags"),
                tool_input.get("priority", "P1")
            )
        elif tool_name == "get_cost_summary":
            return _get_cost_summary()
        elif tool_name == "approve_job":
            return _approve_job_tool(tool_input["job_id"])
        elif tool_name == "web_fetch":
            return _web_fetch(tool_input["url"], tool_input.get("extract", "text"))
        elif tool_name == "get_events":
            return _get_events(tool_input.get("limit", 10), tool_input.get("event_type"))
        elif tool_name == "save_memory":
            return _save_memory(
                tool_input["content"],
                tool_input.get("tags"),
                tool_input.get("importance", 5)
            )
        elif tool_name == "search_memory":
            return _search_memory(tool_input["query"], tool_input.get("limit", 5))
        elif tool_name == "rebuild_semantic_index":
            return _rebuild_semantic_index()
        elif tool_name == "flush_memory_before_compaction":
            return _flush_memory_before_compaction(tool_input.get("items", []))
        elif tool_name == "recall_memory":
            return _recall_memory(
                tool_input["query"],
                tool_input.get("limit", 5),
                tool_input.get("memory_sources"),
                tool_input.get("project"),
                tool_input.get("department")
            )
        elif tool_name == "send_slack_message":
            return _send_slack_message(tool_input["message"], tool_input.get("channel"))
        # ═ Email tools
        elif tool_name == "email_triage":
            return _email_triage(
                max_emails=tool_input.get("max_emails", 20),
                auto_draft=tool_input.get("auto_draft", False),
                vip_senders=tool_input.get("vip_senders", [])
            )
        # ═ SMS tools
        elif tool_name == "send_sms":
            return _send_sms(tool_input["to"], tool_input["body"])
        elif tool_name == "sms_history":
            return _get_sms_history(tool_input.get("direction", "all"), tool_input.get("limit", 10))
        # ═ Agency management tools
        elif tool_name == "kill_job":
            return _kill_job(tool_input["job_id"])
        elif tool_name == "agency_status":
            return _agency_status()
        elif tool_name == "manage_reactions":
            return _manage_reactions(tool_input["action"], tool_input.get("rule_id", ""), tool_input.get("rule_data"))
        # ═ Execution tools
        elif tool_name == "shell_execute":
            return _shell_execute(tool_input["command"], tool_input.get("cwd", "/root"), tool_input.get("timeout", 60))
        elif tool_name == "git_operations":
            return _git_operations(tool_input["action"], tool_input.get("repo_path", "."),
                                   tool_input.get("args", ""), tool_input.get("files", []))
        elif tool_name == "vercel_deploy":
            return _vercel_deploy(tool_input["action"], tool_input.get("project_path", ""),
                                  tool_input.get("project_name", ""), tool_input.get("env_key", ""),
                                  tool_input.get("env_value", ""), tool_input.get("production", True))
        elif tool_name == "file_read":
            return _file_read(tool_input["path"], tool_input.get("lines"), tool_input.get("offset", 0))
        elif tool_name == "file_write":
            return _file_write(tool_input["path"], tool_input["content"], tool_input.get("mode", "write"))
        elif tool_name == "install_package":
            return _install_package(tool_input["name"], tool_input["manager"], tool_input.get("global_install", True))
        elif tool_name == "research_task":
            return _research_task(tool_input["topic"], tool_input.get("depth", "medium"))
        elif tool_name == "web_scrape":
            return _web_scrape(tool_input["url"], tool_input.get("extract", "text"), tool_input.get("selector", ""))
        # ═ Code editing tools
        elif tool_name == "file_edit":
            return _file_edit(tool_input["path"], tool_input["old_string"], tool_input["new_string"],
                             tool_input.get("replace_all", False))
        elif tool_name == "glob_files":
            return _glob_files(tool_input["pattern"], tool_input.get("path", "/root"),
                              tool_input.get("max_results", 50))
        elif tool_name == "grep_search":
            return _grep_search(tool_input["pattern"], tool_input.get("path", "/root"),
                               tool_input.get("file_pattern", ""), tool_input.get("context_lines", 2),
                               tool_input.get("max_results", 20))
        elif tool_name == "process_manage":
            return _process_manage(tool_input["action"], tool_input.get("target", ""),
                                  tool_input.get("signal", "TERM"))
        elif tool_name == "env_manage":
            return _env_manage(tool_input["action"], tool_input.get("key", ""),
                              tool_input.get("value", ""), tool_input.get("env_file", "/root/.env"),
                              tool_input.get("filter", ""))
        # ═ Test tools
        elif tool_name == "auto_test":
            return _auto_test(tool_input["action"], tool_input["project_path"],
                             tool_input.get("framework", "auto"), tool_input.get("test_pattern"),
                             tool_input.get("error_output"), tool_input.get("test_file"))
        # ═ Compute tools
        elif tool_name == "compute_sort":
            return _compute_sort(tool_input["data"], tool_input.get("algorithm", "auto"),
                                tool_input.get("reverse", False), tool_input.get("key"))
        elif tool_name == "compute_stats":
            return _compute_stats(tool_input["data"], tool_input.get("percentiles"))
        elif tool_name == "compute_math":
            return _compute_math(tool_input["expression"], tool_input.get("precision", 10))
        elif tool_name == "compute_search":
            return _compute_search(tool_input["data"], tool_input.get("target"),
                                  tool_input.get("method", "linear"), tool_input.get("condition"))
        elif tool_name == "compute_matrix":
            return _compute_matrix(tool_input["action"], tool_input["matrix_a"],
                                  tool_input.get("matrix_b"))
        elif tool_name == "compute_prime":
            return _compute_prime(tool_input["action"], tool_input["n"], tool_input.get("limit"))
        elif tool_name == "compute_hash":
            return _compute_hash(tool_input.get("data", ""), tool_input.get("algorithm", "sha256"),
                                tool_input.get("file_path"))
        elif tool_name == "compute_convert":
            return _compute_convert(tool_input["value"], tool_input["from_unit"], tool_input["to_unit"])
        elif tool_name == "tmux_agents":
            return _tmux_agents(tool_input)
        elif tool_name == "security_scan":
            return _security_scan(tool_input["target"], tool_input.get("scan_type", "quick"),
                                  tool_input.get("agents"))
        elif tool_name == "prediction_market":
            return _prediction_market(tool_input["action"], tool_input.get("query", ""),
                                      tool_input.get("market_id", ""), tool_input.get("tag", ""),
                                      tool_input.get("limit", 10))
        elif tool_name == "polymarket_prices":
            from polymarket_trading import polymarket_prices
            return polymarket_prices(tool_input["action"], tool_input.get("market_id", ""),
                                     tool_input.get("token_id", ""), tool_input.get("interval", "1d"),
                                     tool_input.get("fidelity", 0))
        elif tool_name == "polymarket_monitor":
            from polymarket_trading import polymarket_monitor
            return polymarket_monitor(tool_input["action"], tool_input.get("market_id", ""),
                                      tool_input.get("condition_id", ""), tool_input.get("event_id", ""),
                                      tool_input.get("period", "week"), tool_input.get("order_by", "pnl"),
                                      tool_input.get("limit", 10))
        elif tool_name == "polymarket_portfolio":
            from polymarket_trading import polymarket_portfolio
            return polymarket_portfolio(tool_input["action"], tool_input.get("address", ""),
                                        tool_input.get("limit", 25))
        elif tool_name == "get_reflections":
            return _get_reflections(tool_input["action"], tool_input.get("task", ""),
                                    tool_input.get("project"), tool_input.get("limit", 5))
        elif tool_name == "create_event":
            return _create_event(tool_input["event_type"], tool_input.get("data", {}))
        elif tool_name == "plan_my_day":
            return _plan_my_day(tool_input.get("focus", "all"))
        elif tool_name == "morning_briefing":
            return _morning_briefing(tool_input.get("send_to_slack", True), tool_input.get("include_news", True))
        # ═ Perplexity research
        elif tool_name == "perplexity_research":
            return _perplexity_research(tool_input["query"], tool_input.get("model", "sonar"),
                                        tool_input.get("focus", "web"))
        # ═ News & Social Media tools
        elif tool_name == "read_ai_news":
            return _read_ai_news(tool_input.get("limit", 10), tool_input.get("source"), tool_input.get("hours", 24))
        elif tool_name == "read_tweets":
            return _read_tweets(tool_input.get("account"), tool_input.get("limit", 5))
        # ═ Trading Engine (Phase 2)
        elif tool_name == "kalshi_markets":
            from kalshi_trading import kalshi_markets
            return kalshi_markets(tool_input["action"], tool_input.get("ticker", ""),
                                  tool_input.get("query", ""), tool_input.get("event_ticker", ""),
                                  tool_input.get("status", ""), tool_input.get("limit", 20))
        elif tool_name == "kalshi_trade":
            from kalshi_trading import kalshi_trade
            return kalshi_trade(tool_input["action"], tool_input.get("ticker", ""),
                                tool_input.get("side", "yes"), tool_input.get("price", 0),
                                tool_input.get("count", 1), tool_input.get("order_id", ""),
                                tool_input.get("dry_run"))
        elif tool_name == "kalshi_portfolio":
            from kalshi_trading import kalshi_portfolio
            return kalshi_portfolio(tool_input["action"], tool_input.get("limit", 50))
        elif tool_name == "polymarket_trade":
            from polymarket_trading import polymarket_trade
            return polymarket_trade(tool_input["action"], tool_input.get("market_id", ""),
                                    tool_input.get("side", "yes"), tool_input.get("price", 0.0),
                                    tool_input.get("size", 0.0), tool_input.get("order_id", ""),
                                    tool_input.get("dry_run"))
        elif tool_name == "arb_scanner":
            from arb_scanner import arb_scan
            return arb_scan(tool_input["action"], tool_input.get("query", ""),
                            tool_input.get("min_edge", 0.02), tool_input.get("max_results", 10))
        elif tool_name == "money_engine":
            from money_engine import money_engine
            return money_engine(tool_input["action"], tool_input.get("params"))
        elif tool_name == "trading_strategies":
            from trading_strategies import trading_strategies
            return trading_strategies(tool_input["action"], tool_input.get("params"))
        elif tool_name == "trading_safety":
            from trading_safety import manage_safety
            return manage_safety(tool_input["action"], tool_input.get("config"))
        # ═ Betting Brain (Phase 4)
        elif tool_name == "betting_brain":
            from betting_brain import betting_brain
            return betting_brain(tool_input["action"], tool_input.get("params"))
        # ═ Sportsbook Odds + Betting Engine (Phase 3)
        elif tool_name == "sportsbook_odds":
            from sportsbook_odds import sportsbook_odds
            return sportsbook_odds(tool_input["action"], tool_input.get("sport", ""),
                                   tool_input.get("market", "h2h"), tool_input.get("bookmakers", ""),
                                   tool_input.get("event_id", ""), tool_input.get("limit", 10))
        elif tool_name == "sportsbook_arb":
            from sportsbook_odds import sportsbook_arb
            return sportsbook_arb(tool_input["action"], tool_input.get("sport", "basketball_nba"),
                                  tool_input.get("event_id", ""), tool_input.get("min_profit", 0.0),
                                  tool_input.get("min_ev", 0.01), tool_input.get("limit", 10))
        elif tool_name == "sports_predict":
            from sports_model import sports_predict
            return sports_predict(tool_input["action"], tool_input.get("sport", "nba"),
                                  tool_input.get("team", ""), tool_input.get("date", ""),
                                  tool_input.get("limit", 10))
        elif tool_name == "sports_betting":
            from sports_model import sports_betting
            return sports_betting(tool_input["action"], tool_input.get("sport", "nba"),
                                  tool_input.get("bankroll", 100.0), tool_input.get("min_ev", 0.01),
                                  tool_input.get("limit", 10))
        elif tool_name == "prediction_tracker":
            from prediction_tracker import prediction_tracker
            return prediction_tracker(tool_input["action"], tool_input.get("date", ""),
                                      tool_input.get("bankroll", 100.0))
        elif tool_name == "bet_tracker":
            from bet_tracker import bet_tracker
            return bet_tracker(tool_input["action"], tool_input.get("params", {}))
        # ═ Deep Research
        elif tool_name == "deep_research":
            from deep_research import deep_research
            return deep_research(tool_input["query"], tool_input.get("depth", "medium"),
                                 tool_input.get("mode", "general"),
                                 tool_input.get("max_sources", 0))
        # ═ Proposal Generator
        elif tool_name == "generate_proposal":
            from proposal_generator import generate_proposal
            return generate_proposal(
                business_name=tool_input["business_name"],
                business_type=tool_input["business_type"],
                owner_name=tool_input["owner_name"],
                selected_services=tool_input["selected_services"],
                custom_notes=tool_input.get("custom_notes", ""),
            )
        elif tool_name == "sales_call":
            import asyncio
            from sales_caller import call_lead
            result = asyncio.get_event_loop().run_until_complete(
                call_lead(
                    phone=tool_input["phone"],
                    business_name=tool_input["business_name"],
                    business_type=tool_input.get("business_type", "restaurant"),
                    owner_name=tool_input.get("owner_name", ""),
                )
            )
            if result.get("success"):
                return f"Call initiated to {result['business_name']} ({result['phone']}). Call ID: {result['call_id']}"
            return f"Call failed: {result.get('error', 'unknown error')}"
        # ═ Blackboard shared state
        elif tool_name == "blackboard_read":
            from blackboard import read as bb_read, list_by_project as bb_list
            key = tool_input.get("key", "")
            project = tool_input.get("project", "")
            if key:
                val = bb_read(key, project=project)
                return val if val else f"No entry found for key='{key}' project='{project}'"
            else:
                entries = bb_list(project)
                if not entries:
                    return f"No blackboard entries for project='{project}'"
                lines = [f"Blackboard entries for {project}:"]
                for e in entries[:10]:
                    lines.append(f"  {e['key']}: {e['value'][:200]}")
                return "\n".join(lines)
        elif tool_name == "blackboard_write":
            from blackboard import write as bb_write
            bb_write(
                key=tool_input["key"],
                value=tool_input["value"],
                project=tool_input.get("project", ""),
                ttl_seconds=tool_input.get("ttl_seconds", 604800),
            )
            return f"Written to blackboard: {tool_input['key']}"
        elif tool_name == "find_leads":
            import asyncio
            from lead_finder import find_leads
            leads = asyncio.get_event_loop().run_until_complete(
                find_leads(
                    business_type=tool_input.get("business_type", "restaurants"),
                    location=tool_input.get("location", "Flagstaff, AZ"),
                    limit=tool_input.get("limit", 10),
                    save=tool_input.get("save", True),
                )
            )
            if not leads:
                return "No leads found. Try a different business type or location."
            lines = [f"Found {len(leads)} leads:\n"]
            for l in leads:
                lines.append(f"• {l['business_name']} — {l.get('phone', 'no phone')} — {l.get('address', 'no address')}")
            return "\n".join(lines)
        # ═ PinchTab browser automation
        elif tool_name == "browser_navigate":
            return _pinchtab_navigate(tool_input["url"])
        elif tool_name == "browser_snapshot":
            return _pinchtab_snapshot()
        elif tool_name == "browser_action":
            return _pinchtab_action(tool_input["action"], tool_input["ref"], tool_input.get("value", ""))
        elif tool_name == "browser_text":
            return _pinchtab_text(tool_input.get("mode", "readability"))
        elif tool_name == "browser_screenshot":
            return _pinchtab_screenshot()
        elif tool_name == "browser_tabs":
            return _pinchtab_tabs(tool_input.get("action", "list"), tool_input.get("url", ""), tool_input.get("tab_id", ""))
        elif tool_name == "browser_evaluate":
            return _pinchtab_evaluate(tool_input["script"])
        # ═ Notion tools
        elif tool_name == "notion_search":
            return _notion_search(tool_input["query"], tool_input.get("limit", 10))
        elif tool_name == "notion_query":
            return _notion_query(tool_input["database_id"], tool_input.get("filter", ""),
                               tool_input.get("sorts", ""), tool_input.get("limit", 10))
        elif tool_name == "notion_create_page":
            return _notion_create_page(tool_input["database_id"], tool_input["properties"],
                                      tool_input.get("content", ""))
        elif tool_name == "notion_update_page":
            return _notion_update_page(tool_input["page_id"], tool_input["properties"])
        # ═ Claude Code Headless (Overseer only)
        elif tool_name == "claude_headless":
            return _claude_headless(tool_input)
        # ═ PC Dispatch tools
        elif tool_name == "dispatch_pc_code":
            return _dispatch_pc_code(tool_input["prompt"], tool_input.get("timeout", 300), tool_input.get("metadata"))
        elif tool_name == "dispatch_pc_ollama":
            return _dispatch_pc_ollama(tool_input["prompt"], tool_input.get("model"), tool_input.get("timeout", 300))
        elif tool_name == "check_pc_health":
            return _check_pc_health()
        elif tool_name == "get_dispatch_status":
            return _get_dispatch_status(tool_input["job_id"])
        elif tool_name == "list_dispatch_jobs":
            return _list_dispatch_jobs(tool_input.get("status"))
        # ═ Codex CLI (GPT-5) tools
        elif tool_name == "codex_build":
            return _codex_build(
                tool_input["repo_path"],
                tool_input["prompt"],
                tool_input.get("model", "gpt-5"),
                tool_input.get("sandbox", "workspace-write")
            )
        elif tool_name == "codex_query":
            return _codex_query(
                tool_input["prompt"],
                tool_input.get("model", "gpt-5")
            )
        elif tool_name == "codex_github_issue":
            return _codex_github_issue(
                tool_input["repo"],
                tool_input["title"],
                tool_input["body"]
            )
        elif tool_name == "propose_tool":
            return _propose_tool(
                tool_input["name"],
                tool_input["description"],
                tool_input["input_schema"],
                tool_input["implementation"],
                tool_input.get("category", "utility")
            )
        elif tool_name == "aider_build":
            return _aider_build(
                tool_input["repo_path"],
                tool_input["prompt"],
                tool_input.get("model", "gemini/gemini-2.5-flash")
            )
        elif tool_name == "gemini_cli_build":
            return _gemini_cli_build(
                tool_input["repo_path"],
                tool_input["prompt"]
            )
        elif tool_name == "goose_build":
            return _goose_build(
                tool_input["repo_path"],
                tool_input["prompt"]
            )
        elif tool_name == "opencode_build":
            return _opencode_build(
                tool_input["repo_path"],
                tool_input["prompt"]
            )
        # ═ Document processing (OCR)
        elif tool_name == "process_document":
            return _process_document(
                tool_input["file_path"],
                tool_input.get("doc_type", "general"),
                tool_input.get("extract_fields", True)
            )
        # ═ Financial tracking tools
        elif tool_name == "track_expense":
            return _track_expense(
                tool_input["amount"],
                tool_input["category"],
                tool_input["description"],
                tool_input.get("type", "expense"),
                tool_input.get("date")
            )
        elif tool_name == "financial_summary":
            return _financial_summary(tool_input.get("period", "month"))
        elif tool_name == "invoice_tracker":
            return _invoice_tracker(
                tool_input["action"],
                tool_input.get("client_name"),
                tool_input.get("amount"),
                tool_input.get("status"),
                tool_input.get("invoice_id")
            )
        else:
            return f"Unknown tool: {tool_name}"
    except Exception as e:
        logger.error(f"Tool execution error ({tool_name}): {e}")
        return f"Error: {str(e)}"


def _github_repo_info(repo: str, action: str) -> str:
    """Get GitHub repo info using gh CLI."""
    try:
        if action == "issues":
            result = subprocess.run(
                ["gh", "issue", "list", "--repo", repo, "--limit", "10", "--json", "number,title,state,labels"],
                capture_output=True, text=True, timeout=15
            )
        elif action == "prs":
            result = subprocess.run(
                ["gh", "pr", "list", "--repo", repo, "--limit", "10", "--json", "number,title,state,headRefName"],
                capture_output=True, text=True, timeout=15
            )
        elif action == "commits":
            result = subprocess.run(
                ["gh", "api", f"repos/{repo}/commits", "--jq", ".[0:5] | .[] | .sha[0:7] + \" \" + .commit.message[0:80]"],
                capture_output=True, text=True, timeout=15
            )
        else:  # status
            result = subprocess.run(
                ["gh", "repo", "view", repo, "--json", "name,description,stargazerCount,forkCount,defaultBranchRef,updatedAt"],
                capture_output=True, text=True, timeout=15
            )

        if result.returncode == 0:
            return result.stdout.strip() or "No results"
        else:
            return f"GitHub error: {result.stderr.strip()}"
    except FileNotFoundError:
        return "gh CLI not installed. Install with: curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg"
    except subprocess.TimeoutExpired:
        return "GitHub request timed out"


def _github_create_issue(repo: str, title: str, body: str, labels: list) -> str:
    """Create a GitHub issue."""
    try:
        cmd = ["gh", "issue", "create", "--repo", repo, "--title", title]
        if body:
            cmd.extend(["--body", body])
        if labels:
            cmd.extend(["--label", ",".join(labels)])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return f"Issue created: {result.stdout.strip()}"
        else:
            return f"Error: {result.stderr.strip()}"
    except Exception as e:
        return f"Error creating issue: {e}"


def _claude_code_build(repo_path: str, prompt: str, max_budget_usd: float = 2.0, model: str = "sonnet", commit: bool = False) -> str:
    """Run Claude Code headless to build features in a repo."""
    import json as _json
    try:
        if not os.path.isdir(repo_path):
            return f"Error: repo_path '{repo_path}' does not exist"
        max_budget_usd = min(max(max_budget_usd, 0.10), 10.0)
        model_name = "claude-opus-4-6" if model == "opus" else "claude-sonnet-4-6"

        full_prompt = prompt
        if commit:
            full_prompt += "\n\nAfter completing the work, commit the changes with a descriptive commit message."

        cmd = [
            "claude", "-p",
            "--output-format", "json",
            "--permission-mode", "acceptEdits",
            "--max-budget-usd", str(max_budget_usd),
            "--model", model_name,
            "--no-session-persistence",
            full_prompt,
        ]

        env = os.environ.copy()
        env.pop("CLAUDECODE", None)  # Allow nested execution

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
            cwd=repo_path, env=env
        )

        if result.returncode == 0 and result.stdout.strip():
            try:
                data = _json.loads(result.stdout.strip())
                output = data.get("result", result.stdout[:3000])
                cost = data.get("total_cost_usd", "unknown")
                duration = data.get("duration_ms", "unknown")
                return f"Claude Code completed.\nCost: ${cost}\nDuration: {duration}ms\nModel: {model_name}\n\nOutput:\n{output[:3000]}"
            except _json.JSONDecodeError:
                return f"Claude Code completed (raw):\n{result.stdout[:3000]}"
        else:
            stderr = result.stderr[:1000] if result.stderr else "no stderr"
            stdout = result.stdout[:1000] if result.stdout else "no stdout"
            return f"Claude Code failed (exit {result.returncode}):\nstderr: {stderr}\nstdout: {stdout}"
    except subprocess.TimeoutExpired:
        return "Error: Claude Code session timed out (10 min limit)"
    except Exception as e:
        return f"Error running Claude Code: {e}"


def _claude_code_github_issue(repo: str, title: str, body: str) -> str:
    """Create a GitHub issue with 'claude' label to trigger the Claude Code GitHub Action."""
    return _github_create_issue(repo, title, body, ["claude"])


# ═══════════════════════════════════════════════════════════════
# CODEX CLI (GPT-5) — Dual-AI Factory
# ═══════════════════════════════════════════════════════════════

def _codex_build(repo_path: str, prompt: str, model: str = "gpt-5", sandbox: str = "workspace-write") -> str:
    """Run Codex CLI headless to build features in a repo using GPT-5."""
    import json as _json
    try:
        if not os.path.isdir(repo_path):
            return f"Error: repo_path '{repo_path}' does not exist"
        output_file = f"/tmp/codex-output-{int(time.time())}.txt"
        cmd = [
            "codex", "exec",
            "--full-auto",
            "-m", model,
            "-s", sandbox,
            "-o", output_file,
            prompt,
        ]
        start = time.time()
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
            cwd=repo_path
        )
        duration = time.time() - start
        # Read output file
        output = ""
        if os.path.exists(output_file):
            with open(output_file) as f:
                output = f.read()[:4000]
            os.remove(output_file)
        if result.returncode == 0:
            if not output:
                output = result.stdout[:3000] if result.stdout else "Completed (no output captured)"
            return f"Codex (GPT-5) completed in {duration:.1f}s.\nModel: {model}\nSandbox: {sandbox}\n\nOutput:\n{output}"
        else:
            stderr = result.stderr[:1000] if result.stderr else "no stderr"
            return f"Codex failed (exit {result.returncode}, {duration:.1f}s):\n{stderr}\nstdout: {(result.stdout or '')[:500]}"
    except subprocess.TimeoutExpired:
        return "Error: Codex session timed out (10 min limit)"
    except FileNotFoundError:
        return "Error: codex CLI not installed. Install with: npm install -g @openai/codex"
    except Exception as e:
        return f"Error running Codex: {e}"


def _codex_query(prompt: str, model: str = "gpt-5") -> str:
    """Query GPT-5 for reasoning/analysis without file system access."""
    try:
        output_file = f"/tmp/codex-query-{int(time.time())}.txt"
        cmd = [
            "codex", "exec",
            "-s", "read-only",
            "-m", model,
            "-o", output_file,
            "--skip-git-repo-check",
            prompt,
        ]
        start = time.time()
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            cwd="/tmp"
        )
        duration = time.time() - start
        output = ""
        if os.path.exists(output_file):
            with open(output_file) as f:
                output = f.read()[:4000]
            os.remove(output_file)
        if not output:
            output = result.stdout[:3000] if result.stdout else "No output"
        return f"GPT-5 ({model}, {duration:.1f}s):\n{output}"
    except subprocess.TimeoutExpired:
        return "Error: GPT-5 query timed out (2 min limit)"
    except FileNotFoundError:
        return "Error: codex CLI not installed"
    except Exception as e:
        return f"Error querying GPT-5: {e}"


def _codex_github_issue(repo: str, title: str, body: str) -> str:
    """Create a GitHub issue with 'codex' label to trigger the Codex cron pipeline."""
    return _github_create_issue(repo, title, body, ["codex"])


def _web_search(query: str) -> str:
    """Web search using DuckDuckGo HTML (no API key needed)."""
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            resp = client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (compatible; OpenClaw/2.0)"}
            )

            if resp.status_code != 200:
                return f"Search failed: HTTP {resp.status_code}"

            # Parse results from HTML (simple extraction)
            text = resp.text
            results = []
            # Extract result snippets between result__snippet class
            import re
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', text, re.DOTALL)
            titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', text, re.DOTALL)
            urls = re.findall(r'class="result__url"[^>]*>(.*?)</a>', text, re.DOTALL)

            for i in range(min(5, len(titles))):
                title = re.sub(r'<[^>]+>', '', titles[i]).strip() if i < len(titles) else ""
                snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else ""
                url = re.sub(r'<[^>]+>', '', urls[i]).strip() if i < len(urls) else ""
                results.append(f"• {title}\n  {url}\n  {snippet}")

            return "\n\n".join(results) if results else "No results found"
    except Exception as e:
        return f"Search error: {e}"


def _create_job(project: str, task: str, priority: str) -> str:
    """Create a job in the queue."""
    from job_manager import create_job
    job = create_job(project, task, priority)
    return f"Job created: {job.id} | Project: {project} | Priority: {priority} | Task: {task}"


def _list_jobs(status: str) -> str:
    """List jobs from the queue."""
    from job_manager import list_jobs
    jobs = list_jobs(status=status)

    if not jobs:
        return "No jobs found"

    lines = []
    for j in jobs[-10:]:
        lines.append(f"• {j['id']} | {j['project']} | {j.get('status','?')} | {j['task'][:60]}")

    return "\n".join(lines)


def _create_proposal_tool(title: str, description: str, agent_pref: str = "project_manager",
                          tags: list = None, priority: str = "P1") -> str:
    """Create a proposal that goes through auto-approval."""
    from proposal_engine import create_proposal as _create_prop
    from approval_engine import auto_approve_and_execute
    tokens_est = 5000 if agent_pref in ("coder_agent", "hacker_agent") else 10000
    p = _create_prop(title, description, agent_pref, tokens_est, tags or [])
    result = auto_approve_and_execute(p.to_dict())
    return f"Proposal {p.id} created (cost: ${p.cost_est_usd:.4f}). Approval: {result.get('decision', {}).get('reason', 'pending')}"


def _get_cost_summary() -> str:
    """Get current API cost summary and budget status."""
    try:
        import requests as req
        resp = req.get("http://localhost:18789/api/costs/summary", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return json.dumps(data, indent=2)
        return f"Cost API returned {resp.status_code}"
    except Exception as e:
        return f"Error: {e}"


def _approve_job_tool(job_id: str) -> str:
    """Approve a job that's in pr_ready status for execution."""
    from job_manager import get_job, update_job_status
    job = get_job(job_id)
    if not job:
        return f"Job {job_id} not found"
    if job.get("status") != "pr_ready":
        return f"Job {job_id} is '{job.get('status')}', not ready for approval"
    update_job_status(job_id, "approved", approved_by="agent")
    return f"Job {job_id} approved for execution"


def _web_fetch(url: str, extract: str = "text") -> str:
    """Fetch content from a URL and return readable text."""
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; OpenClaw/2.0)"})
            if resp.status_code != 200:
                return f"HTTP {resp.status_code}"
            import re
            text = re.sub(r'<script[^>]*>.*?</script>', '', resp.text, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:3000]
    except Exception as e:
        return f"Fetch error: {e}"


def _get_events(limit: int = 10, event_type: str = None) -> str:
    """Get recent system events."""
    try:
        from event_engine import get_event_engine
        engine = get_event_engine()
        if not engine:
            return "Event engine not initialized"
        events = engine.get_recent_events(limit=limit, event_type=event_type)
        if not events:
            return "No recent events"
        lines = []
        for e in events:
            lines.append(f"[{e['timestamp'][:19]}] {e['event_type']}: {json.dumps(e.get('data', {}))[:100]}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def _sb_memory():
    """Lazy import supabase_client for memory operations."""
    try:
        from supabase_client import table_insert, table_select, is_connected
        return {"insert": table_insert, "select": table_select, "connected": is_connected}
    except Exception:
        return None


def _save_memory(content: str, tags: list = None, importance: int = 5) -> str:
    """Save to Supabase memories table, JSONL fallback."""
    import uuid
    mem_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()

    db_id = mem_id
    saved_to_supabase = False

    # Try Supabase first
    try:
        sb = _sb_memory()
        if sb and sb["connected"]():
            row = {
                "content": content,
                "importance": importance,
                "tags": tags or [],
                "created_at": now,
            }
            result = sb["insert"]("memories", row)
            if result:
                db_id = result[0].get("id", mem_id) if isinstance(result, list) else mem_id
                saved_to_supabase = True
    except Exception:
        pass

    # ALWAYS write to JSONL (semantic search indexes this file, not Supabase)
    mem_file = os.path.join(os.environ.get("OPENCLAW_DATA_DIR", "./data"), "memories.jsonl")
    os.makedirs(os.path.dirname(mem_file), exist_ok=True)
    record = {"id": str(db_id), "content": content, "tags": tags or [], "importance": importance,
              "timestamp": now}
    with open(mem_file, "a") as f:
        f.write(json.dumps(record) + "\n")

    # Invalidate semantic index so next search picks up new memory
    try:
        idx_file = os.path.join(os.environ.get("OPENCLAW_DATA_DIR", "./data"), "semantic_index.pkl")
        if os.path.exists(idx_file):
            os.remove(idx_file)
    except Exception:
        pass

    source = "supabase+jsonl" if saved_to_supabase else "jsonl"
    return f"Memory saved (id={db_id}, {source}): {content[:80]}"


def _search_memory(query: str, limit: int = 5) -> str:
    """Search memories using semantic search (meaning-based) + keyword fallback."""
    # Try semantic search first
    try:
        from semantic_memory import semantic_search
        results = semantic_search(query, limit)
        if results:
            lines = []
            for r in results:
                score_pct = int(r["score"] * 100)
                lines.append(f"[{r['id']}] (imp={r['importance']}, sim={score_pct}%) {r['source']}: {r['content'][:80]}")
            return f"Found {len(results)} semantic matches:\n" + "\n".join(lines)
    except Exception as e:
        logger.debug(f"Semantic search failed, falling back to keyword: {e}")

    # Fallback to keyword search (original logic)
    query_lower = query.lower()
    matches = []

    # Try Supabase first
    try:
        sb = _sb_memory()
        if sb and sb["connected"]():
            rows = sb["select"]("memories", "order=created_at.desc", limit=500)
            if rows:
                for m in rows:
                    content_str = m.get("content", "").lower()
                    tags_list = m.get("tags", []) or []
                    tags_str = " ".join(tags_list).lower()
                    if query_lower in content_str or query_lower in tags_str:
                        matches.append(m)
                matches.sort(key=lambda m: m.get("importance", 5), reverse=True)
                if not matches:
                    return f"No memories matching '{query}'"
                lines = [f"[{m.get('id','?')}] (imp={m.get('importance',5)}) {m['content'][:100]}" for m in matches[:limit]]
                return f"Found {len(matches)} memories:\n" + "\n".join(lines)
    except Exception:
        pass

    # JSONL fallback
    mem_file = os.path.join(os.environ.get("OPENCLAW_DATA_DIR", "./data"), "memories.jsonl")
    if not os.path.exists(mem_file):
        return "No memories found"
    with open(mem_file) as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                m = json.loads(line)
                content_str = m.get("content", "").lower()
                tags_str = " ".join(m.get("tags", [])).lower()
                if query_lower in content_str or query_lower in tags_str:
                    matches.append(m)
            except: continue
    matches.sort(key=lambda m: m.get("importance", 5), reverse=True)
    if not matches:
        return f"No memories matching '{query}'"
    lines = [f"[{m['id']}] (imp={m.get('importance',5)}) {m['content'][:100]}" for m in matches[:limit]]
    return f"Found {len(matches)} memories:\n" + "\n".join(lines)


def _rebuild_semantic_index() -> str:
    """Rebuild semantic memory search index."""
    try:
        from semantic_memory import rebuild_index
        rebuild_index()
        return "Semantic memory index rebuilt successfully"
    except ImportError:
        return "Semantic memory module not available"
    except Exception as e:
        return f"Error rebuilding semantic index: {e}"


def _flush_memory_before_compaction(items: list) -> str:
    """Flush pending items to MEMORY.md before context compaction."""
    try:
        from memory_compaction import flush_pending
        result = flush_pending(items)
        count = result.get("flushed_count", 0)
        return f"Flushed {count} items to MEMORY.md: {result.get('file', '?')}"
    except ImportError:
        return "Memory compaction module not available"
    except Exception as e:
        return f"Error flushing memory: {e}"


def _recall_memory(query: str, limit: int = 5, memory_sources: list = None, project: str = None, department: str = None) -> str:
    """Unified memory recall across all sources (semantic, reflexion, topics, supabase)."""
    try:
        from memory_recall import recall

        context = {}
        if project:
            context["project"] = project
        if department:
            context["department"] = department

        result = recall(
            query=query,
            limit=limit,
            memory_sources=memory_sources,
            context=context
        )

        # Format for readability
        lines = [f"Memory Recall: {result['summary']}"]

        if result.get("combined"):
            lines.append("\nTop Results:")
            for i, mem in enumerate(result["combined"][:limit], 1):
                source = mem.get("source_type", "unknown")
                score = mem.get("combined_score", 0)
                content = mem.get("content", "")[:150]
                lines.append(f"{i}. [{source}] (score: {score:.1%})")
                lines.append(f"   {content}")
        else:
            lines.append("No memories found")

        return "\n".join(lines)
    except ImportError:
        return "Memory recall module not available"
    except Exception as e:
        logger.error(f"Error in memory recall: {e}", exc_info=True)
        return f"Error recalling memory: {e}"


def _kill_job(job_id: str) -> str:
    """Cancel a running or pending job."""
    kill_flags_file = os.path.join(os.environ.get("OPENCLAW_DATA_DIR", "./data"), "jobs", "kill_flags.json")
    os.makedirs(os.path.dirname(kill_flags_file), exist_ok=True)
    flags = {}
    if os.path.exists(kill_flags_file):
        with open(kill_flags_file) as f:
            flags = json.load(f)
    flags[job_id] = {"killed_at": datetime.now(timezone.utc).isoformat(), "reason": "manual"}
    with open(kill_flags_file, "w") as f:
        json.dump(flags, f)
    # Try to kill tmux pane
    subprocess.run(["tmux", "kill-window", "-t", f"job-{job_id}"], capture_output=True)
    try:
        from job_manager import update_job_status
        update_job_status(job_id, "cancelled")
    except Exception:
        pass
    return f"Kill flag set for job {job_id}"


def _agency_status() -> str:
    """Get combined agency overview."""
    parts = []
    # Active jobs
    try:
        from job_manager import list_jobs as lj
        jobs = lj(status="all")
        active = [j for j in jobs if j.get("status") in ("analyzing", "running", "pending")]
        recent_done = [j for j in jobs if j.get("status") == "done"][-5:]
        parts.append(f"Active jobs: {len(active)}")
        for j in active:
            parts.append(f"  [{j.get('status')}] {j['id'][:8]}: {j.get('task', '')[:60]}")
        parts.append(f"\nRecent completed: {len(recent_done)}")
        for j in recent_done:
            parts.append(f"  {j['id'][:8]}: {j.get('task', '')[:60]}")
    except Exception as e:
        parts.append(f"Jobs: error - {e}")
    # Costs
    try:
        from cost_tracker import get_cost_metrics
        costs = get_cost_metrics()
        parts.append(f"\nCosts today: ${costs.get('today_usd', 0):.4f}")
        parts.append(f"Costs this month: ${costs.get('month_usd', 0):.4f}")
    except Exception:
        pass
    # Tmux agents
    try:
        result = subprocess.run(["tmux", "list-windows", "-t", "openclaw", "-F", "#{window_name}"],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            windows = [w for w in result.stdout.strip().split("\n") if w]
            parts.append(f"\nActive tmux agents: {len(windows)}")
            for w in windows[:10]:
                parts.append(f"  {w}")
    except Exception:
        pass
    # 7-day performance (computed from jobs.jsonl — source of truth)
    try:
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y%m%d")
        recent_all = [j for j in jobs if j.get("id", "")[4:12] >= cutoff]
        terminal = [j for j in recent_all if j.get("status") in ("done", "failed", "killed_iteration_limit", "killed_cost_limit", "killed_timeout")]
        successes = sum(1 for j in terminal if j.get("status") == "done")
        failures = len(terminal) - successes
        rate = round(successes / len(terminal) * 100, 1) if terminal else 0
        parts.append(f"\n7-day performance: {rate}% success ({successes}/{len(terminal)} jobs)")
        if failures > 0:
            fail_types = {}
            for j in terminal:
                if j.get("status") != "done":
                    s = j.get("status", "unknown")
                    fail_types[s] = fail_types.get(s, 0) + 1
            parts.append(f"  Failures: {fail_types}")
    except Exception as e:
        parts.append(f"\n7-day performance: error - {e}")
    return "\n".join(parts)


def _manage_reactions(action: str, rule_id: str = "", rule_data: dict = None) -> str:
    """Manage auto-reaction rules."""
    try:
        from reactions import get_reactions_engine
        engine = get_reactions_engine()
        if action == "list":
            rules = engine.get_rules()
            return json.dumps(rules, indent=2)
        elif action == "triggers":
            triggers = engine.get_recent_triggers()
            return json.dumps(triggers, indent=2)
        elif action == "add":
            if not rule_data:
                return "Error: rule_data required"
            new_id = engine.add_rule(rule_data)
            return f"Rule added: {new_id}"
        elif action == "update":
            if not rule_id or not rule_data:
                return "Error: rule_id and rule_data required"
            engine.update_rule(rule_id, rule_data)
            return f"Rule {rule_id} updated"
        elif action == "delete":
            if not rule_id:
                return "Error: rule_id required"
            engine.delete_rule(rule_id)
            return f"Rule {rule_id} deleted"
        return f"Unknown action: {action}"
    except Exception as e:
        return f"Error: {e}"


def _send_slack_message(message: str, channel: str = None) -> str:
    """Send a message to a Slack channel."""
    try:
        import requests as req
        channel = channel or os.getenv("SLACK_REPORT_CHANNEL", "C0AFE4QHKH7")
        token = os.getenv("GATEWAY_AUTH_TOKEN", "")
        resp = req.post(
            "http://localhost:18789/slack/report/send",
            json={"text": message, "channel": channel},
            headers={"X-Auth-Token": token},
            timeout=10
        )
        return f"Message sent to Slack ({resp.status_code})"
    except Exception as e:
        return f"Error: {e}"


# ═══════════════════════════════════════════════════════════════════════════
# SMS TOOLS — Twilio send/receive
# ═══════════════════════════════════════════════════════════════════════════

# Rate limiter: track sends per hour
_sms_send_log: list[float] = []
_SMS_RATE_LIMIT = 10  # max sends per hour
_SMS_LOG_FILE = os.path.join(os.getenv("DATA_DIR", "./data"), "sms_log.jsonl")

# Shared in-memory inbox for received SMS — gateway appends here on each inbound Twilio webhook.
# Agents can read it via the sms_history tool. maxlen=100 caps memory usage.
received_sms_inbox: deque = deque(maxlen=100)


def _send_sms(to: str, body: str) -> str:
    """Send an SMS via Twilio with rate limiting."""
    import re as regex
    # Validate E.164 format
    if not regex.match(r'^\+[1-9]\d{1,14}$', to):
        return f"Error: Invalid phone number '{to}'. Must be E.164 format (e.g. +15551234567)"

    if len(body) > 1600:
        return f"Error: Message too long ({len(body)} chars). Max is 1600."

    # Check rate limit
    now = time.time()
    _sms_send_log[:] = [t for t in _sms_send_log if now - t < 3600]
    if len(_sms_send_log) >= _SMS_RATE_LIMIT:
        return f"Rate limited: {len(_sms_send_log)}/{_SMS_RATE_LIMIT} SMS sent in the last hour. Try again later."

    # Check Twilio credentials
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_PHONE_NUMBER")

    if not all([account_sid, auth_token, from_number]):
        missing = []
        if not account_sid: missing.append("TWILIO_ACCOUNT_SID")
        if not auth_token: missing.append("TWILIO_AUTH_TOKEN")
        if not from_number: missing.append("TWILIO_PHONE_NUMBER")
        return f"Error: Missing Twilio credentials: {', '.join(missing)}. Set them in .env"

    try:
        # Call Twilio Messages REST API directly via httpx (no SDK required)
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        resp = httpx.post(
            url,
            data={"To": to, "From": from_number, "Body": body},
            auth=(account_sid, auth_token),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        _sms_send_log.append(now)

        # Log to file
        _log_sms("sent", to, from_number, body, data.get("sid", ""))

        return f"SMS sent to {to} (SID: {data.get('sid', '?')}, status: {data.get('status', '?')})"
    except httpx.HTTPStatusError as e:
        error_body = e.response.text[:200]
        return f"Error sending SMS (HTTP {e.response.status_code}): {error_body}"
    except Exception as e:
        return f"Error sending SMS: {e}"


def _get_sms_history(direction: str = "all", limit: int = 10) -> str:
    """Get recent SMS history from log file."""
    try:
        if not os.path.exists(_SMS_LOG_FILE):
            return "No SMS history yet."

        messages = []
        with open(_SMS_LOG_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        msg = json.loads(line)
                        if direction == "all" or msg.get("direction") == direction:
                            messages.append(msg)
                    except json.JSONDecodeError:
                        pass

        # Return most recent
        messages = messages[-limit:]
        if not messages:
            return f"No {direction} SMS messages found."

        lines = [f"SMS History ({len(messages)} messages):"]
        for msg in messages:
            ts = msg.get("timestamp", "?")
            d = msg.get("direction", "?")
            frm = msg.get("from", "?")
            to = msg.get("to", "?")
            body = msg.get("body", "")[:100]
            lines.append(f"  [{ts}] {d.upper()} {frm} → {to}: {body}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading SMS history: {e}"


def _log_sms(direction: str, to: str, from_num: str, body: str, sid: str = ""):
    """Append SMS to log file and, for received messages, to the in-memory inbox deque."""
    try:
        os.makedirs(os.path.dirname(_SMS_LOG_FILE), exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "direction": direction,
            "from": from_num,
            "to": to,
            "body": body,
            "sid": sid,
        }
        with open(_SMS_LOG_FILE, 'a') as f:
            f.write(json.dumps(entry) + "\n")
        # Mirror received messages into the shared in-memory deque so agents can
        # query the inbox without re-reading the log file every time.
        if direction == "received":
            received_sms_inbox.appendleft(entry)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# EXECUTION TOOLS — Shell, Git, Vercel, File I/O, Packages, Research
# ═══════════════════════════════════════════════════════════════════════════

def _is_command_safe(command: str) -> tuple[bool, str]:
    """Check if a command is safe to execute."""
    cmd_lower = command.strip().lower()

    # Check blocked commands (substring match)
    for blocked in BLOCKED_COMMANDS:
        if blocked in cmd_lower:
            return False, f"BLOCKED: '{blocked}' is not allowed"

    # Check for dangerous subshell / backtick injection patterns
    for pattern in _DANGEROUS_SUBSHELL_PATTERNS:
        if pattern.search(command):
            return False, "BLOCKED: dangerous subshell/backtick injection detected"

    # Check if starts with a safe prefix
    for prefix in SAFE_COMMAND_PREFIXES:
        if cmd_lower.startswith(prefix.lower()) or cmd_lower == prefix.strip():
            return True, "OK"

    # Allow piped commands if each segment is safe
    if "|" in command:
        parts = [p.strip() for p in command.split("|")]
        for part in parts:
            safe, reason = _is_command_safe(part)
            if not safe:
                return False, f"Pipe segment blocked: {reason}"
        return True, "OK (piped)"

    # Allow chained commands (&&, ;)
    for sep in ["&&", ";"]:
        if sep in command:
            parts = [p.strip() for p in command.split(sep)]
            for part in parts:
                safe, reason = _is_command_safe(part)
                if not safe:
                    return False, f"Chained segment blocked: {reason}"
            return True, "OK (chained)"

    return False, f"Command not in allowlist. Allowed prefixes: git, npm, python3, node, curl, vercel, docker, etc."


# Paths that must NEVER be written to by agents (even if inside ALLOWED_WRITE_DIRS)
BLOCKED_WRITE_PATHS = [
    "/etc/",                # System configs
    "/root/.ssh/",          # SSH keys
    "/root/.ssh",           # SSH dir itself
    "/root/.env",           # Environment secrets (edit manually only)
    "/root/.bashrc",        # Shell config
    "/root/.profile",       # Shell config
]

# Path components that block writes when found anywhere in the path
BLOCKED_PATH_COMPONENTS = [
    "/.git/",               # Git internals (objects, hooks, config)
    "/.env",                # Dotenv files anywhere
]


def _is_path_writable(path: str) -> bool:
    """Check if path is in allowed write directories and not in blocked paths."""
    abs_path = os.path.abspath(path)

    # Check blocked paths (exact prefix match)
    for blocked in BLOCKED_WRITE_PATHS:
        if abs_path == blocked.rstrip("/") or abs_path.startswith(blocked):
            return False

    # Check blocked path components (substring match)
    for component in BLOCKED_PATH_COMPONENTS:
        if component in abs_path:
            return False

    return any(abs_path.startswith(d) for d in ALLOWED_WRITE_DIRS)


def _shell_execute(command: str, cwd: str = "/root", timeout: int = 60) -> str:
    """Execute a sandboxed shell command."""
    # Sanitize cwd
    if "\x00" in cwd:
        return "⛔ Command rejected: null byte in working directory path"
    cwd = os.path.realpath(os.path.abspath(cwd))
    if not os.path.isdir(cwd):
        return f"⛔ Working directory does not exist: {cwd}"

    safe, reason = _is_command_safe(command)
    if not safe:
        return f"⛔ Command rejected: {reason}"

    timeout = min(timeout, 300)  # Max 5 minutes

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd,
            env={**os.environ, "PATH": f"/usr/local/bin:/usr/bin:/bin:/root/.bun/bin:/root/.local/bin:{os.environ.get('PATH', '')}"}
        )
        output = ""
        if result.stdout:
            output += result.stdout[:MAX_SHELL_OUTPUT]
        if result.stderr:
            output += f"\n[STDERR]: {result.stderr[:2000]}"
        output += f"\n[EXIT CODE]: {result.returncode}"
        return output.strip() or "[No output]"
    except subprocess.TimeoutExpired:
        return f"⏱️ Command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


def _git_operations(action: str, repo_path: str = ".", args: str = "", files: list = None) -> str:
    """Perform git operations."""
    if not os.path.isdir(repo_path):
        return f"Directory not found: {repo_path}"

    try:
        if action == "status":
            cmd = ["git", "status", "--short"]
        elif action == "add":
            if files:
                cmd = ["git", "add"] + files
            elif args:
                cmd = ["git", "add"] + args.split()
            else:
                cmd = ["git", "add", "-A"]
        elif action == "commit":
            if not args:
                return "Error: commit message required in 'args'"
            cmd = ["git", "commit", "-m", f"{args}\n\nCo-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"]
        elif action == "push":
            remote = args.split()[0] if args else "origin"
            branch = args.split()[1] if args and len(args.split()) > 1 else "main"
            cmd = ["git", "push", remote, branch]
        elif action == "pull":
            cmd = ["git", "pull"] + (args.split() if args else [])
        elif action == "branch":
            if args:
                cmd = ["git", "checkout", "-b", args]
            else:
                cmd = ["git", "branch", "-a"]
        elif action == "log":
            count = args if args else "10"
            cmd = ["git", "log", f"--oneline", f"-{count}"]
        elif action == "diff":
            cmd = ["git", "diff"] + (args.split() if args else [])
        elif action == "clone":
            if not args:
                return "Error: repository URL required in 'args'"
            cmd = ["git", "clone", args]
        elif action == "checkout":
            if not args:
                return "Error: branch name required in 'args'"
            cmd = ["git", "checkout", args]
        else:
            return f"Unknown git action: {action}"

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=repo_path)
        output = result.stdout.strip()
        if result.stderr:
            output += f"\n{result.stderr.strip()}"
        return output or f"git {action}: done"
    except subprocess.TimeoutExpired:
        return f"git {action} timed out"
    except Exception as e:
        return f"git error: {e}"


def _vercel_deploy(action: str, project_path: str = "", project_name: str = "",
                   env_key: str = "", env_value: str = "", production: bool = True) -> str:
    """Vercel deployment operations."""
    vercel_token = os.getenv("VERCEL_TOKEN", "")

    try:
        # Check if vercel CLI is available
        if not shutil.which("vercel"):
            # Try to install it
            result = subprocess.run(["npm", "install", "-g", "vercel"], capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                return "Vercel CLI not installed. Install with: npm install -g vercel"

        if action == "deploy":
            if not project_path:
                return "Error: project_path required for deploy"
            cmd = ["vercel", "deploy", "--yes"]
            if production:
                cmd.append("--prod")
            if vercel_token:
                cmd.extend(["--token", vercel_token])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=project_path)
            output = result.stdout.strip() + ("\n" + result.stderr.strip() if result.stderr else "")
            # Emit deploy event for auto-reactions (security scan, notifications)
            if result.returncode == 0:
                try:
                    from event_engine import get_event_engine
                    deploy_url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
                    get_event_engine().emit("deploy.complete", {
                        "project": os.path.basename(project_path),
                        "url": deploy_url,
                        "env": "production" if production else "preview",
                    })
                except Exception:
                    pass  # don't fail deploy over event emission
            return output

        elif action == "list":
            cmd = ["vercel", "ls"]
            if vercel_token:
                cmd.extend(["--token", vercel_token])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.stdout.strip()[:3000]

        elif action == "env-set":
            if not env_key or not env_value:
                return "Error: env_key and env_value required"
            # Safe: use Popen pipe instead of shell=True to avoid shell injection
            vercel_cmd = ["vercel", "env", "add", env_key, "production", "--force"]
            if vercel_token:
                vercel_cmd.extend(["--token", vercel_token])
            echo_proc = subprocess.Popen(
                ["printf", "%s", env_value], stdout=subprocess.PIPE
            )
            result = subprocess.run(
                vercel_cmd, stdin=echo_proc.stdout,
                capture_output=True, text=True, timeout=30
            )
            echo_proc.stdout.close()
            echo_proc.wait()
            return result.stdout.strip() or f"Env var {env_key} set"

        elif action == "status":
            name = project_name or "current project"
            cmd = ["vercel", "inspect"]
            if vercel_token:
                cmd.extend(["--token", vercel_token])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.stdout.strip()[:2000]

        elif action == "logs":
            cmd = ["vercel", "logs"]
            if project_name:
                cmd.append(project_name)
            if vercel_token:
                cmd.extend(["--token", vercel_token])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.stdout.strip()[:3000]

        return f"Unknown vercel action: {action}"
    except subprocess.TimeoutExpired:
        return f"Vercel {action} timed out"
    except Exception as e:
        return f"Vercel error: {e}"


# Paths agents should never read (secrets, SSH keys, etc.)
BLOCKED_READ_PATHS = [
    "/root/.ssh/",
    "/root/.env",
    "/etc/shadow",
]


def _file_read(path: str, lines: int = None, offset: int = 0) -> str:
    """Read file contents with optional line limits."""
    try:
        abs_path, err = _sanitize_path(path)
        if err:
            return f"⛔ {err}"
        # Block reading sensitive files
        for blocked in BLOCKED_READ_PATHS:
            if abs_path == blocked.rstrip("/") or abs_path.startswith(blocked):
                return f"⛔ Access denied: reading {path} is not permitted"
        if not os.path.exists(abs_path):
            return f"File not found: {path}"
        if os.path.isdir(abs_path):
            entries = os.listdir(abs_path)
            return f"Directory listing ({len(entries)} items):\n" + "\n".join(entries[:100])
        if os.path.getsize(abs_path) > MAX_FILE_READ * 4:
            return f"File too large ({os.path.getsize(abs_path)} bytes). Use 'lines' parameter to read a portion."

        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

        if offset:
            all_lines = all_lines[offset:]
        if lines:
            all_lines = all_lines[:min(lines, 500)]

        content = "".join(all_lines)
        if len(content) > MAX_FILE_READ:
            content = content[:MAX_FILE_READ] + f"\n... [truncated at {MAX_FILE_READ} chars]"
        return content
    except Exception as e:
        return f"Error reading file: {e}"


def _sanitize_path(path: str) -> tuple[str, str | None]:
    """Sanitize a file path. Returns (abs_path, error_msg_or_None)."""
    # Block null bytes (can truncate paths in C-based libs)
    if "\x00" in path:
        return "", "BLOCKED: null byte in path"
    # Resolve to absolute, collapsing any ../
    abs_path = os.path.realpath(os.path.abspath(path))
    return abs_path, None


def _file_write(path: str, content: str, mode: str = "write") -> str:
    """Write or append to a file."""
    try:
        abs_path, err = _sanitize_path(path)
        if err:
            return f"⛔ {err}"
        if not _is_path_writable(abs_path):
            return f"⛔ Path not writable: {path}. Allowed dirs: {', '.join(ALLOWED_WRITE_DIRS)}"

        # Ensure parent directory exists
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        file_mode = "a" if mode == "append" else "w"
        with open(abs_path, file_mode, encoding="utf-8") as f:
            f.write(content)

        size = os.path.getsize(abs_path)
        return f"✅ Written to {path} ({size} bytes, mode={mode})"
    except Exception as e:
        return f"Error writing file: {e}"


def _install_package(name: str, manager: str, global_install: bool = True) -> str:
    """Install a package using the specified manager."""
    try:
        # Check if already installed
        if manager in ("npm", "binary"):
            check = shutil.which(name)
            if check:
                return f"✅ {name} already installed at {check}"

        if manager == "npm":
            cmd = ["npm", "install"]
            if global_install:
                cmd.append("-g")
            cmd.append(name)
        elif manager == "pip":
            cmd = ["pip3", "install", "--break-system-packages", name]
        elif manager == "apt":
            cmd = ["apt-get", "install", "-y", name]
        elif manager == "binary":
            return f"Binary install not implemented for {name}. Use shell_execute with curl."
        else:
            return f"Unknown package manager: {manager}"

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        output = result.stdout.strip()[-1000:]
        if result.returncode != 0:
            output += f"\n[ERROR]: {result.stderr.strip()[-500:]}"
        return output or f"✅ {name} installed via {manager}"
    except subprocess.TimeoutExpired:
        return f"Install timed out for {name}"
    except Exception as e:
        return f"Install error: {e}"


def _research_task(topic: str, depth: str = "medium") -> str:
    """Research a topic by searching the web and fetching relevant pages."""
    results = []

    # Step 1: Web search
    search_result = _web_search(topic)
    results.append(f"=== SEARCH RESULTS ===\n{search_result}")

    if depth in ("medium", "deep"):
        # Step 2: Also search for code examples / tutorials
        code_search = _web_search(f"{topic} tutorial example code 2026")
        results.append(f"\n=== CODE/TUTORIAL SEARCH ===\n{code_search}")

    if depth == "deep":
        # Step 3: Search for best practices and common issues
        best_practices = _web_search(f"{topic} best practices common issues pitfalls")
        results.append(f"\n=== BEST PRACTICES ===\n{best_practices}")

        # Step 4: Search for official documentation
        docs_search = _web_search(f"{topic} official documentation API reference")
        results.append(f"\n=== OFFICIAL DOCS ===\n{docs_search}")

    # Try to fetch the first URL from search results
    import re
    urls = re.findall(r'https?://\S+', search_result)
    if urls and depth in ("medium", "deep"):
        first_url = urls[0].rstrip(')')
        fetched = _web_fetch(first_url, "text")
        results.append(f"\n=== FETCHED: {first_url} ===\n{fetched[:2000]}")

    return "\n".join(results)


def _web_scrape(url: str, extract: str = "text", selector: str = "") -> str:
    """Scrape structured data from a webpage."""
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; OpenClaw/2.0)"})
            if resp.status_code != 200:
                return f"HTTP {resp.status_code}"

            import re
            html = resp.text

            if extract == "links":
                links = re.findall(r'href=["\']([^"\']+)["\']', html)
                unique_links = list(dict.fromkeys(links))[:50]
                return "\n".join(unique_links)

            elif extract == "headings":
                headings = re.findall(r'<h[1-6][^>]*>(.*?)</h[1-6]>', html, re.DOTALL | re.IGNORECASE)
                clean = [re.sub(r'<[^>]+>', '', h).strip() for h in headings]
                return "\n".join(clean) if clean else "No headings found"

            elif extract == "code":
                # Extract code blocks
                code_blocks = re.findall(r'<code[^>]*>(.*?)</code>', html, re.DOTALL)
                pre_blocks = re.findall(r'<pre[^>]*>(.*?)</pre>', html, re.DOTALL)
                all_code = code_blocks + pre_blocks
                clean = [re.sub(r'<[^>]+>', '', c).strip() for c in all_code]
                return "\n---\n".join(clean[:20]) if clean else "No code blocks found"

            elif extract == "tables":
                tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL | re.IGNORECASE)
                result = []
                for table in tables[:5]:
                    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table, re.DOTALL | re.IGNORECASE)
                    for row in rows:
                        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL | re.IGNORECASE)
                        clean_cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                        result.append(" | ".join(clean_cells))
                    result.append("---")
                return "\n".join(result) if result else "No tables found"

            else:  # text or all
                # Remove script/style
                text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
                text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)

                if selector and extract == "all":
                    # Try to find elements matching a simple class/id selector
                    if selector.startswith("."):
                        pattern = rf'class=["\'][^"\']*{re.escape(selector[1:])}[^"\']*["\'][^>]*>(.*?)</'
                    elif selector.startswith("#"):
                        pattern = rf'id=["\'][^"\']*{re.escape(selector[1:])}[^"\']*["\'][^>]*>(.*?)</'
                    else:
                        pattern = rf'<{re.escape(selector)}[^>]*>(.*?)</{re.escape(selector)}>'
                    matches = re.findall(pattern, text, re.DOTALL)
                    if matches:
                        clean = [re.sub(r'<[^>]+>', ' ', m).strip() for m in matches[:20]]
                        return "\n".join(clean)

                text = re.sub(r'<[^>]+>', ' ', text)
                text = re.sub(r'\s+', ' ', text).strip()
                return text[:5000]

    except Exception as e:
        return f"Scrape error: {e}"


# ═══════════════════════════════════════════════════════════════════════════
# CODE EDITING TOOLS — Edit, Glob, Grep, Process, Env
# ═══════════════════════════════════════════════════════════════════════════

def _file_edit(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """Find and replace a string in a file (surgical edit, not overwrite)."""
    try:
        abs_path, err = _sanitize_path(path)
        if err:
            return f"⛔ {err}"
        if not os.path.exists(abs_path):
            return f"File not found: {path}"
        if not _is_path_writable(abs_path):
            return f"⛔ Path not writable: {path}"

        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()

        if old_string not in content:
            return f"⛔ String not found in {path}. Make sure old_string matches exactly (including whitespace/indentation)."

        if not replace_all:
            count = content.count(old_string)
            if count > 1:
                return f"⛔ Found {count} occurrences of old_string — must be unique. Add more context to make it unique, or set replace_all=true."
            new_content = content.replace(old_string, new_string, 1)
        else:
            count = content.count(old_string)
            new_content = content.replace(old_string, new_string)

        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        # Return diff-aware result if available (shows only changed lines)
        if HAS_DIFF_VIEW:
            return format_edit_result(path, content, new_content, success=True)

        replaced = content.count(old_string) if replace_all else 1
        return f"✅ Edited {path}: replaced {replaced} occurrence(s) ({len(new_content)} bytes written)"
    except Exception as e:
        return f"Edit error: {e}"


def _glob_files(pattern: str, path: str = "/root", max_results: int = 50) -> str:
    """Find files matching a glob pattern using subprocess find for performance."""
    import fnmatch as _fnmatch
    import subprocess as _sp

    try:
        # Skip directories that produce massive results
        skip_dirs = {"node_modules", ".git", "__pycache__", ".next", "dist", "build", ".cache", ".worktrees"}

        # Extract the filename pattern from the glob (e.g. "**/*.py" -> "*.py")
        # Use 'find' with -prune to avoid walking into huge dirs
        parts = pattern.replace("\\", "/").split("/")
        name_pattern = parts[-1] if parts else pattern

        # Build find command with prune for skip dirs
        prune_args = []
        for d in skip_dirs:
            prune_args.extend(["-name", d, "-o"])
        # Remove trailing -o
        if prune_args:
            prune_args = prune_args[:-1]

        # find <path> ( -name node_modules -o -name .git ... ) -prune -o -name "*.py" -type f -print
        cmd = ["find", path, "("] + prune_args + [")", "-prune", "-o",
               "-name", name_pattern, "-type", "f", "-print"]

        result = _sp.run(cmd, capture_output=True, text=True, timeout=10)
        all_files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]

        # If pattern had directory components (e.g. "src/**/*.ts"), filter by full glob
        if len(parts) > 1 and parts[0] != "**":
            import glob as glob_mod
            full_pattern = os.path.join(path, pattern)
            all_files = [f for f in all_files if glob_mod.fnmatch.fnmatch(f, full_pattern)]

        matches = all_files[:max_results * 5]  # cap before sorting

        if not matches:
            return f"No files matching '{pattern}' in {path}"

        # Sort by modification time (newest first) — only on the capped list
        matches.sort(key=lambda f: os.path.getmtime(f) if os.path.exists(f) else 0, reverse=True)
        matches = matches[:max_results]

        lines = []
        for m in matches:
            try:
                size = os.path.getsize(m)
                mtime = os.path.getmtime(m)
                from datetime import datetime
                dt = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                size_str = f"{size:>8,}" if size < 1_000_000 else f"{size/1_000_000:.1f}M"
                lines.append(f"{size_str}  {dt}  {m}")
            except Exception:
                lines.append(f"           {m}")

        header = f"Found {len(matches)} files matching '{pattern}':"
        return header + "\n" + "\n".join(lines)
    except Exception as e:
        return f"Glob error: {e}"


def _grep_search(pattern: str, path: str = "/root", file_pattern: str = "",
                 context_lines: int = 2, max_results: int = 20) -> str:
    """Search file contents using grep/ripgrep."""
    try:
        # Prefer ripgrep (rg) if available, else fallback to grep
        rg = shutil.which("rg")

        if rg:
            cmd = [rg, "--no-heading", "-n", f"-C{context_lines}", f"-m{max_results}"]
            if file_pattern:
                cmd.extend(["-g", file_pattern])
            cmd.extend([pattern, path])
        else:
            cmd = ["grep", "-rn", f"-C{context_lines}", f"-m{max_results}"]
            if file_pattern:
                cmd.extend(["--include", file_pattern])
            cmd.extend([pattern, path])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout.strip()

        if not output:
            return f"No matches for '{pattern}' in {path}"

        # Truncate if too long
        if len(output) > MAX_SHELL_OUTPUT:
            output = output[:MAX_SHELL_OUTPUT] + f"\n... [truncated, showing first {MAX_SHELL_OUTPUT} chars]"

        match_count = output.count("\n") + 1
        return f"Found matches ({match_count} lines):\n{output}"
    except subprocess.TimeoutExpired:
        return "Search timed out"
    except Exception as e:
        return f"Grep error: {e}"


def _process_manage(action: str, target: str = "", signal: str = "TERM") -> str:
    """Manage running processes."""
    try:
        if action == "list":
            # List running processes (filtered if target provided)
            if target:
                result = subprocess.run(
                    ["pgrep", "-a", "-f", target],
                    capture_output=True, text=True, timeout=5
                )
            else:
                result = subprocess.run(
                    ["ps", "aux", "--sort=-pcpu"],
                    capture_output=True, text=True, timeout=5
                )
            output = result.stdout.strip()
            return output[:3000] if output else "No matching processes"

        elif action == "kill":
            if not target:
                return "Error: target (PID or process name) required"
            sig = {"TERM": "15", "KILL": "9", "HUP": "1"}.get(signal, "15")

            # Try as PID first
            if target.isdigit():
                result = subprocess.run(
                    ["kill", f"-{sig}", target],
                    capture_output=True, text=True, timeout=5
                )
            else:
                # Kill by name
                result = subprocess.run(
                    ["pkill", f"-{sig}", "-f", target],
                    capture_output=True, text=True, timeout=5
                )
            if result.returncode == 0:
                return f"✅ Sent SIG{signal} to {target}"
            else:
                return f"Failed to kill {target}: {result.stderr.strip()}"

        elif action == "check_port":
            if not target:
                return "Error: port number required"
            result = subprocess.run(
                ["fuser", f"{target}/tcp"],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip():
                pids = result.stdout.strip()
                # Get process details
                details = subprocess.run(
                    ["ps", "-p", pids.replace(" ", ","), "-o", "pid,comm,args"],
                    capture_output=True, text=True, timeout=5
                )
                return f"Port {target} used by PID(s): {pids}\n{details.stdout.strip()}"
            return f"Port {target} is free"

        elif action == "top":
            result = subprocess.run(
                ["ps", "aux", "--sort=-pcpu"],
                capture_output=True, text=True, timeout=5
            )
            lines = result.stdout.strip().split("\n")
            return "\n".join(lines[:15])  # Top 15 processes

        return f"Unknown action: {action}"
    except Exception as e:
        return f"Process error: {e}"


def _env_manage(action: str, key: str = "", value: str = "",
                env_file: str = "/root/.env", filter_str: str = "") -> str:
    """Manage environment variables and .env files."""
    try:
        if action == "get":
            if not key:
                return "Error: key required"
            val = os.environ.get(key, "")
            if val:
                # Mask secrets
                if any(s in key.upper() for s in ["KEY", "TOKEN", "SECRET", "PASSWORD"]):
                    return f"{key}={val[:8]}...{val[-4:]}" if len(val) > 12 else f"{key}=***"
                return f"{key}={val}"
            return f"{key} not set"

        elif action == "set":
            if not key or not value:
                return "Error: key and value required"
            os.environ[key] = value
            return f"✅ Set {key} in current process"

        elif action == "list":
            env_vars = sorted(os.environ.items())
            if filter_str:
                env_vars = [(k, v) for k, v in env_vars if filter_str.upper() in k.upper()]
            lines = []
            for k, v in env_vars[:50]:
                if any(s in k.upper() for s in ["KEY", "TOKEN", "SECRET", "PASSWORD"]):
                    v_display = f"{v[:8]}..." if len(v) > 8 else "***"
                else:
                    v_display = v[:80]
                lines.append(f"{k}={v_display}")
            return f"Environment variables ({len(lines)}):\n" + "\n".join(lines)

        elif action == "load_dotenv":
            if not os.path.exists(env_file):
                return f"File not found: {env_file}"
            loaded = 0
            with open(env_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip()
                        loaded += 1
            return f"✅ Loaded {loaded} vars from {env_file}"

        elif action == "save_dotenv":
            if not key or not value:
                return "Error: key and value required to save"
            if not _is_path_writable(env_file):
                return f"⛔ Cannot write to {env_file}"

            # Read existing, update or append
            lines = []
            found = False
            if os.path.exists(env_file):
                with open(env_file, "r") as f:
                    for line in f:
                        if line.strip().startswith(f"{key}="):
                            lines.append(f"{key}={value}\n")
                            found = True
                        else:
                            lines.append(line)
            if not found:
                lines.append(f"{key}={value}\n")

            with open(env_file, "w") as f:
                f.writelines(lines)
            return f"✅ Saved {key} to {env_file}"

        return f"Unknown action: {action}"
    except Exception as e:
        return f"Env error: {e}"


# ═══════════════════════════════════════════════════════════════
# COMPUTE TOOL IMPLEMENTATIONS — Precise algorithms
# ═══════════════════════════════════════════════════════════════

def _compute_sort(data: list, algorithm: str = "auto", reverse: bool = False, key: str = None) -> str:
    """Sort data using O(n log n) algorithms with timing."""
    import time
    import heapq
    try:
        n = len(data)
        if n == 0:
            return "[]  (empty input)"

        # If data contains dicts and key specified, extract sort key
        if key and isinstance(data[0], dict):
            keyfunc = lambda x: x.get(key, 0)
        else:
            keyfunc = None

        start = time.perf_counter_ns()

        if algorithm == "mergesort":
            # Pure mergesort implementation
            def mergesort(arr):
                if len(arr) <= 1:
                    return arr
                mid = len(arr) // 2
                left = mergesort(arr[:mid])
                right = mergesort(arr[mid:])
                return merge(left, right)
            def merge(l, r):
                result, i, j = [], 0, 0
                while i < len(l) and j < len(r):
                    lv = l[i].get(key, 0) if key and isinstance(l[i], dict) else l[i]
                    rv = r[j].get(key, 0) if key and isinstance(r[j], dict) else r[j]
                    if lv <= rv:
                        result.append(l[i]); i += 1
                    else:
                        result.append(r[j]); j += 1
                result.extend(l[i:]); result.extend(r[j:])
                return result
            result = mergesort(list(data))
            if reverse:
                result.reverse()

        elif algorithm == "heapsort":
            if keyfunc:
                decorated = [(keyfunc(x), i, x) for i, x in enumerate(data)]
                heapq.heapify(decorated)
                result = [heapq.heappop(decorated)[2] for _ in range(len(decorated))]
            else:
                heap = list(data)
                heapq.heapify(heap)
                result = [heapq.heappop(heap) for _ in range(len(heap))]
            if reverse:
                result.reverse()

        else:  # auto / quicksort / timsort — Python's Timsort is optimal
            result = sorted(data, key=keyfunc, reverse=reverse)

        elapsed_ns = time.perf_counter_ns() - start
        elapsed_ms = elapsed_ns / 1_000_000

        # Format output
        preview = json.dumps(result[:100])
        if n > 100:
            preview = preview[:-1] + f", ... ({n - 100} more)]"

        algo_used = algorithm if algorithm != "auto" else "timsort"
        return f"Sorted {n} items ({algo_used}, O(n·log·n)) in {elapsed_ms:.3f}ms\n{preview}"
    except Exception as e:
        return f"Sort error: {e}"


def _compute_stats(data: list, percentiles: list = None) -> str:
    """Calculate comprehensive statistics."""
    import statistics
    import math
    try:
        n = len(data)
        if n == 0:
            return "Error: empty dataset"

        nums = [float(x) for x in data]
        result = {
            "count": n,
            "sum": sum(nums),
            "min": min(nums),
            "max": max(nums),
            "range": max(nums) - min(nums),
            "mean": statistics.mean(nums),
            "median": statistics.median(nums),
        }

        if n >= 2:
            result["std_dev"] = statistics.stdev(nums)
            result["variance"] = statistics.variance(nums)
            result["pop_std_dev"] = statistics.pstdev(nums)

        try:
            result["mode"] = statistics.mode(nums)
        except statistics.StatisticsError:
            result["mode"] = "no unique mode"

        if n >= 4:
            sorted_nums = sorted(nums)
            q1_idx = n // 4
            q3_idx = (3 * n) // 4
            result["q1"] = sorted_nums[q1_idx]
            result["q3"] = sorted_nums[q3_idx]
            result["iqr"] = sorted_nums[q3_idx] - sorted_nums[q1_idx]

        # Custom percentiles
        if percentiles:
            sorted_nums = sorted(nums)
            pct_results = {}
            for p in percentiles:
                idx = int(p / 100 * (n - 1))
                pct_results[f"p{p}"] = sorted_nums[min(idx, n - 1)]
            result["percentiles"] = pct_results

        lines = [f"Statistics for {n} values:"]
        for k, v in result.items():
            if isinstance(v, float):
                lines.append(f"  {k}: {v:.6f}")
            elif isinstance(v, dict):
                for pk, pv in v.items():
                    lines.append(f"  {pk}: {pv:.6f}" if isinstance(pv, float) else f"  {pk}: {pv}")
            else:
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)
    except Exception as e:
        return f"Stats error: {e}"


def _compute_math(expression: str, precision: int = 10) -> str:
    """Evaluate math expressions safely."""
    import math
    try:
        # Allowed names for eval
        safe_names = {
            "math": math, "abs": abs, "round": round, "min": min, "max": max,
            "sum": sum, "len": len, "pow": pow, "int": int, "float": float,
            "pi": math.pi, "e": math.e, "inf": math.inf, "tau": math.tau,
            "sqrt": math.sqrt, "log": math.log, "log2": math.log2, "log10": math.log10,
            "sin": math.sin, "cos": math.cos, "tan": math.tan,
            "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
            "ceil": math.ceil, "floor": math.floor,
            "factorial": math.factorial, "gcd": math.gcd, "lcm": math.lcm,
            "comb": math.comb, "perm": math.perm,
            "radians": math.radians, "degrees": math.degrees,
            "isqrt": math.isqrt, "exp": math.exp,
            "True": True, "False": False,
        }

        # Block dangerous builtins
        for blocked in ["import", "__", "exec", "eval", "open", "compile", "globals", "locals", "getattr", "setattr", "delattr"]:
            if blocked in expression:
                return f"Error: '{blocked}' not allowed in expressions"

        result = eval(expression, {"__builtins__": {}}, safe_names)

        if isinstance(result, float):
            if result == int(result) and abs(result) < 10**15:
                return f"{expression} = {int(result)}"
            return f"{expression} = {result:.{precision}f}"
        return f"{expression} = {result}"
    except Exception as e:
        return f"Math error: {e}"


def _compute_search(data: list, target=None, method: str = "linear", condition: str = None) -> str:
    """Search/filter data using various algorithms."""
    import bisect
    import re
    import time
    try:
        n = len(data)
        start = time.perf_counter_ns()

        if method == "binary":
            if target is None:
                return "Error: target required for binary search"
            idx = bisect.bisect_left(data, target)
            elapsed = (time.perf_counter_ns() - start) / 1_000_000
            if idx < n and data[idx] == target:
                return f"Found {target} at index {idx} (binary search, O(log n)) in {elapsed:.3f}ms"
            return f"{target} not found (binary search, checked {n} items) in {elapsed:.3f}ms"

        elif method == "filter":
            if not condition:
                return "Error: condition required for filter (e.g. 'x > 50')"
            for blocked in ["import", "__", "exec", "eval", "open"]:
                if blocked in condition:
                    return f"Error: '{blocked}' not allowed"
            results = [x for x in data if eval(condition, {"__builtins__": {}}, {"x": x})]
            elapsed = (time.perf_counter_ns() - start) / 1_000_000
            preview = json.dumps(results[:50])
            return f"Filter '{condition}': {len(results)}/{n} items matched in {elapsed:.3f}ms\n{preview}"

        elif method == "regex":
            if target is None:
                return "Error: target (regex pattern) required"
            pattern = re.compile(str(target))
            results = [x for x in data if pattern.search(str(x))]
            elapsed = (time.perf_counter_ns() - start) / 1_000_000
            return f"Regex '{target}': {len(results)}/{n} matched in {elapsed:.3f}ms\n{json.dumps(results[:50])}"

        else:  # linear
            if target is None:
                return "Error: target required for linear search"
            indices = [i for i, x in enumerate(data) if x == target]
            elapsed = (time.perf_counter_ns() - start) / 1_000_000
            if indices:
                return f"Found {target} at {len(indices)} position(s): {indices[:20]} (linear, O(n)) in {elapsed:.3f}ms"
            return f"{target} not found (linear search, {n} items) in {elapsed:.3f}ms"
    except Exception as e:
        return f"Search error: {e}"


def _compute_matrix(action: str, matrix_a: list, matrix_b: list = None) -> str:
    """Matrix operations — pure Python, no numpy required."""
    try:
        a = [[float(c) for c in row] for row in matrix_a]
        rows_a, cols_a = len(a), len(a[0])

        if action == "transpose":
            result = [[a[j][i] for j in range(rows_a)] for i in range(cols_a)]
            return f"Transpose ({rows_a}x{cols_a} → {cols_a}x{rows_a}):\n{json.dumps(result)}"

        elif action == "multiply":
            if not matrix_b:
                return "Error: matrix_b required for multiply"
            b = [[float(c) for c in row] if isinstance(row, list) else [float(row)] for row in matrix_b]
            rows_b, cols_b = len(b), len(b[0])
            if cols_a != rows_b:
                return f"Error: incompatible dimensions {rows_a}x{cols_a} * {rows_b}x{cols_b}"
            result = [[sum(a[i][k] * b[k][j] for k in range(cols_a)) for j in range(cols_b)] for i in range(rows_a)]
            return f"Product ({rows_a}x{cols_a} * {rows_b}x{cols_b} = {rows_a}x{cols_b}):\n{json.dumps(result)}"

        elif action == "determinant":
            if rows_a != cols_a:
                return "Error: determinant requires square matrix"
            def det(m):
                n = len(m)
                if n == 1: return m[0][0]
                if n == 2: return m[0][0]*m[1][1] - m[0][1]*m[1][0]
                d = 0
                for j in range(n):
                    sub = [[m[i][k] for k in range(n) if k != j] for i in range(1, n)]
                    d += ((-1)**j) * m[0][j] * det(sub)
                return d
            d = det(a)
            return f"Determinant of {rows_a}x{cols_a} matrix = {d}"

        elif action == "inverse":
            if rows_a != cols_a:
                return "Error: inverse requires square matrix"
            n = rows_a
            # Augment with identity
            aug = [row + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(a)]
            for col in range(n):
                max_row = max(range(col, n), key=lambda r: abs(aug[r][col]))
                aug[col], aug[max_row] = aug[max_row], aug[col]
                if abs(aug[col][col]) < 1e-12:
                    return "Error: matrix is singular (no inverse)"
                pivot = aug[col][col]
                aug[col] = [x / pivot for x in aug[col]]
                for row in range(n):
                    if row != col:
                        factor = aug[row][col]
                        aug[row] = [aug[row][k] - factor * aug[col][k] for k in range(2 * n)]
            inv = [row[n:] for row in aug]
            return f"Inverse of {n}x{n} matrix:\n{json.dumps([[round(c, 8) for c in row] for row in inv])}"

        elif action == "solve":
            if not matrix_b:
                return "Error: matrix_b (vector b) required for solve Ax=b"
            b_vec = [float(x) if not isinstance(x, list) else float(x[0]) for x in matrix_b]
            n = rows_a
            aug = [list(a[i]) + [b_vec[i]] for i in range(n)]
            for col in range(n):
                max_row = max(range(col, n), key=lambda r: abs(aug[r][col]))
                aug[col], aug[max_row] = aug[max_row], aug[col]
                if abs(aug[col][col]) < 1e-12:
                    return "Error: system has no unique solution"
                pivot = aug[col][col]
                aug[col] = [x / pivot for x in aug[col]]
                for row in range(n):
                    if row != col:
                        factor = aug[row][col]
                        aug[row] = [aug[row][k] - factor * aug[col][k] for k in range(n + 1)]
            solution = [round(aug[i][n], 8) for i in range(n)]
            return f"Solution x = {solution}"

        elif action == "eigenvalues":
            if rows_a != cols_a:
                return "Error: eigenvalues require square matrix"
            if rows_a == 2:
                trace = a[0][0] + a[1][1]
                det_val = a[0][0]*a[1][1] - a[0][1]*a[1][0]
                disc = trace**2 - 4*det_val
                if disc >= 0:
                    e1 = (trace + disc**0.5) / 2
                    e2 = (trace - disc**0.5) / 2
                    return f"Eigenvalues: [{round(e1, 8)}, {round(e2, 8)}]"
                else:
                    real = trace / 2
                    imag = (-disc)**0.5 / 2
                    return f"Eigenvalues: [{real:.8f} + {imag:.8f}i, {real:.8f} - {imag:.8f}i]"
            return "Eigenvalues for matrices >2x2 require numpy (not installed). Use 2x2 matrices or install numpy."

        return f"Unknown matrix action: {action}"
    except Exception as e:
        return f"Matrix error: {e}"


def _compute_prime(action: str, n: int, limit: int = None) -> str:
    """Prime number operations."""
    try:
        if action == "is_prime":
            if n < 2:
                return f"{n} is NOT prime"
            if n < 4:
                return f"{n} IS prime"
            if n % 2 == 0:
                return f"{n} is NOT prime (divisible by 2)"
            i = 3
            while i * i <= n:
                if n % i == 0:
                    return f"{n} is NOT prime (divisible by {i})"
                i += 2
            return f"{n} IS prime"

        elif action == "factorize":
            if n < 2:
                return f"{n} has no prime factorization"
            factors = []
            d = 2
            temp = n
            while d * d <= temp:
                while temp % d == 0:
                    factors.append(d)
                    temp //= d
                d += 1
            if temp > 1:
                factors.append(temp)
            # Format as exponents
            from collections import Counter
            counts = Counter(factors)
            factored = " × ".join(f"{p}^{e}" if e > 1 else str(p) for p, e in sorted(counts.items()))
            return f"{n} = {factored}  (factors: {factors})"

        elif action == "generate":
            upper = limit if limit else n
            if upper > 10_000_000:
                return "Error: limit too large (max 10M for sieve)"
            # Sieve of Eratosthenes — O(n log log n)
            sieve = [True] * (upper + 1)
            sieve[0] = sieve[1] = False
            for i in range(2, int(upper**0.5) + 1):
                if sieve[i]:
                    for j in range(i*i, upper + 1, i):
                        sieve[j] = False
            primes = [i for i, is_p in enumerate(sieve) if is_p]
            count = len(primes)
            preview = primes[:100]
            result = f"Found {count} primes up to {upper}\n{preview}"
            if count > 100:
                result += f"\n... and {count - 100} more"
            return result

        elif action == "nth_prime":
            if n > 500_000:
                return "Error: n too large (max 500K)"
            count = 0
            candidate = 2
            while True:
                is_p = True
                if candidate < 2:
                    is_p = False
                elif candidate == 2:
                    is_p = True
                elif candidate % 2 == 0:
                    is_p = False
                else:
                    i = 3
                    while i * i <= candidate:
                        if candidate % i == 0:
                            is_p = False
                            break
                        i += 2
                if is_p:
                    count += 1
                    if count == n:
                        return f"The {n}th prime is {candidate}"
                candidate += 1

        return f"Unknown prime action: {action}"
    except Exception as e:
        return f"Prime error: {e}"


def _compute_hash(data: str = "", algorithm: str = "sha256", file_path: str = None) -> str:
    """Compute cryptographic hashes."""
    import hashlib
    try:
        h = hashlib.new(algorithm)

        if file_path:
            if not os.path.exists(file_path):
                return f"File not found: {file_path}"
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    h.update(chunk)
            size = os.path.getsize(file_path)
            return f"{algorithm}({file_path}) [{size} bytes] = {h.hexdigest()}"

        if not data:
            return "Error: provide data string or file_path"

        h.update(data.encode("utf-8"))
        return f"{algorithm}(\"{data[:50]}{'...' if len(data) > 50 else ''}\") = {h.hexdigest()}"
    except Exception as e:
        return f"Hash error: {e}"


def _compute_convert(value, from_unit: str, to_unit: str) -> str:
    """Unit and base conversions."""
    try:
        from_u = from_unit.lower().strip()
        to_u = to_unit.lower().strip()

        # Number base conversions
        base_map = {"bin": 2, "binary": 2, "oct": 8, "octal": 8, "dec": 10, "decimal": 10, "hex": 16, "hexadecimal": 16}
        if from_u in base_map and to_u in base_map:
            num = int(str(value), base_map[from_u])
            if base_map[to_u] == 2:
                result = bin(num)
            elif base_map[to_u] == 8:
                result = oct(num)
            elif base_map[to_u] == 16:
                result = hex(num)
            else:
                result = str(num)
            return f"{value} (base {base_map[from_u]}) = {result} (base {base_map[to_u]})"

        v = float(value)

        # Temperature
        temp_conversions = {
            ("celsius", "fahrenheit"): lambda c: c * 9/5 + 32,
            ("fahrenheit", "celsius"): lambda f: (f - 32) * 5/9,
            ("celsius", "kelvin"): lambda c: c + 273.15,
            ("kelvin", "celsius"): lambda k: k - 273.15,
            ("fahrenheit", "kelvin"): lambda f: (f - 32) * 5/9 + 273.15,
            ("kelvin", "fahrenheit"): lambda k: (k - 273.15) * 9/5 + 32,
        }
        if (from_u, to_u) in temp_conversions:
            result = temp_conversions[(from_u, to_u)](v)
            return f"{v} {from_u} = {result:.4f} {to_u}"

        # Data sizes
        data_units = {"bits": 1, "bytes": 8, "kb": 8*1024, "mb": 8*1024**2, "gb": 8*1024**3, "tb": 8*1024**4, "kib": 8*1024, "mib": 8*1024**2, "gib": 8*1024**3}
        if from_u in data_units and to_u in data_units:
            bits = v * data_units[from_u]
            result = bits / data_units[to_u]
            return f"{v} {from_unit} = {result:.6f} {to_unit}"

        # Distance
        dist_m = {"m": 1, "meters": 1, "km": 1000, "mi": 1609.344, "miles": 1609.344, "ft": 0.3048, "feet": 0.3048, "in": 0.0254, "inches": 0.0254, "cm": 0.01, "mm": 0.001, "yd": 0.9144, "yards": 0.9144, "nm": 1852, "nautical_miles": 1852}
        if from_u in dist_m and to_u in dist_m:
            meters = v * dist_m[from_u]
            result = meters / dist_m[to_u]
            return f"{v} {from_unit} = {result:.6f} {to_unit}"

        # Weight
        weight_kg = {"kg": 1, "g": 0.001, "mg": 0.000001, "lb": 0.453592, "lbs": 0.453592, "oz": 0.0283495, "ton": 907.185, "tonne": 1000, "st": 6.35029}
        if from_u in weight_kg and to_u in weight_kg:
            kg = v * weight_kg[from_u]
            result = kg / weight_kg[to_u]
            return f"{v} {from_unit} = {result:.6f} {to_unit}"

        # Timestamp conversions
        if from_u == "unix_timestamp" and to_u == "iso8601":
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(v, tz=timezone.utc)
            return f"{value} unix = {dt.isoformat()}"
        if from_u == "iso8601" and to_u == "unix_timestamp":
            from datetime import datetime
            dt = datetime.fromisoformat(str(value))
            return f"{value} = {dt.timestamp()} unix"

        return f"Unknown conversion: {from_unit} → {to_unit}"
    except Exception as e:
        return f"Convert error: {e}"


# ═══════════════════════════════════════════════════════════════
# Tmux Agent Spawning (Elvis pattern)
# ═══════════════════════════════════════════════════════════════

def _tmux_agents(tool_input: dict) -> str:
    """Manage parallel Claude Code agents in tmux panes."""
    try:
        from tmux_spawner import get_spawner
        spawner = get_spawner()
        action = tool_input["action"]

        if action == "spawn":
            job_id = tool_input.get("job_id")
            prompt = tool_input.get("prompt")
            if not job_id or not prompt:
                return "Error: spawn requires job_id and prompt"
            pane_id = spawner.spawn_agent(
                job_id=job_id,
                prompt=prompt,
                worktree_repo=tool_input.get("worktree_repo"),
                use_worktree=tool_input.get("use_worktree", False),
                cwd=tool_input.get("cwd"),
                timeout_minutes=tool_input.get("timeout_minutes", 30),
            )
            return json.dumps({"status": "spawned", "pane_id": pane_id, "job_id": job_id})

        elif action == "spawn_parallel":
            jobs = tool_input.get("jobs", [])
            if not jobs:
                return "Error: spawn_parallel requires jobs list"
            results = spawner.spawn_parallel(jobs)
            spawned = sum(1 for r in results if r["status"] == "spawned")
            return json.dumps({"spawned": spawned, "total": len(jobs), "results": results})

        elif action == "list":
            agents = spawner.list_agents()
            return json.dumps({"count": len(agents), "agents": agents})

        elif action == "output":
            pane_id = tool_input.get("pane_id")
            if not pane_id:
                return "Error: output requires pane_id"
            output = spawner.collect_output(pane_id)
            status = spawner.get_agent_status(pane_id)
            return json.dumps({
                "pane_id": pane_id,
                "output": output[:10000],  # Cap output size
                "status": status,
            })

        elif action == "kill":
            pane_id = tool_input.get("pane_id")
            if not pane_id:
                return "Error: kill requires pane_id"
            killed = spawner.kill_agent(pane_id)
            return json.dumps({"killed": killed, "pane_id": pane_id})

        elif action == "kill_all":
            count = spawner.kill_all()
            return json.dumps({"killed": count})

        elif action == "cleanup":
            job_id = tool_input.get("job_id")
            if not job_id:
                return "Error: cleanup requires job_id"
            spawner.cleanup(job_id)
            return json.dumps({"cleaned": True, "job_id": job_id})

        else:
            return f"Unknown tmux_agents action: {action}"

    except Exception as e:
        return f"Error: {e}"


# ═══════════════════════════════════════════════════════════════
# Claude Code Headless Mode (Overseer only)
# ═══════════════════════════════════════════════════════════════

def _claude_headless(tool_input: dict) -> str:
    """
    Execute a Claude Code headless mode task.
    RESTRICTED: Overseer agent only (expensive — uses Opus).
    """
    import asyncio
    from claude_headless import ClaudeHeadless

    action = tool_input.get("action", "run")

    try:
        headless = ClaudeHeadless()

        # Create an event loop for async operations
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            if action == "run":
                # Direct prompt execution
                result = loop.run_until_complete(
                    headless.run(
                        prompt=tool_input.get("prompt", ""),
                        cwd=tool_input.get("cwd", "."),
                        timeout=tool_input.get("timeout"),
                        model=tool_input.get("model"),
                        max_turns=tool_input.get("max_turns", 10),
                    )
                )

            elif action == "review_pr":
                # Code review
                result = loop.run_until_complete(
                    headless.review_pr(
                        repo_path=tool_input.get("repo_path", "."),
                        branch=tool_input.get("branch", "HEAD"),
                        pr_number=tool_input.get("pr_number"),
                    )
                )

            elif action == "fix_test":
                # Auto-fix failing test
                result = loop.run_until_complete(
                    headless.fix_test(
                        test_file=tool_input.get("test_file", ""),
                        error=tool_input.get("error", ""),
                        project_path=tool_input.get("project_path", "."),
                    )
                )

            elif action == "build_feature":
                # Build feature from spec
                result = loop.run_until_complete(
                    headless.build_feature(
                        spec=tool_input.get("spec", ""),
                        project_path=tool_input.get("project_path", "."),
                    )
                )

            elif action == "debug_issue":
                # Debug and propose fix
                result = loop.run_until_complete(
                    headless.debug_issue(
                        issue_description=tool_input.get("error", ""),
                        project_path=tool_input.get("project_path", "."),
                    )
                )

            elif action == "audit_code":
                # Code audit
                result = loop.run_until_complete(
                    headless.audit_code(
                        target_path=tool_input.get("repo_path", "."),
                        focus=tool_input.get("focus", "security"),
                    )
                )

            else:
                return f"Unknown claude_headless action: {action}"

            # Format result
            output = {
                "action": action,
                "success": result.get("success", False),
                "model": result.get("model", "opus"),
                "duration_seconds": result.get("duration_seconds", 0),
                "cost_estimate": result.get("cost_estimate", "$0"),
            }

            if result.get("success"):
                output["output"] = result.get("output", "")[:3000]
            else:
                output["error"] = result.get("error", "Unknown error")

            return json.dumps(output, indent=2)

        finally:
            loop.close()

    except ImportError:
        return json.dumps({
            "success": False,
            "error": "claude_headless module not found. Install it first.",
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Claude headless error: {str(e)}",
        })


# ═══════════════════════════════════════════════════════════════
# Security Scan (OXO / Ostorlab)
# ═══════════════════════════════════════════════════════════════

SCAN_PROFILES = {
    "quick": ["agent/ostorlab/nmap"],
    "full": ["agent/ostorlab/nmap", "agent/ostorlab/nuclei"],
    "web": ["agent/ostorlab/nmap", "agent/ostorlab/nuclei", "agent/ostorlab/zap"],
}


def _security_scan(target: str, scan_type: str = "quick", agents: list = None) -> str:
    """Run an OXO security scan against a target."""
    import re

    if not shutil.which("oxo"):
        return "Error: oxo CLI not installed. Install with: pip3 install ostorlab"

    # Validate target
    target = target.strip()
    if not target:
        return "Error: target is required"

    # Determine asset type
    if re.match(r"^https?://", target):
        asset_flag = ["--url", target]
    elif re.match(r"^\d{1,3}(\.\d{1,3}){3}$", target):
        asset_flag = ["--ip", target]
    elif re.match(r"^\d{1,3}(\.\d{1,3}){3}/\d+$", target):
        asset_flag = ["--ip-range", target]
    else:
        asset_flag = ["--domain", target]

    # Pick agents
    agent_list = agents or SCAN_PROFILES.get(scan_type, SCAN_PROFILES["quick"])

    # Build command
    cmd = ["oxo", "scan", "run"]
    for agent_key in agent_list:
        cmd.extend(["--agent", agent_key])
    cmd.extend(asset_flag)

    try:
        logger.info(f"Starting OXO scan: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        output = result.stdout.strip()
        if result.stderr:
            output += f"\n{result.stderr.strip()}"

        # Emit scan event
        try:
            from event_engine import get_event_engine
            event_type = "scan.completed" if result.returncode == 0 else "scan.failed"
            get_event_engine().emit(event_type, {
                "target": target,
                "scan_type": scan_type,
                "agents": agent_list,
            })
        except Exception:
            pass

        return output or "Scan completed (no output)"
    except subprocess.TimeoutExpired:
        return "Scan timed out after 5 minutes. Try a 'quick' scan or specific agents."
    except Exception as e:
        return f"Scan error: {e}"


def _prediction_market(action: str, query: str, market_id: str, tag: str, limit: int) -> str:
    """Query Polymarket prediction markets via CLI."""
    try:
        if action == "search":
            if not query:
                return "Error: 'query' is required for search action"
            cmd = ["polymarket", "markets", "search", query, "-o", "json"]
        elif action == "get_market":
            if not market_id:
                return "Error: 'market_id' is required for get_market action"
            cmd = ["polymarket", "markets", "get", market_id, "-o", "json"]
        elif action == "list_markets":
            cmd = ["polymarket", "markets", "list", "-o", "json"]
        elif action == "list_events":
            cmd = ["polymarket", "events", "list", "-o", "json"]
            if tag:
                cmd.extend(["--tag", tag])
        else:
            return f"Unknown action: {action}. Use: search, get_market, list_markets, list_events"

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr:
            output = result.stderr.strip() if not output else f"{output}\n{result.stderr.strip()}"

        if not output:
            return "No results returned"

        # Cap output size
        if len(output) > MAX_SHELL_OUTPUT:
            output = output[:MAX_SHELL_OUTPUT] + "\n... (truncated)"

        return output
    except subprocess.TimeoutExpired:
        return "Polymarket query timed out after 30 seconds"
    except FileNotFoundError:
        return "Error: polymarket CLI not installed. Run: curl -sSL https://raw.githubusercontent.com/Polymarket/polymarket-cli/main/install.sh | sh"
    except Exception as e:
        return f"Prediction market error: {e}"


def _get_reflections(action: str, task: str = "", project: str = None, limit: int = 5) -> str:
    """Get past job reflections — learnings from completed/failed jobs."""
    try:
        from reflexion import get_stats, list_reflections, search_reflections, format_reflections_for_prompt

        if action == "stats":
            stats = get_stats()
            return json.dumps(stats, indent=2)

        elif action == "list":
            refs = list_reflections(project=project, limit=limit)
            if not refs:
                return "No reflections found."
            lines = [f"Reflections ({len(refs)} total):"]
            for r in refs:
                outcome = "SUCCESS" if r.get("outcome") == "success" else "FAILED"
                lines.append(
                    f"  [{outcome}] {r.get('job_id', '?')} — {r.get('task', '?')[:80]} "
                    f"(project={r.get('project', '?')}, {r.get('duration_seconds', 0):.0f}s)"
                )
            return "\n".join(lines)

        elif action == "search":
            if not task:
                return "Error: 'task' parameter required for search action"
            refs = search_reflections(task, project=project, limit=limit)
            if not refs:
                return "No relevant reflections found for this task."
            return format_reflections_for_prompt(refs)

        else:
            return f"Unknown action: {action}. Use: stats, list, search"

    except Exception as e:
        return f"Reflections error: {e}"


def _create_event(event_type: str, data: dict) -> str:
    """Emit an event to the OpenClaw event engine."""
    try:
        import requests as req
        resp = req.post(
            "http://localhost:18789/api/events",
            json={"event_type": event_type, "data": data},
            timeout=10,
        )
        return json.dumps(resp.json(), indent=2)
    except Exception as e:
        return f"Error creating event: {e}"


def _plan_my_day(focus: str = "all") -> str:
    """Gather calendar, jobs, agency status, emails, schedule, and todos for a daily plan."""
    try:
        import requests as req
        gw = "http://localhost:18789"
        results = {}
        now = datetime.now(timezone.utc)
        day_name = now.strftime("%A")

        # === Miles' Schedule Context ===
        schedule = {
            "today": day_name,
            "date": now.strftime("%Y-%m-%d"),
            "work_today": day_name != "Monday",
            "work_hours": "5pm-10pm" if day_name != "Monday" else "OFF",
            "free_hours": "All day" if day_name == "Monday" else "Before 5pm, after 10pm",
            "notes": [],
        }
        if day_name == "Thursday":
            schedule["notes"].append("Soccer at 9:20pm — leave work early")
        if day_name == "Monday":
            schedule["notes"].append("Day off — best day for big tasks, Claude sessions, planning")
        results["schedule"] = schedule

        # === Calendar ===
        try:
            r = req.get(f"{gw}/api/calendar/today", timeout=10)
            results["calendar"] = r.json() if r.ok else {"events": []}
        except Exception:
            results["calendar"] = {"events": []}

        # === Jobs ===
        try:
            r = req.get(f"{gw}/api/jobs?limit=20", timeout=10)
            jobs = r.json().get("jobs", []) if r.ok else []
            results["pending_jobs"] = [j for j in jobs if j.get("status") in ("pending", "analyzing")]
            results["active_jobs"] = [j for j in jobs if j.get("status") in ("running", "in_progress")]
            results["recent_completed"] = [j for j in jobs if j.get("status") == "done"][:5]
        except Exception:
            results["pending_jobs"] = []
            results["active_jobs"] = []
            results["recent_completed"] = []

        # === Agency status ===
        try:
            r = req.get(f"{gw}/api/agency/status", timeout=10)
            results["agency_status"] = r.json() if r.ok else {}
        except Exception:
            results["agency_status"] = {}

        # === Emails ===
        try:
            r = req.get(f"{gw}/api/gmail/inbox?max_results=10", timeout=10)
            results["unread_emails"] = r.json().get("messages", []) if r.ok else []
        except Exception:
            results["unread_emails"] = []

        # === Todos / Assignments ===
        try:
            r = req.get(f"{gw}/api/tasks", timeout=10)
            tasks = r.json() if r.ok else []
            if isinstance(tasks, dict):
                tasks = tasks.get("tasks", [])
            results["todos"] = [t for t in tasks if t.get("status") != "done"]
        except Exception:
            results["todos"] = []

        # === Memories (assignments, deadlines, commitments) ===
        try:
            memories = _search_memory("assignments deadlines schedule todo", limit=5)
            results["relevant_memories"] = memories
        except Exception:
            results["relevant_memories"] = "No memories found"

        results["focus"] = focus

        # === AI News Highlights ===
        try:
            news = _read_ai_news(limit=5, source=None, hours=24)
            results["ai_news_highlights"] = news
        except Exception:
            results["ai_news_highlights"] = "Could not fetch AI news"

        # === Suggested todos based on context ===
        suggested = []
        if results.get("pending_jobs"):
            suggested.append(f"Review {len(results['pending_jobs'])} pending jobs")
        if day_name == "Monday":
            suggested.append("Plan the week — review all projects")
            suggested.append("Work on OpenClaw (Stripe go-live, client dashboard)")
        results["suggested_todos"] = suggested

        return json.dumps(results, indent=2, default=str)
    except Exception as e:
        return f"Error planning day: {e}"

def _morning_briefing(send_to_slack: bool = True, include_news: bool = True) -> str:
    """
    Generate comprehensive morning briefing:
    - Today's calendar events via gws
    - Unread emails via gws
    - Overdue/pending tasks
    - Industry news (optional)
    - Sends to Slack if enabled
    """
    try:
        briefing_parts = []
        now = datetime.now(timezone.utc)
        day_name = now.strftime("%A")
        briefing_date = now.strftime("%A, %B %d, %Y")

        briefing_parts.append(f"☀️ *Good Morning!* — {briefing_date}")
        briefing_parts.append(f"Today: {day_name}")

        if day_name == "Monday":
            briefing_parts.append("⚠️  You have the day off — focus time available for deep work")
        elif day_name == "Thursday":
            briefing_parts.append("⚠️  Soccer at 9:20pm — adjust work schedule accordingly")

        briefing_parts.append("")

        # === CALENDAR EVENTS ===
        calendar_section = ["📅 *Today's Calendar*"]
        try:
            result = subprocess.run(
                ["/usr/bin/gws", "calendar", "events", "list",
                 "--params", '{"calendarId":"primary","timeMin":"' + now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + '","timeMax":"' + now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat() + '","maxResults":10}',
                 "--format", "json"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                events_data = json.loads(result.stdout)
                events = events_data.get("items", [])
                if events:
                    for event in events[:5]:  # Top 5 events
                        title = event.get("summary", "Untitled")
                        start = event.get("start", {})
                        start_time = start.get("dateTime", start.get("date", "N/A"))
                        if "T" in str(start_time):
                            try:
                                dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                                time_str = dt.strftime("%I:%M %p")
                            except:
                                time_str = str(start_time)[:16]
                        else:
                            time_str = "All day"
                        calendar_section.append(f"  • {time_str}: {title}")
                else:
                    calendar_section.append("  No events scheduled")
            else:
                calendar_section.append("  Could not fetch calendar (gws not authorized)")
        except subprocess.TimeoutExpired:
            calendar_section.append("  Calendar fetch timeout")
        except Exception as e:
            calendar_section.append(f"  Error: {str(e)[:50]}")

        briefing_parts.extend(calendar_section)
        briefing_parts.append("")

        # === UNREAD EMAILS ===
        email_section = ["📧 *Unread Emails*"]
        try:
            result = subprocess.run(
                ["/usr/bin/gws", "gmail", "users", "messages", "list",
                 "--params", '{"userId":"me","q":"is:unread","maxResults":5}',
                 "--format", "json"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                messages_data = json.loads(result.stdout)
                messages = messages_data.get("messages", [])
                if messages:
                    email_section.append(f"  {len(messages)} unread messages")
                    for msg in messages[:3]:  # Top 3 senders
                        msg_id = msg.get("id")
                        try:
                            detail_result = subprocess.run(
                                ["/usr/bin/gws", "gmail", "users", "messages", "get",
                                 "--params", f'{{"userId":"me","id":"{msg_id}","format":"metadata","metadataHeaders":"From,Subject"}}',
                                 "--format", "json"],
                                capture_output=True,
                                text=True,
                                timeout=5
                            )
                            if detail_result.returncode == 0:
                                detail_data = json.loads(detail_result.stdout)
                                headers = detail_data.get("payload", {}).get("headers", [])
                                sender = next((h["value"] for h in headers if h["name"] == "From"), "Unknown")
                                subject = next((h["value"] for h in headers if h["name"] == "Subject"), "No subject")
                                sender_name = sender.split("<")[0].strip() if "<" in sender else sender
                                email_section.append(f"  • From: {sender_name[:30]}")
                                email_section.append(f"    Subject: {subject[:50]}")
                        except:
                            pass
                else:
                    email_section.append("  Inbox zero! 🎉")
            else:
                email_section.append("  Could not fetch emails (gws not authorized)")
        except subprocess.TimeoutExpired:
            email_section.append("  Email fetch timeout")
        except Exception as e:
            email_section.append(f"  Error: {str(e)[:50]}")

        briefing_parts.extend(email_section)
        briefing_parts.append("")

        # === PENDING JOBS & TASKS ===
        try:
            import requests as req
            gw = "http://localhost:18789"
            r = req.get(f"{gw}/api/jobs?limit=10", timeout=5)
            if r.ok:
                jobs = r.json().get("jobs", [])
                pending_jobs = [j for j in jobs if j.get("status") in ("pending", "analyzing")]
                if pending_jobs:
                    briefing_parts.append(f"⏳ *Pending Jobs*: {len(pending_jobs)} waiting")
                    for j in pending_jobs[:3]:
                        briefing_parts.append(f"  • {j.get('description', 'Unknown')[:50]}")
                    briefing_parts.append("")
        except Exception:
            pass

        # === AI/TECH NEWS (optional) ===
        if include_news:
            news_section = ["📰 *Industry Headlines*"]
            try:
                news = _read_ai_news(limit=3, source=None, hours=24)
                if news and isinstance(news, str):
                    # Parse the news output (it's text, not JSON)
                    lines = news.split("\n")[:6]
                    for line in lines:
                        if line.strip():
                            news_section.append(f"  • {line.strip()[:60]}")
                else:
                    news_section.append("  Could not fetch news")
            except Exception as e:
                news_section.append(f"  Error: {str(e)[:50]}")

            briefing_parts.extend(news_section)
            briefing_parts.append("")

        # === ACTION ITEMS ===
        action_section = ["✅ *Today's Focus*"]
        if day_name == "Monday":
            action_section.append("  • Plan the week — review all projects")
            action_section.append("  • OpenClaw: Stripe commercialization")
            action_section.append("  • Check in on all active projects")
        else:
            action_section.append(f"  • Work hours: 5pm-10pm (10 hours)")
            action_section.append("  • Review pending jobs above")
            action_section.append("  • Respond to unread emails")

        if day_name == "Thursday":
            action_section.append("  ⚽ Leave early for soccer (9:20pm)")

        briefing_parts.extend(action_section)

        # === Format and send ===
        briefing_text = "\n".join(briefing_parts)

        if send_to_slack:
            try:
                channel = os.environ.get("SLACK_REPORT_CHANNEL", "C0AFE4QHKH7")
                _send_slack_message(briefing_text, channel)
                briefing_text += "\n\n✅ Sent to Slack"
            except Exception as e:
                briefing_text += f"\n\n⚠️  Slack send failed: {str(e)[:50]}"

        return briefing_text

    except Exception as e:
        return f"Error generating morning briefing: {e}"




# ═══════════════════════════════════════════════════════════════
# NEWS & SOCIAL MEDIA IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════

RSS_FEEDS = {
    "openai": "https://openai.com/blog/rss.xml",
    "deepmind": "https://deepmind.google/blog/rss.xml",
    "huggingface": "https://huggingface.co/blog/feed.xml",
    "arxiv": "https://rss.arxiv.org/rss/cs.AI",
    "verge": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "arstechnica": "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "techcrunch": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "hackernews": "https://hnrss.org/frontpage?q=AI+OR+LLM+OR+GPT+OR+Claude+OR+machine+learning",
    "mittech": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
}

NITTER_INSTANCES = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://xcancel.com",
]

AI_TWITTER_ACCOUNTS = [
    "AnthropicAI",
    "OpenAI",
    "GoogleDeepMind",
    "ylecun",
    "sama",
    "kaboragora",
    "karpathy",
    "hardmaru",
    "_akhaliq",
    "svpino",
    "ClementDelangue",
    "jackclarkSF",
    "HuggingFace",
    "LangChainAI",
    "DrJimFan",
    "bindureddy",
]

# Bluesky AT Protocol — free public API, no auth needed
BLUESKY_API = "https://public.api.bsky.app/xrpc"
BLUESKY_ACCOUNTS = [
    "sama.bsky.social",
    "karpathy.bsky.social",
    "jimfan.bsky.social",
    "huggingface.bsky.social",
    "deepmind.bsky.social",
    "langchain.bsky.social",
    "openai.bsky.social",
]

# Map Twitter handles to Bluesky handles where available
TWITTER_TO_BLUESKY = {
    "sama": "sama.bsky.social",
    "karpathy": "karpathy.bsky.social",
    "jimfan": "jimfan.bsky.social",
}

# Reddit AI subreddits (native RSS, no auth needed, very reliable)
REDDIT_AI_FEEDS = [
    "https://www.reddit.com/r/MachineLearning/hot/.rss",
    "https://www.reddit.com/r/artificial/hot/.rss",
    "https://www.reddit.com/r/LocalLLaMA/hot/.rss",
    "https://www.reddit.com/r/singularity/hot/.rss",
    "https://www.reddit.com/r/ChatGPT/hot/.rss",
]


def _perplexity_research(query: str, model: str = "sonar", focus: str = "web") -> str:
    """Deep research using Perplexity Sonar API — returns AI-synthesized answers with citations."""
    api_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not api_key:
        return json.dumps({
            "error": "PERPLEXITY_API_KEY not set. Get one at https://perplexity.ai/settings/api",
            "hint": "Add PERPLEXITY_API_KEY to /root/.env and restart the gateway."
        })

    # Validate model
    if model not in ("sonar", "sonar-pro"):
        model = "sonar"

    # Map focus to search_mode (Perplexity API parameter)
    # Perplexity supports: web, academic, sec
    search_mode_map = {"web": "web", "academic": "academic", "news": "web"}
    search_mode = search_mode_map.get(focus, "web")

    # Build recency filter for news focus
    search_recency = None
    if focus == "news":
        search_recency = "week"

    # Build system message
    system_msg = "You are a research assistant. Provide detailed, factual answers with citations. Be thorough and precise."

    # Build request body (OpenAI-compatible format)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": query}
        ],
        "max_tokens": 4096,
        "temperature": 0.2,
        "search_mode": search_mode,
    }

    # Add recency filter for news
    if search_recency:
        body["search_recency_filter"] = search_recency

    try:
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json=body
            )

            if resp.status_code != 200:
                error_text = resp.text[:500]
                return json.dumps({
                    "error": f"Perplexity API returned {resp.status_code}",
                    "detail": error_text
                })

            data = resp.json()

            # Extract response
            answer = ""
            if data.get("choices"):
                answer = data["choices"][0].get("message", {}).get("content", "")

            # Extract citations
            citations = data.get("citations", [])

            # Extract usage for cost tracking
            usage = data.get("usage", {})

            result = {
                "answer": answer,
                "citations": citations,
                "model": data.get("model", model),
                "usage": {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0)
                },
                "query": query,
                "focus": focus
            }

            return json.dumps(result)

    except httpx.TimeoutException:
        return json.dumps({"error": "Perplexity API request timed out (60s limit)"})
    except Exception as e:
        return json.dumps({"error": f"Perplexity research failed: {str(e)}"})


def _read_ai_news(limit: int = 10, source: str = None, hours: int = 24) -> str:
    """Fetch AI news from RSS feeds. Returns article titles, summaries, and links."""
    import re
    import html
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    feeds_to_check = {}

    if source and source.lower() in RSS_FEEDS:
        feeds_to_check[source.lower()] = RSS_FEEDS[source.lower()]
    else:
        feeds_to_check = dict(RSS_FEEDS)

    all_articles = []

    for src_name, feed_url in feeds_to_check.items():
        try:
            with httpx.Client(timeout=10, follow_redirects=True) as client:
                resp = client.get(feed_url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; OpenClaw/2.0)"
                })
                if resp.status_code != 200:
                    continue

                xml = resp.text

                # Simple XML parsing for RSS/Atom items
                items = re.findall(r'<item[^>]*>(.*?)</item>', xml, re.DOTALL)
                if not items:
                    items = re.findall(r'<entry[^>]*>(.*?)</entry>', xml, re.DOTALL)

                for item_xml in items[:20]:  # Check up to 20 per feed
                    title = ""
                    link = ""
                    description = ""
                    pub_date = ""

                    # Title
                    t = re.search(r'<title[^>]*>(.*?)</title>', item_xml, re.DOTALL)
                    if t:
                        title = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', t.group(1)).strip()
                        title = re.sub(r'<[^>]+>', '', title).strip()

                    # Link (RSS uses <link>, Atom uses <link href="..."/>)
                    l = re.search(r'<link[^>]*href="([^"]+)"', item_xml)
                    if l:
                        link = l.group(1)
                    else:
                        l = re.search(r'<link[^>]*>(.*?)</link>', item_xml, re.DOTALL)
                        if l:
                            link = l.group(1).strip()

                    # Description/summary
                    d = re.search(r'<description[^>]*>(.*?)</description>', item_xml, re.DOTALL)
                    if not d:
                        d = re.search(r'<summary[^>]*>(.*?)</summary>', item_xml, re.DOTALL)
                    if d:
                        description = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', d.group(1), flags=re.DOTALL).strip()
                        description = re.sub(r'<[^>]+>', '', description).strip()
                        description = description[:200]

                    # Published date
                    p = re.search(r'<pubDate[^>]*>(.*?)</pubDate>', item_xml, re.DOTALL)
                    if not p:
                        p = re.search(r'<published[^>]*>(.*?)</published>', item_xml, re.DOTALL)
                    if not p:
                        p = re.search(r'<updated[^>]*>(.*?)</updated>', item_xml, re.DOTALL)
                    if p:
                        pub_date = p.group(1).strip()

                    # Try to parse date and filter by cutoff
                    article_time = None
                    if pub_date:
                        try:
                            from email.utils import parsedate_to_datetime
                            article_time = parsedate_to_datetime(pub_date)
                        except Exception:
                            try:
                                # Try ISO format
                                article_time = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                            except Exception:
                                pass

                    if article_time and article_time.tzinfo and article_time < cutoff:
                        continue

                    if title:
                        all_articles.append({
                            "source": src_name,
                            "title": html.unescape(title),
                            "link": link,
                            "summary": html.unescape(description) if description else "",
                            "published": pub_date,
                            "parsed_time": article_time,
                        })

        except Exception as e:
            logger.warning(f"Failed to fetch RSS from {src_name}: {e}")
            continue

    # Sort by date (newest first), articles without dates go last
    def sort_key(a):
        if a.get("parsed_time"):
            return a["parsed_time"].timestamp()
        return 0

    all_articles.sort(key=sort_key, reverse=True)

    # Limit results
    all_articles = all_articles[:limit]

    if not all_articles:
        return json.dumps({"articles": [], "message": f"No AI news found in the last {hours} hours"})

    # Clean up for output (remove parsed_time which isn't serializable)
    output = []
    for a in all_articles:
        output.append({
            "source": a["source"],
            "title": a["title"],
            "link": a["link"],
            "summary": a["summary"],
            "published": a["published"],
        })

    return json.dumps({"articles": output, "count": len(output)}, indent=2)


def _parse_rss_items(xml: str, acct: str, limit: int) -> list:
    """Parse RSS XML and extract tweet items. Shared between RSSHub and Nitter."""
    import re
    tweets = []
    items = re.findall(r'<item[^>]*>(.*?)</item>', xml, re.DOTALL)
    for item_xml in items[:limit]:
        title = ""
        link = ""
        pub_date = ""
        description = ""

        t = re.search(r'<title[^>]*>(.*?)</title>', item_xml, re.DOTALL)
        if t:
            title = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', t.group(1)).strip()
            title = re.sub(r'<[^>]+>', '', title).strip()

        l = re.search(r'<link[^>]*>(.*?)</link>', item_xml, re.DOTALL)
        if l:
            link = l.group(1).strip()

        p = re.search(r'<pubDate[^>]*>(.*?)</pubDate>', item_xml, re.DOTALL)
        if p:
            pub_date = p.group(1).strip()

        d = re.search(r'<description[^>]*>(.*?)</description>', item_xml, re.DOTALL)
        if d:
            description = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', d.group(1), flags=re.DOTALL).strip()
            description = re.sub(r'<[^>]+>', '', description).strip()
            description = description[:280]

        if title or description:
            tweets.append({
                "account": acct,
                "text": description or title,
                "link": link,
                "published": pub_date,
            })
    return tweets


RSSHUB_BASE_URL = "http://localhost:1200"


def _read_tweets(account: str = None, limit: int = 5) -> str:
    """Read recent AI community posts. Tries Reddit AI subs, Bluesky, RSSHub Twitter, Nitter, then web search."""
    import html as html_mod
    import re as re_mod

    accounts = [account] if account else AI_TWITTER_ACCOUNTS
    all_tweets = []
    source = None

    # === Strategy 0: Reddit AI subreddits (most reliable, always fresh) ===
    if not account:  # Only use Reddit when not looking for a specific account
        for feed_url in REDDIT_AI_FEEDS:
            try:
                # Use urllib (not httpx) — Reddit blocks HTTP/2 Python clients
                import urllib.request
                req = urllib.request.Request(feed_url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; OpenClaw/2.0)"
                })
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status != 200:
                        continue
                    xml = resp.read().decode("utf-8")
                    # Parse Atom entries
                    entries = re_mod.findall(r'<entry>(.*?)</entry>', xml, re_mod.DOTALL)
                    subreddit = re_mod.search(r'/r/(\w+)/', feed_url)
                    sub_name = subreddit.group(1) if subreddit else "reddit"
                    for entry_xml in entries[:limit]:
                        title = ""
                        link = ""
                        updated = ""

                        t = re_mod.search(r'<title[^>]*>(.*?)</title>', entry_xml, re_mod.DOTALL)
                        if t:
                            title = html_mod.unescape(re_mod.sub(r'<[^>]+>', '', t.group(1))).strip()

                        l = re_mod.search(r'<link href="([^"]+)"', entry_xml)
                        if l:
                            link = l.group(1)

                        u = re_mod.search(r'<updated[^>]*>(.*?)</updated>', entry_xml, re_mod.DOTALL)
                        if u:
                            updated = u.group(1).strip()

                        if title and not title.startswith("[D]") and not title.startswith("[P]"):
                            # Skip pure discussion/project threads, keep research/news
                            pass
                        if title:
                            all_tweets.append({
                                "account": f"r/{sub_name}",
                                "text": html_mod.unescape(title),
                                "link": link,
                                "published": updated,
                                "platform": "reddit",
                            })
                if all_tweets:
                    source = "reddit"
            except Exception as e:
                logger.warning(f"Reddit RSS failed for {feed_url}: {e}")

    # === Strategy 1: Bluesky AT Protocol (free, no auth) ===
    if not all_tweets:
        bsky_accounts_to_check = []
        if account:
            bsky_handle = TWITTER_TO_BLUESKY.get(account.lower())
            if bsky_handle:
                bsky_accounts_to_check = [bsky_handle]
            elif account.endswith(".bsky.social"):
                bsky_accounts_to_check = [account]
        else:
            bsky_accounts_to_check = BLUESKY_ACCOUNTS

        for bsky_acct in bsky_accounts_to_check:
            try:
                url = f"{BLUESKY_API}/app.bsky.feed.getAuthorFeed?actor={bsky_acct}&limit={limit}&filter=posts_no_replies"
                with httpx.Client(timeout=10) as client:
                    resp = client.get(url)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    for item in data.get("feed", [])[:limit]:
                        post = item.get("post", {})
                        record = post.get("record", {})
                        author = post.get("author", {})
                        text = record.get("text", "")
                        if not text:
                            continue
                        all_tweets.append({
                            "account": f"@{author.get('handle', bsky_acct)}",
                            "display_name": author.get("displayName", ""),
                            "text": html_mod.unescape(text),
                            "link": f"https://bsky.app/profile/{author.get('handle', bsky_acct)}/post/{post.get('uri', '').split('/')[-1]}",
                            "published": record.get("createdAt", ""),
                            "likes": post.get("likeCount", 0),
                            "reposts": post.get("repostCount", 0),
                            "platform": "bluesky",
                        })
                    if all_tweets:
                        source = "bluesky"
            except Exception as e:
                logger.warning(f"Bluesky failed for {bsky_acct}: {e}")

    # === Strategy 2: Self-hosted RSSHub Twitter (localhost:1200) ===
    if not all_tweets:
        for acct in accounts:
            try:
                url = f"{RSSHUB_BASE_URL}/twitter/user/{acct}"
                with httpx.Client(timeout=15, follow_redirects=True) as client:
                    resp = client.get(url, headers={
                        "User-Agent": "Mozilla/5.0 (compatible; OpenClaw/2.0)"
                    })
                    if resp.status_code == 200 and '<?xml' in resp.text[:100]:
                        tweets = _parse_rss_items(resp.text, acct, limit)
                        if tweets:
                            all_tweets.extend(tweets)
                            source = "rsshub_twitter"
            except Exception as e:
                logger.warning(f"RSSHub failed for @{acct}: {e}")

    # === Strategy 3: Nitter instances (fallback) ===
    if not all_tweets:
        for nitter_url in NITTER_INSTANCES:
            if all_tweets:
                break
            for acct in accounts:
                try:
                    url = f"{nitter_url}/{acct}/rss"
                    with httpx.Client(timeout=10, follow_redirects=True) as client:
                        resp = client.get(url, headers={
                            "User-Agent": "Mozilla/5.0 (compatible; OpenClaw/2.0)"
                        })
                        if resp.status_code != 200:
                            continue
                        tweets = _parse_rss_items(resp.text, acct, limit)
                        if tweets:
                            all_tweets.extend(tweets)
                            source = "nitter"
                except Exception as e:
                    logger.warning(f"Nitter failed for @{acct} from {nitter_url}: {e}")
                    continue

    # === Strategy 4: Web search fallback ===
    if not all_tweets:
        try:
            search_accounts = account or "AnthropicAI OR OpenAI OR GoogleDeepMind"
            search_result = _web_search(f"{search_accounts} AI latest announcement 2026")
            return json.dumps({
                "tweets": [],
                "source": "web_search_fallback",
                "fallback_search": search_result,
                "message": "Reddit, Bluesky, RSSHub, and Nitter unavailable. Used web search fallback.",
            }, indent=2)
        except Exception:
            pass
        return json.dumps({
            "tweets": [],
            "message": "All sources failed (Reddit, Bluesky, RSSHub, Nitter, web search)",
        })

    return json.dumps({
        "tweets": all_tweets,
        "count": len(all_tweets),
        "source": source
    }, indent=2)



# ═══════════════════════════════════════════════════════════════════════════
# NOTION API TOOLS
# ═══════════════════════════════════════════════════════════════════════════

NOTION_API_KEY = os.getenv("NOTION_API_TOKEN")
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_API_VERSION = "2022-06-28"


def _notion_request(method: str, endpoint: str, body: dict = None) -> dict:
    """Make a request to the Notion API."""
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }
    url = f"{NOTION_API_BASE}{endpoint}"

    try:
        if method == "GET":
            response = httpx.get(url, headers=headers, timeout=30)
        elif method == "POST":
            response = httpx.post(url, headers=headers, json=body, timeout=30)
        elif method == "PATCH":
            response = httpx.patch(url, headers=headers, json=body, timeout=30)
        else:
            return {"error": f"Unsupported method: {method}"}

        if response.status_code >= 400:
            return {
                "error": f"Notion API error {response.status_code}",
                "details": response.text[:500]
            }

        return response.json()
    except Exception as e:
        return {"error": f"Notion request failed: {str(e)}"}


def _notion_search(query: str, limit: int = 10) -> str:
    """Search across all Notion content."""
    body = {
        "query": query,
        "page_size": min(limit, 100),
    }

    result = _notion_request("POST", "/search", body)

    if "error" in result:
        return json.dumps(result, indent=2)

    results = result.get("results", [])
    if not results:
        return json.dumps({"message": f"No results found for query: {query}"})

    items = []
    for item in results[:limit]:
        obj_type = item.get("object", "unknown")
        if obj_type == "page":
            title = "Untitled"
            if "properties" in item:
                for prop in item["properties"].values():
                    if prop.get("type") == "title" and prop.get("title"):
                        title = "".join([t.get("plain_text", "") for t in prop["title"]])
                        break
            items.append({
                "type": "page",
                "id": item["id"],
                "title": title,
                "url": item.get("url", "")
            })
        elif obj_type == "database":
            title = "Untitled"
            if "title" in item:
                title = "".join([t.get("plain_text", "") for t in item["title"]])
            items.append({
                "type": "database",
                "id": item["id"],
                "title": title,
                "url": item.get("url", "")
            })

    return json.dumps({"results": items}, indent=2)


def _notion_query(database_id: str, filter_str: str = "", sorts_str: str = "", limit: int = 10) -> str:
    """Query a Notion database with filters and sorting."""
    database_id = database_id.replace("-", "")

    body = {"page_size": min(limit, 100)}

    if filter_str:
        try:
            body["filter"] = json.loads(filter_str)
        except json.JSONDecodeError:
            return json.dumps({"error": f"Invalid filter JSON: {filter_str}"})

    if sorts_str:
        try:
            body["sorts"] = json.loads(sorts_str)
        except json.JSONDecodeError:
            return json.dumps({"error": f"Invalid sorts JSON: {sorts_str}"})

    result = _notion_request("POST", f"/databases/{database_id}/query", body)

    if "error" in result:
        return json.dumps(result, indent=2)

    pages = result.get("results", [])
    items = []

    for page in pages:
        item = {"id": page["id"], "url": page.get("url", "")}
        if "properties" in page:
            for prop_name, prop_value in page["properties"].items():
                prop_type = prop_value.get("type", "unknown")

                if prop_type == "title":
                    title_blocks = prop_value.get("title", [])
                    item[prop_name] = "".join([t.get("plain_text", "") for t in title_blocks])
                elif prop_type == "rich_text":
                    text_blocks = prop_value.get("rich_text", [])
                    item[prop_name] = "".join([t.get("plain_text", "") for t in text_blocks])
                elif prop_type == "select":
                    select_val = prop_value.get("select")
                    item[prop_name] = select_val.get("name") if select_val else None
                elif prop_type == "date":
                    date_val = prop_value.get("date")
                    item[prop_name] = date_val.get("start") if date_val else None
                elif prop_type == "number":
                    item[prop_name] = prop_value.get("number")
                elif prop_type == "checkbox":
                    item[prop_name] = prop_value.get("checkbox")
                else:
                    item[prop_name] = prop_value.get(prop_type, "")

        items.append(item)

    return json.dumps({
        "count": len(items),
        "results": items
    }, indent=2)


def _notion_create_page(database_id: str, properties_str: str, content: str = "") -> str:
    """Create a new page in a Notion database."""
    database_id = database_id.replace("-", "")

    try:
        properties = json.loads(properties_str)
    except json.JSONDecodeError:
        return json.dumps({"error": f"Invalid properties JSON: {properties_str}"})

    body = {
        "parent": {"database_id": database_id},
        "properties": properties,
    }

    if content:
        try:
            body["children"] = json.loads(content)
        except json.JSONDecodeError:
            return json.dumps({"error": f"Invalid content JSON: {content}"})

    result = _notion_request("POST", "/pages", body)

    if "error" in result:
        return json.dumps(result, indent=2)

    return json.dumps({
        "success": True,
        "page_id": result.get("id"),
        "url": result.get("url"),
        "created_at": result.get("created_time"),
    }, indent=2)


def _notion_update_page(page_id: str, properties_str: str) -> str:
    """Update properties on an existing page."""
    page_id = page_id.replace("-", "")

    try:
        properties = json.loads(properties_str)
    except json.JSONDecodeError:
        return json.dumps({"error": f"Invalid properties JSON: {properties_str}"})

    body = {"properties": properties}

    result = _notion_request("PATCH", f"/pages/{page_id}", body)

    if "error" in result:
        return json.dumps(result, indent=2)

    return json.dumps({
        "success": True,
        "page_id": result.get("id"),
        "updated_at": result.get("last_edited_time"),
    }, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# PINCHTAB — Browser Automation for AI Agents
# ═══════════════════════════════════════════════════════════════════════════

PINCHTAB_BASE = os.getenv("PINCHTAB_URL", "http://localhost:9867")


def _pinchtab_request(method: str, path: str, body: dict = None, timeout: int = 30) -> str:
    """Make a request to PinchTab HTTP API."""
    import urllib.request
    url = f"{PINCHTAB_BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = resp.read().decode()
            # Truncate very large responses
            if len(result) > 50000:
                result = result[:50000] + "\n... (truncated)"
            return result
    except urllib.error.URLError as e:
        return json.dumps({"error": f"PinchTab unreachable: {e}. Is pinchtab running? Start with: pinchtab"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _pinchtab_navigate(url: str) -> str:
    """Navigate to a URL and return the snapshot."""
    result = _pinchtab_request("POST", "/navigate", {"url": url})
    # Also grab the snapshot so the agent can see the page
    snapshot = _pinchtab_request("GET", "/snapshot")
    try:
        snap_data = json.loads(snapshot)
        return json.dumps({
            "navigated": url,
            "snapshot_count": snap_data.get("count", 0),
            "snapshot": snap_data.get("tree", snapshot)[:30000],
        }, indent=2)
    except Exception:
        return f"Navigated to {url}. Snapshot: {snapshot[:5000]}"


def _pinchtab_snapshot() -> str:
    """Get accessibility tree snapshot."""
    return _pinchtab_request("GET", "/snapshot")


def _pinchtab_action(action: str, ref: str, value: str = "") -> str:
    """Perform a browser action."""
    body = {"kind": action, "ref": ref}
    if value:
        body["value"] = value
    return _pinchtab_request("POST", "/action", body)


def _pinchtab_text(mode: str = "readability") -> str:
    """Extract text from current page."""
    return _pinchtab_request("GET", f"/text?mode={mode}")


def _pinchtab_screenshot() -> str:
    """Take a screenshot (returns base64 JPEG)."""
    result = _pinchtab_request("GET", "/screenshot")
    return result[:100000]  # Cap at 100KB base64


def _pinchtab_tabs(action: str = "list", url: str = "", tab_id: str = "") -> str:
    """Manage browser tabs."""
    if action == "list":
        return _pinchtab_request("GET", "/tabs")
    elif action == "open":
        return _pinchtab_request("GET", f"/tabs/new?url={url}")
    elif action == "close":
        return _pinchtab_request("GET", f"/tabs/close/{tab_id}")
    return json.dumps({"error": f"Unknown tab action: {action}"})


def _pinchtab_evaluate(script: str) -> str:
    """Execute JavaScript in browser."""
    return _pinchtab_request("POST", "/evaluate", {"expression": script})


# ═══════════════════════════════════════════════════════════════
# PC DISPATCHER — Send tasks to Miles' PC via SSH over Tailscale
# ═══════════════════════════════════════════════════════════════

def _dispatch_pc_code(prompt: str, timeout: int = 300, metadata: dict = None) -> str:
    """Dispatch a Claude Code task to Miles' PC via API Gateway."""
    try:
        import httpx
        url = "http://localhost:18789/api/dispatch/pc"
        payload = {
            "prompt": prompt,
            "timeout": timeout,
            "metadata": metadata or {}
        }
        with httpx.Client(timeout=10) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
    except Exception as e:
        logger.error(f"Error dispatching PC code task via API: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e)
        }, indent=2)


def _dispatch_pc_ollama(prompt: str, model: str = None, timeout: int = 300) -> str:
    """Dispatch an Ollama inference task to Miles' PC via API Gateway."""
    try:
        import httpx
        url = "http://localhost:18789/api/dispatch/ollama"
        payload = {
            "prompt": prompt,
            "timeout": timeout
        }
        if model:
            payload["model"] = model
            
        with httpx.Client(timeout=10) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
    except Exception as e:
        logger.error(f"Error dispatching Ollama task via API: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e)
        }, indent=2)


def _check_pc_health() -> str:
    """Check PC connectivity and availability."""
    try:
        import httpx
        url = "http://localhost:18789/api/dispatch/pc/health"
        with httpx.Client(timeout=20) as client:
            response = client.get(url)
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
    except Exception as e:
        logger.error(f"Error checking PC health via API: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e)
        }, indent=2)


def _get_dispatch_status(job_id: str) -> str:
    """Get status of a dispatched job."""
    try:
        import httpx
        url = f"http://localhost:18789/api/dispatch/status/{job_id}"
        with httpx.Client(timeout=10) as client:
            response = client.get(url)
            if response.status_code == 404:
                return json.dumps({"error": f"Job {job_id} not found"}, indent=2)
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
    except Exception as e:
        logger.error(f"Error getting dispatch status via API: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e)
        }, indent=2)


def _list_dispatch_jobs(status: str = None) -> str:
    """List PC dispatch jobs."""
    try:
        import httpx
        url = "http://localhost:18789/api/dispatch/jobs"
        params = {}
        if status:
            params["status"] = status
        with httpx.Client(timeout=10) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
    except Exception as e:
        logger.error(f"Error listing dispatch jobs via API: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e)
        }, indent=2)


# ═══════════════════════════════════════════════════════════════
# AUTO-TEST RUNNER — Test execution, failure analysis, fix suggestions
# ═══════════════════════════════════════════════════════════════

def _auto_test(action: str, project_path: str, framework: str = "auto",
               test_pattern: str = None, error_output: str = None,
               test_file: str = None) -> str:
    """Auto-Test Runner: Execute tests, analyze failures, suggest fixes."""
    try:
        from auto_test_runner import (
            run_tests, analyze_failure, watch_and_fix, coverage_report
        )
    except ImportError:
        return json.dumps({
            "status": "error",
            "error": "auto_test_runner module not found. Ensure auto_test_runner.py is in ./"
        })

    try:
        if action == "run":
            result = run_tests(project_path, framework, test_pattern, verbose=True)
            return result
        elif action == "analyze":
            if not error_output:
                return json.dumps({
                    "status": "error",
                    "error": "analyze action requires error_output parameter"
                })
            result = analyze_failure(error_output, test_file)
            return result
        elif action == "watch":
            result = watch_and_fix(project_path, framework)
            return result
        elif action == "coverage":
            result = coverage_report(project_path, framework)
            return result
        else:
            return json.dumps({
                "status": "error",
                "error": f"Unknown action: {action}. Use: run, analyze, watch, coverage"
            })
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": f"Auto-test runner error: {str(e)}"
        })


def _propose_tool(
    name: str,
    description: str,
    input_schema: dict,
    implementation: str,
    category: str = "utility"
) -> str:
    """
    Propose a new dynamic tool to the tool factory.
    Validates the tool definition and stores it for approval/execution.
    """
    try:
        from tool_factory import get_factory

        factory = get_factory()

        # Validate tool name (alphanumeric, underscores, hyphens)
        if not re.match(r'^[a-zA-Z0-9_-]+$', name):
            return json.dumps({
                "status": "rejected",
                "reason": "Tool name must contain only alphanumeric characters, underscores, and hyphens"
            })

        # Validate input schema is valid JSON Schema
        if not isinstance(input_schema, dict):
            return json.dumps({
                "status": "rejected",
                "reason": "input_schema must be a valid JSON Schema object"
            })

        # Validate implementation is not empty
        if not implementation or len(implementation.strip()) < 10:
            return json.dumps({
                "status": "rejected",
                "reason": "implementation must be a non-empty Python function body"
            })

        # Check for forbidden patterns in implementation
        forbidden_patterns = [
            r'import\s+os\s*;',
            r'__import__\(',
            r'eval\(',
            r'exec\(',
            r'compile\(',
            r'subprocess\.run.*rm\s+-',
            r'os\.system.*rm\s+-',
            r'internal\s+ip',
            r'127\.0\.0\.1',
            r'localhost',
            r'192\.168\.',
            r'10\.0\.',
        ]

        implementation_lower = implementation.lower()
        for pattern in forbidden_patterns:
            if re.search(pattern, implementation_lower, re.IGNORECASE):
                return json.dumps({
                    "status": "rejected",
                    "reason": f"Implementation contains forbidden pattern: {pattern}"
                })

        # Submit to factory for storage and validation
        tool_def = {
            "name": name,
            "description": description,
            "input_schema": input_schema,
            "implementation": implementation,
            "implementation_type": "python_snippet",  # Must be: shell_command, http_request, python_snippet
            "category": category,
            "proposed_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending_approval"
        }

        # Store in factory (will validate and store to disk)
        # Use "system" as agent_key for API-initiated proposals
        agent_key = "api_user"
        result = factory.propose_tool(agent_key, tool_def)

        return json.dumps({
            "status": "proposed",
            "tool_name": name,
            "message": f"Tool '{name}' proposed and stored for approval",
            "category": category,
            "tool": {
                "name": result.name if hasattr(result, 'name') else name,
                "description": result.description if hasattr(result, 'description') else description
            }
        })

    except Exception as e:
        logger.error(f"Error proposing tool: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e)
        })



# ═══════════════════════════════════════════════════════════════
# FREE CODING TOOLS — Fallback Chain
# ═══════════════════════════════════════════════════════════════

def _aider_build(repo_path: str, prompt: str, model: str = "gemini/gemini-2.5-flash") -> str:
    """Run Aider headless to edit code using specified model."""
    try:
        if not os.path.isdir(repo_path):
            return f"Error: repo_path '{repo_path}' does not exist"

        # Set Gemini API key in environment
        env = os.environ.copy()
        if "GEMINI_API_KEY" not in env:
            env_file = "./.env"
            if os.path.exists(env_file):
                with open(env_file) as f:
                    for line in f:
                        if line.startswith("GEMINI_API_KEY="):
                            key = line.split("=", 1)[1].strip()
                            env["GEMINI_API_KEY"] = key
                            break

        cmd = [
            "aider",
            "--model", model,
            "--no-git",
            "--yes",
            "--message", prompt
        ]

        start = time.time()
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
            cwd=repo_path, env=env
        )
        duration = time.time() - start

        if result.returncode == 0:
            output = result.stdout[:3000] if result.stdout else "Aider completed (no output)"
            return f"Aider completed in {duration:.1f}s.\nModel: {model}\n\nOutput:\n{output}"
        else:
            stderr = result.stderr[:1000] if result.stderr else "no stderr"
            stdout = result.stdout[:1000] if result.stdout else "no stdout"
            return f"Aider failed (exit {result.returncode}, {duration:.1f}s):\nstderr: {stderr}\nstdout: {stdout}"
    except subprocess.TimeoutExpired:
        return "Error: Aider session timed out (10 min limit)"
    except FileNotFoundError:
        return "Error: aider CLI not installed. Install with: pip install aider-install"
    except Exception as e:
        return f"Error running Aider: {e}"


def _gemini_cli_build(repo_path: str, prompt: str) -> str:
    """Run Gemini CLI headless for coding tasks."""
    try:
        if not os.path.isdir(repo_path):
            return f"Error: repo_path '{repo_path}' does not exist"

        # Set Gemini API key in environment
        env = os.environ.copy()
        if "GEMINI_API_KEY" not in env:
            env_file = "./.env"
            if os.path.exists(env_file):
                with open(env_file) as f:
                    for line in f:
                        if line.startswith("GEMINI_API_KEY="):
                            key = line.split("=", 1)[1].strip()
                            env["GEMINI_API_KEY"] = key
                            break

        cmd = [
            "gemini",
            "-p", prompt,
            "--approval-mode", "yolo",
            "-o", "json"
        ]

        start = time.time()
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
            cwd=repo_path, env=env
        )
        duration = time.time() - start

        if result.returncode == 0:
            output = result.stdout[:3000] if result.stdout else "Gemini CLI completed (no output)"
            return f"Gemini CLI completed in {duration:.1f}s.\n\nOutput:\n{output}"
        else:
            stderr = result.stderr[:1000] if result.stderr else "no stderr"
            stdout = result.stdout[:1000] if result.stdout else "no stdout"
            return f"Gemini CLI failed (exit {result.returncode}, {duration:.1f}s):\nstderr: {stderr}\nstdout: {stdout}"
    except subprocess.TimeoutExpired:
        return "Error: Gemini CLI session timed out (10 min limit)"
    except FileNotFoundError:
        return "Error: gemini CLI not installed"
    except Exception as e:
        return f"Error running Gemini CLI: {e}"


def _goose_build(repo_path: str, prompt: str) -> str:
    """Run Goose headless for coding tasks."""
    try:
        if not os.path.isdir(repo_path):
            return f"Error: repo_path '{repo_path}' does not exist"

        cmd = [
            "goose", "run",
            "--text", prompt,
            "--no-session",
            "--output-format", "json"
        ]

        start = time.time()
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
            cwd=repo_path
        )
        duration = time.time() - start

        if result.returncode == 0:
            output = result.stdout[:3000] if result.stdout else "Goose completed (no output)"
            return f"Goose completed in {duration:.1f}s.\n\nOutput:\n{output}"
        else:
            stderr = result.stderr[:1000] if result.stderr else "no stderr"
            stdout = result.stdout[:1000] if result.stdout else "no stdout"
            return f"Goose failed (exit {result.returncode}, {duration:.1f}s):\nstderr: {stderr}\nstdout: {stdout}"
    except subprocess.TimeoutExpired:
        return "Error: Goose session timed out (10 min limit)"
    except FileNotFoundError:
        return "Error: goose CLI not installed"
    except Exception as e:
        return f"Error running Goose: {e}"


def _opencode_build(repo_path: str, prompt: str) -> str:
    """Run OpenCode headless for coding tasks."""
    try:
        if not os.path.isdir(repo_path):
            return f"Error: repo_path '{repo_path}' does not exist"

        cmd = [
            "opencode",
            "-p", prompt,
            "-f", "json",
            "-c", repo_path,
            "-q"
        ]

        start = time.time()
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
            cwd=repo_path
        )
        duration = time.time() - start

        if result.returncode == 0:
            output = result.stdout[:3000] if result.stdout else "OpenCode completed (no output)"
            return f"OpenCode completed in {duration:.1f}s.\n\nOutput:\n{output}"
        else:
            stderr = result.stderr[:1000] if result.stderr else "no stderr"
            stdout = result.stdout[:1000] if result.stdout else "no stdout"
            return f"OpenCode failed (exit {result.returncode}, {duration:.1f}s):\nstderr: {stderr}\nstdout: {stdout}"
    except subprocess.TimeoutExpired:
        return "Error: OpenCode session timed out (10 min limit)"
    except FileNotFoundError:
        return "Error: opencode CLI not installed"
    except Exception as e:
        return f"Error running OpenCode: {e}"


# ═══════════════════════════════════════════════════════════════
# FINANCIAL TRACKING TOOL IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════

def _track_expense(amount: float, category: str, description: str,
                   transaction_type: str = "expense", date: str = None) -> str:
    """Track an expense or income to Supabase finance_transactions table."""
    try:
        from supabase_client import table_insert, is_connected
        from datetime import date as date_class

        if not is_connected():
            return "Error: Supabase connection unavailable"

        # Use provided date or today
        if not date:
            date = str(date_class.today())

        # Validate date format
        try:
            date_class.fromisoformat(date)
        except ValueError:
            return f"Error: Invalid date format. Use YYYY-MM-DD, got: {date}"

        # Prepare transaction record
        transaction = {
            "amount": amount,
            "category": category,
            "description": description,
            "type": transaction_type,
            "date": date,
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        result = table_insert("finance_transactions", transaction)
        if result:
            return f"✓ {transaction_type.capitalize()} tracked: ${amount:.2f} ({category}) - {description}"
        else:
            return "Error: Failed to insert transaction into Supabase"
    except Exception as e:
        return f"Error tracking expense: {e}"


def _financial_summary(period: str = "month") -> str:
    """Get financial summary for a period: income, expenses by category, net."""
    try:
        from supabase_client import table_select
        from datetime import datetime, timedelta, date as date_class

        # Calculate date range based on period
        today = date_class.today()
        if period == "today":
            start_date = today
            end_date = today
        elif period == "week":
            start_date = today - timedelta(days=today.weekday())
            end_date = today
        elif period == "year":
            start_date = date_class(today.year, 1, 1)
            end_date = today
        else:  # month (default)
            start_date = date_class(today.year, today.month, 1)
            # Calculate last day of month
            if today.month == 12:
                end_date = date_class(today.year + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = date_class(today.year, today.month + 1, 1) - timedelta(days=1)

        # Query transactions for the period
        query = f"date=gte.{start_date}&date=lte.{end_date}"
        transactions = table_select("finance_transactions", query=query, limit=1000)

        if not transactions:
            return f"No transactions found for {period}"

        # Aggregate data
        income_total = 0
        expenses_by_category = {}
        expense_total = 0

        for txn in transactions:
            amount = txn.get("amount", 0)
            txn_type = txn.get("type", "expense")
            category = txn.get("category", "other")

            if txn_type == "income":
                income_total += amount
            else:
                expense_total += amount
                if category not in expenses_by_category:
                    expenses_by_category[category] = 0
                expenses_by_category[category] += amount

        # Build summary
        summary_lines = [
            f"Financial Summary ({period}): {start_date} to {end_date}",
            "",
            f"Income:  ${income_total:.2f}",
            f"Expenses: ${expense_total:.2f}",
            f"Net:      ${income_total - expense_total:.2f}",
            ""
        ]

        if expenses_by_category:
            summary_lines.append("Expenses by Category:")
            # Sort by amount descending
            sorted_cats = sorted(expenses_by_category.items(), key=lambda x: x[1], reverse=True)
            for cat, amount in sorted_cats:
                summary_lines.append(f"  {cat}: ${amount:.2f}")

        return "\n".join(summary_lines)

    except Exception as e:
        return f"Error generating financial summary: {e}"


def _invoice_tracker(action: str, client_name: str = None, amount: float = None,
                     status: str = None, invoice_id: str = None) -> str:
    """Track invoices: create, update status, or list outstanding."""
    try:
        from supabase_client import table_insert, table_select, table_update
        from datetime import datetime
        import uuid

        if action == "create":
            if not client_name or not amount:
                return "Error: client_name and amount required for create action"

            # Create invoice record
            invoice = {
                "id": str(uuid.uuid4())[:8],
                "client_name": client_name,
                "amount": amount,
                "status": status or "draft",
                "created_at": datetime.now().isoformat(),
                "due_date": None
            }

            result = table_insert("invoices", invoice)
            if result:
                inv_id = invoice["id"]
                return f"✓ Invoice created: {inv_id} | {client_name} | ${amount:.2f}"
            else:
                return "Error: Failed to create invoice"

        elif action == "update_status":
            if not invoice_id or not status:
                return "Error: invoice_id and status required for update_status action"

            result = table_update("invoices", f"id=eq.{invoice_id}", {"status": status})
            if result:
                return f"✓ Invoice {invoice_id} status updated to: {status}"
            else:
                return f"Error: Invoice {invoice_id} not found or update failed"

        elif action == "list_outstanding":
            # List invoices that are not paid
            query = "status=ne.paid"
            invoices = table_select("invoices", query=query, limit=100)

            if not invoices:
                return "No outstanding invoices"

            lines = ["Outstanding Invoices:"]
            total = 0
            for inv in invoices:
                inv_id = inv.get("id", "?")
                client = inv.get("client_name", "?")
                amount = inv.get("amount", 0)
                stat = inv.get("status", "?")
                total += amount
                lines.append(f"  {inv_id} | {client} | ${amount:.2f} | {stat}")

            lines.append(f"\nTotal Outstanding: ${total:.2f}")
            return "\n".join(lines)

        else:
            return f"Error: Unknown action '{action}'. Use: create, update_status, list_outstanding"

    except Exception as e:
        return f"Error in invoice tracker: {e}"
