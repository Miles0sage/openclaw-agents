"""
OpenClaw Department Definitions
===============================
Specialized agent teams organized by domain. Each department has:
- Curated keywords for routing
- Domain-specific system prompts
- Knowledge loaders that inject focused project context
- File ownership patterns for conflict prevention

Used by autonomous_runner.py to route jobs to the right department
and inject domain-specific context into every pipeline phase.
"""

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Project root mapping (must match autonomous_runner.PROJECT_ROOTS)
PROJECT_ROOTS = {
    "barber-crm": "/root/Barber-CRM/nextjs-app",
    "delhi-palace": "/root/Delhi-Palace",
    "openclaw": "./",
    "prestress-calc": "/root/Mathcad-Scripts",
    "concrete-canoe": "/root/concrete-canoe-project2026",
}


@dataclass
class DepartmentConfig:
    name: str                           # "frontend", "backend", etc.
    primary_agent: str                  # agent key from config.json
    fallback_agent: str | None          # escalation for complex tasks
    keywords: list[str]                 # routing keywords
    file_patterns: list[str]            # glob patterns this dept owns
    system_prompt: str                  # dept-specific instructions
    verify_instruction: str             # dept-specific verification prompt


# ---------------------------------------------------------------------------
# Department system prompts
# ---------------------------------------------------------------------------

_FRONTEND_PROMPT = (
    "You are a Frontend specialist. Only use components from `src/components/ui/` — "
    "NEVER import non-existent components. Follow the dark/gold theme "
    "(`bg-dark-900`, `text-gold-500`). Use `'use client'` for interactive components. "
    "Mobile-first responsive design."
)

_BACKEND_PROMPT = (
    "You are a Backend specialist. `requireAuth()` takes NO arguments — returns "
    "`{authorized, session}` or `{authorized: false, response}`. "
    "`checkRateLimit(ip, maxPerMinute)` returns boolean. Always try Supabase first, "
    "fall back to mock data. Use `NextRequest`/`NextResponse`."
)

_SECURITY_PROMPT = (
    "You are a Security specialist. Check OWASP Top 10. Verify RLS policies. "
    "Validate user input at API boundaries. Report with severity "
    "(Critical/High/Medium/Low) and remediation steps."
)

_DATA_PROMPT = (
    "You are a Data specialist. Surgical SQL precision — verify JOINs produce "
    "correct row counts. Check RLS policies. Never run destructive queries "
    "without confirmation."
)

_DEVOPS_PROMPT = (
    "You are a DevOps specialist. Verify `npm run build` passes before pushing. "
    "Check Vercel deployment status. Manage env vars safely — never commit secrets."
)

_CODE_REVIEW_PROMPT = (
    "You are a Code Review specialist. Read all changed files thoroughly before "
    "commenting. Flag logic errors, missing edge cases, and architectural violations. "
    "Provide actionable feedback with concrete fix suggestions. Don't nitpick style."
)

_DEBUGGING_PROMPT = (
    "You are a Debugging specialist. Build a mental model of the system first. "
    "Identify what changed recently. Trace the execution path. Narrow down the root "
    "cause systematically — don't guess. Check logs, stack traces, and state transitions."
)

# ---------------------------------------------------------------------------
# Verify instructions per department
# ---------------------------------------------------------------------------

_FRONTEND_VERIFY = (
    "Run `npm run build`. Check that no non-existent imports are used. "
    "Verify components render without errors."
)
_BACKEND_VERIFY = (
    "Run `npm run build`. Verify API routes return correct status codes. "
    "Check auth middleware is applied."
)
_SECURITY_VERIFY = "List all findings with severity ratings."
_DATA_VERIFY = "Verify queries return expected row counts. Check RLS policies."
_DEVOPS_VERIFY = "Check deployment status. Verify env vars are set."
_CODE_REVIEW_VERIFY = "Verify all flagged issues have severity ratings and fix suggestions."
_DEBUGGING_VERIFY = "Verify the root cause was identified and the fix addresses it without regressions."


# ---------------------------------------------------------------------------
# Department definitions
# ---------------------------------------------------------------------------

