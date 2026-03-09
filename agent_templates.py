"""
Agent Templates — Structured agent definitions for OpenClaw.

Replaces ad-hoc routing with typed templates that define each agent's
capabilities, constraints, model preferences, and failure recovery strategy.

Templates are used by autonomous_runner.py for:
- Model fallback chain ordering
- Failure recovery strategy selection
- Cost caps per job
- Tool access control
"""

import logging
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("agent_templates")


@dataclass
class AgentTemplate:
    name: str                           # "CodeGen Pro"
    role: str                           # "Developer"
    model_preference: list[str] = field(default_factory=list)  # ordered fallback chain
    tools_allowed: list[str] = field(default_factory=list)     # tool names this agent can use
    memory_access: str = "read_write"   # "read_only" | "read_write" | "none"
    max_cost_per_job: float = 0.05      # USD budget cap
    success_criteria: str = ""          # what "done" means
    failure_recovery: str = "retry_with_diagnosis"  # "retry_with_diagnosis" | "escalate" | "skip"
    system_prompt: str = ""             # agent persona/soul prompt
    department: str = "backend"         # default department

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Template Registry
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, AgentTemplate] = {

    "codegen_pro": AgentTemplate(
        name="CodeGen Pro",
        role="Developer",
        model_preference=["gemini-2.5-flash", "grok-3-mini", "MiniMax-M2.5"],
        tools_allowed=[
            "shell_execute", "git_operations", "file_read", "file_write", "file_edit",
            "glob_files", "grep_search", "install_package", "process_manage",
        ],
        memory_access="read_write",
        max_cost_per_job=0.05,
        success_criteria="Code compiles, tests pass, no regressions",
        failure_recovery="retry_with_diagnosis",
        system_prompt=(
            "You are CodeGen Pro — a fast, reliable developer agent. "
            "Write clean code that works on first deploy. Test before calling it done. "
            "If a task is above your weight class (multi-file architecture), flag it for escalation."
        ),
        department="backend",
    ),

    "codegen_elite": AgentTemplate(
        name="CodeGen Elite",
        role="Complex Developer",
        model_preference=["MiniMax-M2.5", "grok-3", "gemini-2.5-pro"],
        tools_allowed=[
            "shell_execute", "git_operations", "file_read", "file_write", "file_edit",
            "glob_files", "grep_search", "install_package", "process_manage",
            "research_task", "web_search",
        ],
        memory_access="read_write",
        max_cost_per_job=0.50,
        success_criteria="Complex refactor complete, all tests pass, no regressions, architecture documented",
        failure_recovery="retry_with_diagnosis",
        system_prompt=(
            "You are CodeGen Elite — you handle tasks that break other coding agents. "
            "Multi-file refactors, system redesigns, algorithm implementations. "
            "Think before you code. Read existing architecture. Write code that fits."
        ),
        department="backend",
    ),

    "pentest_ai": AgentTemplate(
        name="Pentest AI",
        role="Security Analyst",
        model_preference=["grok-3-mini", "gemini-2.5-flash"],
        tools_allowed=[
            "file_read", "glob_files", "grep_search", "shell_execute",
            "web_search", "web_fetch",
        ],
        memory_access="read_only",
        max_cost_per_job=0.10,
        success_criteria="All OWASP Top 10 checked, vulnerabilities listed with severity and remediation",
        failure_recovery="escalate",
        system_prompt=(
            "You are Pentest AI — find vulnerabilities before attackers do. "
            "Simulate what a motivated attacker would try. Report with severity "
            "(Critical/High/Medium/Low) and specific remediation steps."
        ),
        department="security",
    ),

    "database_agent": AgentTemplate(
        name="SupabaseConnector",
        role="Data Specialist",
        model_preference=["gemini-2.5-flash", "grok-3-mini"],
        tools_allowed=[
            "file_read", "glob_files", "grep_search", "shell_execute",
        ],
        memory_access="read_only",
        max_cost_per_job=0.20,
        success_criteria="Queries return correct data, RLS policies verified, no data leaks",
        failure_recovery="escalate",
        system_prompt=(
            "You are SupabaseConnector — surgical SQL precision. "
            "Verify JOINs produce correct row counts. Check RLS policies. "
            "Never run destructive queries without confirmation."
        ),
        department="data",
    ),

    "code_reviewer": AgentTemplate(
        name="Code Reviewer",
        role="PR & Code Audit",
        model_preference=["gemini-2.5-flash", "grok-3-mini"],
        tools_allowed=[
            "file_read", "glob_files", "grep_search",
        ],
        memory_access="read_only",
        max_cost_per_job=0.05,
        success_criteria="All changed files reviewed, issues listed with severity and fix suggestions",
        failure_recovery="skip",
        system_prompt=(
            "You are Code Reviewer — catch logic errors, missing edge cases, "
            "and architectural violations. Provide actionable feedback with concrete fixes."
        ),
        department="code_review",
    ),

    "test_generator": AgentTemplate(
        name="Test Generator",
        role="Testing & QA",
        model_preference=["gemini-2.5-flash", "grok-3-mini"],
        tools_allowed=[
            "shell_execute", "file_read", "file_write", "file_edit",
            "glob_files", "grep_search",
        ],
        memory_access="read_only",
        max_cost_per_job=0.05,
        success_criteria="Tests cover happy path + edge cases, all tests pass",
        failure_recovery="retry_with_diagnosis",
        system_prompt=(
            "You are Test Generator — think about how code breaks, not how it works. "
            "Write tests that catch regressions and exercise error paths."
        ),
        department="backend",
    ),

    "debugger": AgentTemplate(
        name="Debugger",
        role="Deep Debugging",
        model_preference=["grok-3", "MiniMax-M2.5", "gemini-2.5-pro"],
        tools_allowed=[
            "shell_execute", "file_read", "glob_files", "grep_search",
            "process_manage",
        ],
        memory_access="read_write",
        max_cost_per_job=1.00,
        success_criteria="Root cause identified, fix verified, no regressions",
        failure_recovery="escalate",
        system_prompt=(
            "You are Debugger — called when nobody else can figure out why it's broken. "
            "Build a mental model, identify what changed, trace execution, narrow root cause."
        ),
        department="debugging",
    ),

    "project_manager": AgentTemplate(
        name="Overseer",
        role="PM / Coordinator",
        model_preference=["gemini-2.5-flash", "grok-3-mini"],
        tools_allowed=[
            "file_read", "glob_files", "grep_search", "shell_execute",
            "git_operations", "web_search", "send_slack_message",
        ],
        memory_access="read_write",
        max_cost_per_job=0.30,
        success_criteria="Task decomposed, routed correctly, verified before delivery",
        failure_recovery="retry_with_diagnosis",
        system_prompt=(
            "You are Overseer — decompose objectives, route to the right agent, "
            "track execution, verify results, manage budget."
        ),
        department="devops",
    ),

    "architecture_designer": AgentTemplate(
        name="Architecture Designer",
        role="System Design",
        model_preference=["MiniMax-M2.5", "grok-3", "gemini-2.5-pro"],
        tools_allowed=[
            "file_read", "glob_files", "grep_search", "web_search",
        ],
        memory_access="read_only",
        max_cost_per_job=0.50,
        success_criteria="Design documented with trade-offs, API contracts defined, migration path clear",
        failure_recovery="escalate",
        system_prompt=(
            "You are Architecture Designer — think in systems, not features. "
            "Map blast radius before anyone writes code. Consider scale, "
            "maintainability, and migration paths."
        ),
        department="backend",
    ),

    "researcher": AgentTemplate(
        name="Researcher",
        role="Deep Research",
        model_preference=["gemini-2.5-flash", "grok-3-mini"],
        tools_allowed=[
            "web_search", "web_fetch", "web_scrape", "research_task",
            "deep_research", "perplexity_research",
            "file_read", "glob_files", "grep_search",
            "save_memory", "search_memory",
            "notion_search", "notion_query",
        ],
        memory_access="read_write",
        max_cost_per_job=0.15,
        success_criteria="Structured report with citations, contradictions flagged, confidence scores included",
        failure_recovery="retry_with_diagnosis",
        system_prompt=(
            "You are Researcher — decompose complex questions into sub-questions, "
            "research each in parallel, synthesize findings into structured reports with citations. "
            "Flag uncertainty. Never present opinions as facts."
        ),
        department="research",
    ),
}

