
import sys
import os

# Add current directory to path to import agent_tool_profiles
sys.path.append('.')
from agent_tool_profiles import AGENT_TOOL_PROFILES

# List of tools from agent_tools.py (extracted via grep)
all_tools = [
    "agency_status", "approve_job", "arb_scanner", "auto_test", "betting_brain",
    "bet_tracker", "blackboard_read", "blackboard_write", "browser_action",
    "browser_evaluate", "browser_navigate", "browser_screenshot", "browser_snapshot",
    "browser_tabs", "browser_text", "claude_headless", "compute_convert",
    "compute_hash", "compute_math", "compute_matrix", "compute_prime",
    "compute_search", "compute_sort", "compute_stats", "create_event",
    "create_job", "create_proposal", "deep_research", "env_manage", "file_edit",
    "file_read", "file_write", "find_leads", "flush_memory_before_compaction",
    "generate_proposal", "get_cost_summary", "get_events", "get_reflections",
    "github_create_issue", "github_repo_info", "git_operations", "glob_files",
    "grep_search", "install_package", "kalshi_markets", "kalshi_portfolio",
    "kalshi_trade", "kill_job", "list_jobs", "manage_reactions", "money_engine",
    "notion_create_page", "notion_query", "notion_search", "notion_update_page",
    "perplexity_research", "plan_my_day", "polymarket_monitor", "polymarket_portfolio",
    "polymarket_prices", "polymarket_trade", "prediction_market", "prediction_tracker",
    "process_manage", "read_ai_news", "read_tweets", "rebuild_semantic_index",
    "recall_memory", "research_task", "sales_call", "save_memory", "search_memory",
    "security_scan", "send_slack_message", "send_sms", "shell_execute",
    "sms_history", "sports_betting", "sportsbook_arb", "sportsbook_odds",
    "sports_predict", "tmux_agents", "trading_safety", "trading_strategies",
    "vercel_deploy", "web_fetch", "web_scrape", "web_search"
]

tools_in_profiles = set()
for profile in AGENT_TOOL_PROFILES.values():
    tools_in_profiles.update(profile)

unrestricted_tools = [t for t in all_tools if t not in tools_in_profiles]
print(f"Total tools: {len(all_tools)}")
print(f"Tools in profiles: {len(tools_in_profiles)}")
print(f"Unrestricted tools ({len(unrestricted_tools)}):")
for t in unrestricted_tools:
    print(f"  - {t}")
