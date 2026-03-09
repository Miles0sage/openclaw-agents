"""
Agent Tool Profiles — per-agent tool allowlists for multi-agent delegation.

Each agent gets a filtered set of tools based on their role. When an agent
executes a step, only tools in its allowlist are available. This prevents
accidental misuse (e.g., the research agent deploying to Vercel).

If an agent has no profile entry, it gets unrestricted access (None).
"""

from typing import Optional, Set

# Per-agent tool allowlists.
# Keys match agent keys in config.json / AGENT_MAP.
# Values are sets of tool names from agent_tools.AGENT_TOOLS.
AGENT_TOOL_PROFILES: dict[str, set[str]] = {
    "project_manager": {
        "recall_memory",
        "file_read", "glob_files", "grep_search",
        "web_search", "web_fetch", "web_scrape", "research_task",
        "github_repo_info", "github_create_issue",
        "claude_code_build", "claude_code_github_issue",
        "codex_build", "codex_query", "codex_github_issue",
        # free coding tools (fallback chain)
        "aider_build", "gemini_cli_build", "goose_build", "opencode_build",
        "create_job", "list_jobs", "approve_job",
        "create_proposal", "get_cost_summary", "get_events",
        "send_slack_message", "email_triage",
        "save_memory", "search_memory",
        # daily briefing
        "plan_my_day", "morning_briefing",
        # financial tracking and document processing
        "track_expense", "financial_summary", "invoice_tracker", "process_document",
        # utility tools (safe for all agents)
        "compute_math", "compute_stats", "compute_sort", "compute_search",
        "compute_hash", "compute_convert", "compute_matrix", "compute_prime",
    },
    "coder_agent": {
        "shell_execute", "git_operations",
        "file_read", "file_write", "file_edit",
        "glob_files", "grep_search",
        "install_package", "process_manage", "env_manage", "auto_test",
        # free coding tools (cheap fallbacks)
        "aider_build", "gemini_cli_build",
        # utility tools (safe for all agents)
        "compute_math", "compute_stats", "compute_sort", "compute_search",
        "compute_hash", "compute_convert", "compute_matrix", "compute_prime",
    },
    "elite_coder": {
        "shell_execute", "git_operations",
        "file_read", "file_write", "file_edit",
        "glob_files", "grep_search",
        "install_package", "process_manage", "env_manage",
        "vercel_deploy", "auto_test",
        "claude_code_build", "codex_build",
        # free coding tools (fallback chain)
        "aider_build", "gemini_cli_build", "goose_build", "opencode_build",
        # utility tools (safe for all agents)
        "compute_math", "compute_stats", "compute_sort", "compute_search",
        "compute_hash", "compute_convert", "compute_matrix", "compute_prime",
    },
    "hacker_agent": {
        "shell_execute",
        "file_read", "glob_files", "grep_search",
        "web_search", "web_fetch", "web_scrape",
        "github_repo_info",
        # utility tools (safe for all agents)
        "compute_math", "compute_stats", "compute_sort", "compute_search",
        "compute_hash", "compute_convert", "compute_matrix", "compute_prime",
    },
    "database_agent": {
        "shell_execute",
        "file_read", "file_write",
        "glob_files", "grep_search",
        # utility tools (safe for all agents)
        "compute_math", "compute_stats", "compute_sort", "compute_search",
        "compute_hash", "compute_convert", "compute_matrix", "compute_prime",
    },
    "research_agent": {
        "web_search", "web_fetch", "web_scrape", "research_task",
        "file_read", "glob_files", "grep_search",
        "save_memory", "search_memory",
        "github_repo_info",
        # utility tools (safe for all agents)
        "compute_math", "compute_stats", "compute_sort", "compute_search",
        "compute_hash", "compute_convert", "compute_matrix", "compute_prime",
    },
    "code_reviewer": {
        "file_read", "glob_files", "grep_search",
        "git_operations", "auto_test",
        "github_repo_info", "codex_query",
        # utility tools (safe for all agents)
        "compute_math", "compute_stats", "compute_sort", "compute_search",
        "compute_hash", "compute_convert", "compute_matrix", "compute_prime",
    },
    "test_generator": {
        "shell_execute", "git_operations",
        "file_read", "file_write", "file_edit",
        "glob_files", "grep_search",
        "process_manage", "auto_test",
        # utility tools (safe for all agents)
        "compute_math", "compute_stats", "compute_sort", "compute_search",
        "compute_hash", "compute_convert", "compute_matrix", "compute_prime",
    },
    "debugger": {
        "shell_execute", "git_operations",
        "file_read", "file_write", "file_edit",
        "glob_files", "grep_search",
        "process_manage", "env_manage", "auto_test",
        # utility tools (safe for all agents)
        "compute_math", "compute_stats", "compute_sort", "compute_search",
        "compute_hash", "compute_convert", "compute_matrix", "compute_prime",
    },
    "architecture_designer": {
        "file_read", "glob_files", "grep_search",
        "web_search", "web_fetch", "research_task",
        "github_repo_info",
        # utility tools (safe for all agents)
        "compute_math", "compute_stats", "compute_sort", "compute_search",
        "compute_hash", "compute_convert", "compute_matrix", "compute_prime",
    },
    "researcher": {
        "recall_memory",
        "web_search", "web_fetch", "web_scrape", "research_task",
        "deep_research", "perplexity_research",
        "file_read", "file_write",
        "save_memory", "search_memory",
        "notion_search", "notion_query",
        # utility tools (safe for all agents)
        "compute_math", "compute_stats", "compute_sort", "compute_search",
        "compute_hash", "compute_convert", "compute_matrix", "compute_prime",
    },
    "content_creator": {
        "file_read", "file_write",
        "web_search", "web_fetch",
        "save_memory", "search_memory",
        "notion_search", "notion_query", "notion_create_page", "notion_update_page",
        # utility tools (safe for all agents)
        "compute_math", "compute_stats", "compute_sort", "compute_search",
        "compute_hash", "compute_convert", "compute_matrix", "compute_prime",
    },
    "financial_analyst": {
        "file_read", "file_write",
        "web_search", "web_fetch",
        "save_memory", "search_memory",
        "notion_search", "notion_query", "notion_create_page", "notion_update_page",
        # daily briefing
        "morning_briefing",
        # financial tracking tools
        "track_expense", "financial_summary", "invoice_tracker", "process_document",
        "compute_math", "compute_stats", "compute_sort", "compute_search",
        "compute_hash", "compute_convert", "compute_matrix", "compute_prime",
    },
    # trading_agent: crypto, prediction markets, options trading
    "trading_agent": {
        "kalshi_markets", "kalshi_portfolio", "kalshi_trade",
        "polymarket_monitor", "polymarket_portfolio", "polymarket_prices", "polymarket_trade",
        "trading_safety", "trading_strategies",
        "money_engine", "prediction_market", "prediction_tracker",
        "arb_scanner", "betting_brain", "sportsbook_odds", "sportsbook_arb",
        "sports_predict", "sports_betting", "bet_tracker",
        "file_read", "file_write", "recall_memory",
        "web_search", "web_fetch",
        "save_memory", "search_memory",
        "compute_math", "compute_stats", "compute_sort", "compute_search",
        "compute_hash", "compute_convert", "compute_matrix", "compute_prime",
        "kalshi_markets", "kalshi_portfolio", "kalshi_trade",
        "polymarket_monitor", "polymarket_portfolio", "polymarket_prices", "polymarket_trade",
        "trading_safety", "trading_strategies",
        "money_engine", "prediction_market", "prediction_tracker",
        "arb_scanner",
        "file_read", "file_write",
        "web_search", "web_fetch",
        "save_memory", "search_memory",
        "compute_math", "compute_stats", "compute_sort", "compute_search",
        "compute_hash", "compute_convert", "compute_matrix", "compute_prime",
    },
    # betting_agent: sports analytics, EV, arb, Kelly sizing
    # sales_agent: lead gen, prospecting, proposal creation
    "sales_agent": {
        "recall_memory",
        "find_leads", "sales_call", "generate_proposal",
        "file_read", "file_write",
        "web_search", "web_fetch",
        "save_memory", "search_memory",
        "send_slack_message", "send_sms",
        "compute_math", "compute_stats",
    },
    # browser_agent: web interaction, automation, scraping
    "browser_agent": {
        "recall_memory",
        "browser_navigate", "browser_screenshot", "browser_snapshot",
        "browser_action", "browser_evaluate", "browser_tabs", "browser_text",
        "web_search", "web_fetch", "web_scrape",
        "file_read", "file_write",
        "save_memory", "search_memory",
        "compute_math", "compute_stats",
    },
    # overseer: full system control, admin only
    "overseer": {
        "recall_memory",
        "tmux_agents", "manage_reactions", "env_manage", "process_manage",
        "kill_job", "agency_status", "plan_my_day", "morning_briefing",
        "create_event", "blackboard_read", "blackboard_write",
        "flush_memory_before_compaction", "rebuild_semantic_index", "get_reflections",
        "read_ai_news", "read_tweets", "security_scan", "send_sms", "sms_history",
        # Claude Code headless (expensive — Opus only)
        "claude_headless",
        # Codex CLI (GPT-5) — dual AI factory
        "codex_build", "codex_query", "codex_github_issue",
        # Free coding tools (fallback chain)
        "aider_build", "gemini_cli_build", "goose_build", "opencode_build",
        # PC dispatch tools (SSH to Miles' Windows PC)
        "dispatch_pc_code", "dispatch_pc_ollama", "check_pc_health", "get_dispatch_status", "list_dispatch_jobs",
        # Notion tools
        "notion_search", "notion_query", "notion_create_page", "notion_update_page",
        # financial tracking and document processing
        "track_expense", "financial_summary", "invoice_tracker", "process_document",
        # can also use general tools
        "file_read", "file_write", "file_edit",
        "shell_execute", "git_operations",
        "web_search", "web_fetch", "web_scrape",
        "create_job", "list_jobs", "approve_job", "create_proposal",
        "get_cost_summary", "get_events", "send_slack_message", "email_triage",
        "save_memory", "search_memory",
        "github_repo_info", "github_create_issue",
        "glob_files", "grep_search", "install_package",
        "compute_math", "compute_stats", "compute_sort", "compute_search",
        "compute_hash", "compute_convert", "compute_matrix", "compute_prime",
    },
}


def get_tools_for_agent(agent_key: str) -> Optional[Set[str]]:
    """Return the tool allowlist for an agent, or None if unrestricted."""
    return AGENT_TOOL_PROFILES.get(agent_key)


def is_tool_allowed(agent_key: str, tool_name: str) -> bool:
    """Check if a specific tool is allowed for an agent. Returns True if unrestricted."""
    allowlist = AGENT_TOOL_PROFILES.get(agent_key)
    if allowlist is None:
        return True  # unrestricted
    return tool_name in allowlist


def get_available_agents() -> list[str]:
    """Return all agent keys that have tool profiles defined."""
    return list(AGENT_TOOL_PROFILES.keys())