DEPARTMENTS: dict[str, DepartmentConfig] = {
    "frontend": DepartmentConfig(
        name="frontend",
        primary_agent="coder_agent",
        fallback_agent="elite_coder",
        keywords=[
            "page", "component", "ui", "layout", "form", "button", "css",
            "style", "responsive", "dashboard", "landing", "modal", "sidebar",
            "header", "footer", "navigation", "menu", "card", "table",
        ],
        file_patterns=[
            "src/app/**/page.tsx", "src/app/**/layout.tsx", "src/components/**",
        ],
        system_prompt=_FRONTEND_PROMPT,
        verify_instruction=_FRONTEND_VERIFY,
    ),
    "backend": DepartmentConfig(
        name="backend",
        primary_agent="coder_agent",
        fallback_agent="elite_coder",
        keywords=[
            "api", "endpoint", "route", "server", "middleware", "auth",
            "webhook", "integration", "stripe", "vapi", "cron", "handler",
        ],
        file_patterns=[
            "src/app/api/**", "src/lib/**", "src/middleware.ts",
        ],
        system_prompt=_BACKEND_PROMPT,
        verify_instruction=_BACKEND_VERIFY,
    ),
    "security": DepartmentConfig(
        name="security",
        primary_agent="hacker_agent",
        fallback_agent=None,
        keywords=[
            "security", "audit", "xss", "csrf", "injection", "owasp",
            "pentest", "vulnerability", "rls",
        ],
        file_patterns=["**/*.policy.sql"],
        system_prompt=_SECURITY_PROMPT,
        verify_instruction=_SECURITY_VERIFY,
    ),
    "data": DepartmentConfig(
        name="data",
        primary_agent="database_agent",
        fallback_agent=None,
        keywords=[
            "database", "sql", "query", "migration", "schema", "table",
            "index", "supabase", "data", "rls policy",
        ],
        file_patterns=["supabase/**", "migrations/**"],
        system_prompt=_DATA_PROMPT,
        verify_instruction=_DATA_VERIFY,
    ),
    "devops": DepartmentConfig(
        name="devops",
        primary_agent="project_manager",
        fallback_agent="elite_coder",
        keywords=[
            "deploy", "vercel", "ci", "cd", "build", "package", "config",
            "docker", "systemd", "infrastructure",
        ],
        file_patterns=[
            "vercel.json", "package.json", "next.config.*", ".github/**",
        ],
        system_prompt=_DEVOPS_PROMPT,
        verify_instruction=_DEVOPS_VERIFY,
    ),
    "code_review": DepartmentConfig(
        name="code_review",
        primary_agent="code_reviewer",
        fallback_agent="elite_coder",
        keywords=[
            "review", "pr", "pull request", "audit", "code smell", "technical debt",
            "code quality", "lint", "best practice", "pattern", "anti-pattern",
        ],
        file_patterns=["**/*.ts", "**/*.tsx", "**/*.py", "**/*.js"],
        system_prompt=_CODE_REVIEW_PROMPT,
        verify_instruction=_CODE_REVIEW_VERIFY,
    ),
    "debugging": DepartmentConfig(
        name="debugging",
        primary_agent="debugger",
        fallback_agent="elite_coder",
        keywords=[
            "bug", "error", "crash", "race condition", "leak", "stack trace",
            "debug", "broken", "failing", "exception", "traceback", "segfault",
        ],
        file_patterns=["**/*.log", "**/*.py", "**/*.ts"],
        system_prompt=_DEBUGGING_PROMPT,
        verify_instruction=_DEBUGGING_VERIFY,
    ),
}

# Reverse mapping: agent_pref -> department name
AGENT_TO_DEPARTMENT = {
    "coder_agent": "backend",       # safe default for generic coder tasks
    "elite_coder": "backend",
    "hacker_agent": "security",
    "database_agent": "data",
    "project_manager": "devops",
    "code_reviewer": "code_review",
    "architecture_designer": "backend",  # no dedicated dept, routes through backend
    "test_generator": "backend",          # same — tests route through backend
    "debugger": "debugging",
}


# ---------------------------------------------------------------------------
# Knowledge loaders — one per department
# ---------------------------------------------------------------------------

def _read_file_safe(path: str, max_chars: int = 3000) -> str:
    """Read a file, return empty string on failure."""
    try:
        with open(path, "r") as f:
            return f.read()[:max_chars]
    except Exception:
        return ""


def _list_dir_safe(path: str) -> list[str]:
    """List directory contents, return empty list on failure."""
    try:
        return os.listdir(path)
    except Exception:
        return []