# Mapping from agent keys used in autonomous_runner.py AGENT_MAP
_AGENT_KEY_TO_TEMPLATE = {
    "project_manager": "project_manager",
    "coder_agent": "codegen_pro",
    "elite_coder": "codegen_elite",
    "hacker_agent": "pentest_ai",
    "database_agent": "database_agent",
    "code_reviewer": "code_reviewer",
    "test_generator": "test_generator",
    "debugger": "debugger",
    "architecture_designer": "architecture_designer",
    "researcher": "researcher",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_template(agent_key: str) -> AgentTemplate | None:
    """Get template by agent key (as used in autonomous_runner.py).

    Accepts both template names ('codegen_pro') and agent keys ('coder_agent').
    """
    # Direct template name match
    if agent_key in TEMPLATES:
        return TEMPLATES[agent_key]

    # Agent key -> template mapping
    template_name = _AGENT_KEY_TO_TEMPLATE.get(agent_key)
    if template_name and template_name in TEMPLATES:
        return TEMPLATES[template_name]

    return None


def get_template_for_task(task_type: str) -> AgentTemplate:
    """Map task signals to the best agent template.

    Task type examples: "simple_code_fix", "complex_refactor", "security_audit", etc.
    Falls back to codegen_pro for unrecognized tasks.
    """
    mapping = {
        # Simple tasks
        "simple_code_fix": "codegen_pro",
        "bug_fix": "codegen_pro",
        "feature": "codegen_pro",
        "api_endpoint": "codegen_pro",
        "css": "codegen_pro",
        "component": "codegen_pro",

        # Complex tasks
        "complex_refactor": "codegen_elite",
        "architecture": "codegen_elite",
        "multi_file": "codegen_elite",
        "system_design": "architecture_designer",

        # Security
        "security_audit": "pentest_ai",
        "pentest": "pentest_ai",
        "vulnerability": "pentest_ai",

        # Data
        "database": "database_agent",
        "sql": "database_agent",
        "migration": "database_agent",

        # Review & test
        "code_review": "code_reviewer",
        "pr_review": "code_reviewer",
        "testing": "test_generator",
        "test_writing": "test_generator",

        # Debugging
        "debug": "debugger",
        "race_condition": "debugger",

        # Research
        "research": "researcher",
        "news_synthesis": "researcher",
        "due_diligence": "researcher",
        "market_research": "researcher",
        "competitor_analysis": "researcher",

        # Planning
        "planning": "project_manager",
        "decomposition": "project_manager",
    }

    template_name = mapping.get(task_type, "codegen_pro")
    return TEMPLATES[template_name]


def get_failure_recovery(agent_key: str) -> str:
    """Get the failure recovery strategy for an agent.

    Returns: "retry_with_diagnosis" | "escalate" | "skip"
    """
    template = get_template(agent_key)
    if template:
        return template.failure_recovery
    return "retry_with_diagnosis"  # safe default


def get_model_preference(agent_key: str) -> list[str]:
    """Get the ordered model preference list for an agent."""
    template = get_template(agent_key)
    if template:
        return template.model_preference
    return ["gemini-2.5-flash", "grok-3-mini", "MiniMax-M2.5"]  # default chain