def _discover_ui_components(root: str) -> str:
    """List available UI components for a Next.js project."""
    ui_dir = os.path.join(root, "src", "components", "ui")
    if not os.path.isdir(ui_dir):
        return ""
    components = [
        f.replace(".tsx", "").replace(".ts", "")
        for f in _list_dir_safe(ui_dir)
        if f.endswith((".tsx", ".ts")) and not f.startswith("_")
    ]
    if not components:
        return ""
    return (
        f"AVAILABLE UI COMPONENTS in @/components/ui/: {', '.join(sorted(components))}\n"
        f"IMPORTANT: Only import from components that exist in this list."
    )


def _discover_page_routes(root: str) -> str:
    """List page routes for a Next.js app router project."""
    app_dir = os.path.join(root, "src", "app")
    if not os.path.isdir(app_dir):
        return ""
    routes = []
    for dirpath, _, filenames in os.walk(app_dir):
        if "page.tsx" in filenames or "page.ts" in filenames:
            rel = os.path.relpath(dirpath, app_dir)
            route = "/" if rel == "." else f"/{rel}"
            routes.append(route)
    if not routes:
        return ""
    return f"PAGE ROUTES: {', '.join(sorted(routes))}"


def _discover_api_routes(root: str) -> str:
    """List API routes for a Next.js project."""
    api_dir = os.path.join(root, "src", "app", "api")
    if not os.path.isdir(api_dir):
        return ""
    routes = []
    for dirpath, _, filenames in os.walk(api_dir):
        if "route.ts" in filenames or "route.tsx" in filenames:
            rel = os.path.relpath(dirpath, os.path.join(root, "src", "app"))
            routes.append(f"/{rel}")
    if not routes:
        return ""
    return f"API ROUTES: {', '.join(sorted(routes))}"


def _discover_tailwind_tokens(root: str) -> str:
    """Extract key color tokens from tailwind config."""
    for name in ("tailwind.config.ts", "tailwind.config.js"):
        path = os.path.join(root, name)
        content = _read_file_safe(path, max_chars=2000)
        if content:
            return f"TAILWIND CONFIG (key colors/theme):\n{content[:1500]}"
    return ""


def _get_git_log(root: str, count: int = 3) -> str:
    """Get recent git log entries."""
    try:
        result = subprocess.run(
            ["git", "-C", root, "log", f"-{count}", "--oneline"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return f"RECENT COMMITS:\n{result.stdout.strip()}"
    except Exception:
        pass
    return ""


def _read_claude_md(root: str) -> str:
    """Read project CLAUDE.md."""
    return _read_file_safe(os.path.join(root, "CLAUDE.md"), max_chars=3000)


# OWASP Top 10 checklist (compact)
_OWASP_CHECKLIST = """OWASP TOP 10 CHECKLIST:
1. Broken Access Control — verify auth on every endpoint, check RLS
2. Cryptographic Failures — no secrets in code, HTTPS everywhere
3. Injection — parameterize all queries, sanitize user input
4. Insecure Design — check business logic flaws
5. Security Misconfiguration — review headers, CORS, error messages
6. Vulnerable Components — check outdated dependencies
7. Auth Failures — verify session management, password policies
8. Data Integrity — validate all inputs, check CSRF tokens
9. Logging Failures — ensure security events are logged
10. SSRF — validate URLs, restrict outbound requests"""


def load_frontend_knowledge(project: str) -> str:
    """Load frontend-specific context for a project."""
    root = PROJECT_ROOTS.get(project, "")
    if not root:
        return ""

    parts = []
    claude_md = _read_claude_md(root)
    if claude_md:
        parts.append(f"PROJECT GUIDE:\n{claude_md}")

    components = _discover_ui_components(root)
    if components:
        parts.append(components)

    routes = _discover_page_routes(root)
    if routes:
        parts.append(routes)

    tokens = _discover_tailwind_tokens(root)
    if tokens:
        parts.append(tokens)

    return "\n\n".join(parts)


def load_backend_knowledge(project: str) -> str:
    """Load backend-specific context for a project."""
    root = PROJECT_ROOTS.get(project, "")
    if not root:
        return ""

    parts = []
    claude_md = _read_claude_md(root)
    if claude_md:
        parts.append(f"PROJECT GUIDE:\n{claude_md}")

    api_routes = _discover_api_routes(root)
    if api_routes:
        parts.append(api_routes)

    # Read key backend files (signatures only)
    for rel_path in ("src/lib/require-auth.ts", "src/lib/rate-limit.ts"):
        content = _read_file_safe(os.path.join(root, rel_path), max_chars=500)
        if content:
            parts.append(f"FILE {rel_path}:\n{content}")

    # Mock data exports
    mock_path = os.path.join(root, "src", "lib", "mock-data.ts")
    mock_content = _read_file_safe(mock_path, max_chars=1000)
    if mock_content:
        parts.append(f"MOCK DATA EXPORTS:\n{mock_content}")

    return "\n\n".join(parts)


def load_security_knowledge(project: str) -> str:
    """Load security-specific context for a project."""
    root = PROJECT_ROOTS.get(project, "")
    parts = [_OWASP_CHECKLIST]

    if root:
        claude_md = _read_claude_md(root)
        if claude_md:
            parts.append(f"PROJECT GUIDE:\n{claude_md}")

        # Auth middleware pattern
        for rel_path in ("src/lib/require-auth.ts", "src/middleware.ts"):
            content = _read_file_safe(os.path.join(root, rel_path), max_chars=500)
            if content:
                parts.append(f"AUTH PATTERN ({rel_path}):\n{content}")

    return "\n\n".join(parts)


def load_data_knowledge(project: str) -> str:
    """Load data/database-specific context for a project."""
    root = PROJECT_ROOTS.get(project, "")
    if not root:
        return ""

    parts = []
    claude_md = _read_claude_md(root)
    if claude_md:
        parts.append(f"PROJECT GUIDE:\n{claude_md}")

    # Supabase client / query patterns
    for rel_path in ("src/lib/supabase.ts", "src/lib/supabase-client.ts"):
        content = _read_file_safe(os.path.join(root, rel_path), max_chars=1500)
        if content:
            parts.append(f"SUPABASE CLIENT ({rel_path}):\n{content}")
            break

    # Schema / migrations
    migrations_dir = os.path.join(root, "supabase", "migrations")
    if os.path.isdir(migrations_dir):
        files = sorted(_list_dir_safe(migrations_dir))[-3:]  # last 3 migrations
        for fname in files:
            content = _read_file_safe(os.path.join(migrations_dir, fname), max_chars=800)
            if content:
                parts.append(f"MIGRATION {fname}:\n{content}")

    return "\n\n".join(parts)


def load_devops_knowledge(project: str) -> str:
    """Load devops-specific context for a project."""
    root = PROJECT_ROOTS.get(project, "")
    if not root:
        return ""

    parts = []

    # package.json scripts
    pkg = _read_file_safe(os.path.join(root, "package.json"), max_chars=2000)
    if pkg:
        parts.append(f"PACKAGE.JSON:\n{pkg}")

    # vercel.json
    vercel = _read_file_safe(os.path.join(root, "vercel.json"), max_chars=1000)
    if vercel:
        parts.append(f"VERCEL CONFIG:\n{vercel}")

    # Recent git log
    git_log = _get_git_log(root, count=3)
    if git_log:
        parts.append(git_log)

    return "\n\n".join(parts)


def load_code_review_knowledge(project: str) -> str:
    """Load code review context for a project."""
    root = PROJECT_ROOTS.get(project, "")
    if not root:
        return ""
    parts = []
    claude_md = _read_claude_md(root)
    if claude_md:
        parts.append(f"PROJECT GUIDE:\n{claude_md}")
    git_log = _get_git_log(root, count=10)
    if git_log:
        parts.append(git_log)
    return "\n\n".join(parts)


def load_debugging_knowledge(project: str) -> str:
    """Load debugging context for a project."""
    root = PROJECT_ROOTS.get(project, "")
    if not root:
        return ""
    parts = []
    claude_md = _read_claude_md(root)
    if claude_md:
        parts.append(f"PROJECT GUIDE:\n{claude_md}")
    git_log = _get_git_log(root, count=5)
    if git_log:
        parts.append(git_log)
    return "\n\n".join(parts)


# Map department name -> knowledge loader function
KNOWLEDGE_LOADERS = {
    "frontend": load_frontend_knowledge,
    "backend": load_backend_knowledge,
    "security": load_security_knowledge,
    "data": load_data_knowledge,
    "devops": load_devops_knowledge,
    "code_review": load_code_review_knowledge,
    "debugging": load_debugging_knowledge,
}


def load_department_knowledge(department: str, project: str) -> str:
    """Load knowledge for a department + project combination."""
    loader = KNOWLEDGE_LOADERS.get(department)
    if not loader:
        return ""
    return loader(project)
