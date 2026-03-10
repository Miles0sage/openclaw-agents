"""
OpenClaw Portal Router — API endpoints for the client portal dashboard.

Provides:
- GET /api/agents/profiles — Agent souls with model, cost, specialty, tools
- GET /api/tools/catalog — Tool catalog with descriptions, agent/phase access
"""

import logging
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["portal"])
logger = logging.getLogger("portal")


# ── Agent profile data (derived from CLAUDE.md souls + agent_router.py) ──

AGENT_PROFILES = {
    "project_manager": {
        "id": "project_manager",
        "name": "Overseer",
        "role": "PM / Coordinator",
        "model": "Claude Opus 4.6",
        "cost_input": "$15.00/M tokens",
        "cost_output": "$75.00/M tokens",
        "cost_tier": "premium",
        "specialty": "Task decomposition, agent routing, execution tracking, budget management",
        "description": "Decomposes objectives, routes to the right agent, tracks execution, verifies results, manages budget.",
        "signature": "-- Overseer",
    },
    "coder_agent": {
        "id": "coder_agent",
        "name": "CodeGen Pro",
        "role": "Developer",
        "model": "Kimi 2.5 (Deepseek)",
        "cost_input": "$0.14/M tokens",
        "cost_output": "$0.28/M tokens",
        "cost_tier": "economy",
        "specialty": "Frontend, backend, API, database, testing, bug fixes, feature implementation",
        "description": "Fast and cheap — 95% cheaper than Claude for routine coding tasks. Handles button fixes, API endpoints, component builds, test writing, CSS work.",
        "signature": "-- CodeGen Pro",
    },
    "elite_coder": {
        "id": "elite_coder",
        "name": "CodeGen Elite",
        "role": "Complex Developer",
        "model": "MiniMax M2.5",
        "cost_input": "$0.30/M tokens",
        "cost_output": "$1.20/M tokens",
        "cost_tier": "standard",
        "specialty": "Complex refactors, architecture implementation, system design, algorithm work, deep debugging",
        "description": "Handles tasks that break other coding agents. Multi-file refactors, system redesigns, algorithm implementations. 80.2% SWE-Bench accuracy, 205K context window.",
        "signature": "-- CodeGen Elite",
    },
    "hacker_agent": {
        "id": "hacker_agent",
        "name": "Pentest AI",
        "role": "Security",
        "model": "Kimi Reasoner (Deepseek)",
        "cost_input": "$0.27/M tokens",
        "cost_output": "$0.68/M tokens",
        "cost_tier": "standard",
        "specialty": "OWASP analysis, vulnerability assessment, RLS audits, threat modeling, penetration testing",
        "description": "Finds vulnerabilities before attackers do. Specializes in edge cases that look correct at first glance.",
        "signature": "-- Pentest AI",
    },
    "database_agent": {
        "id": "database_agent",
        "name": "SupabaseConnector",
        "role": "Data",
        "model": "Claude Opus 4.6",
        "cost_input": "$15.00/M tokens",
        "cost_output": "$75.00/M tokens",
        "cost_tier": "premium",
        "specialty": "Supabase queries, SQL execution, schema exploration, data analysis, RLS policy verification",
        "description": "Queries databases with surgical precision. Runs on Opus because cheaper models produce subtly wrong SQL.",
        "signature": "-- SupabaseConnector",
    },
    "research_agent": {
        "id": "research_agent",
        "name": "Researcher",
        "role": "Deep Research",
        "model": "Kimi 2.5 (Deepseek)",
        "cost_input": "$0.14/M tokens",
        "cost_output": "$0.28/M tokens",
        "cost_tier": "economy",
        "specialty": "Market research, technical deep dives, competitor analysis, academic lit review, news synthesis",
        "description": "Autonomous deep research agent. Decomposes topics into sub-questions, researches in parallel, synthesizes with citations.",
        "signature": "-- Researcher",
    },
    "code_reviewer": {
        "id": "code_reviewer",
        "name": "Code Reviewer",
        "role": "PR & Code Audit",
        "model": "Kimi 2.5 (Deepseek)",
        "cost_input": "$0.14/M tokens",
        "cost_output": "$0.28/M tokens",
        "cost_tier": "economy",
        "specialty": "PR reviews, code audits, technical debt assessment, pattern matching",
        "description": "Catches logic errors, missing edge cases, and architectural violations. Suggests concrete fixes.",
        "signature": "-- Code Reviewer",
    },
    "test_generator": {
        "id": "test_generator",
        "name": "Test Generator",
        "role": "Testing & QA",
        "model": "Kimi 2.5 (Deepseek)",
        "cost_input": "$0.14/M tokens",
        "cost_output": "$0.28/M tokens",
        "cost_tier": "economy",
        "specialty": "Unit tests, integration tests, E2E tests, edge case detection, coverage gap analysis",
        "description": "Thinks about how code breaks, not how it works. 100% coverage means nothing if you're testing the wrong things.",
        "signature": "-- Test Generator",
    },
    "debugger": {
        "id": "debugger",
        "name": "Debugger",
        "role": "Deep Debugging",
        "model": "Claude Opus 4.6",
        "cost_input": "$15.00/M tokens",
        "cost_output": "$75.00/M tokens",
        "cost_tier": "premium",
        "specialty": "Race conditions, memory leaks, distributed system failures, heisenbugs, root cause analysis",
        "description": "Doesn't guess. Builds a mental model, identifies what changed, traces execution path, narrows root cause systematically.",
        "signature": "-- Debugger",
    },
    "architecture_designer": {
        "id": "architecture_designer",
        "name": "Architecture Designer",
        "role": "System Design",
        "model": "MiniMax M2.5",
        "cost_input": "$0.30/M tokens",
        "cost_output": "$1.20/M tokens",
        "cost_tier": "standard",
        "specialty": "System design, API contracts, database modeling, scalability analysis, trade-off documentation",
        "description": "Thinks in systems, not features. Maps blast radius before anyone writes code. 205K context holds entire architectures.",
        "signature": "-- Architecture Designer",
    },
    "content_creator": {
        "id": "content_creator",
        "name": "Content Creator",
        "role": "Content & Copy",
        "model": "Kimi 2.5 (Deepseek)",
        "cost_input": "$0.14/M tokens",
        "cost_output": "$0.28/M tokens",
        "cost_tier": "economy",
        "specialty": "Blog posts, social media, proposals, documentation, email campaigns, presentation content",
        "description": "Writes content that people actually read. Matches tone to audience and format to medium.",
        "signature": "-- Content Creator",
    },
    "financial_analyst": {
        "id": "financial_analyst",
        "name": "Financial Analyst",
        "role": "Finance & Revenue",
        "model": "Kimi 2.5 (Deepseek)",
        "cost_input": "$0.14/M tokens",
        "cost_output": "$0.28/M tokens",
        "cost_tier": "economy",
        "specialty": "Revenue tracking, cost analysis, pricing research, invoicing, budget reports, financial forecasting",
        "description": "Tracks money. Revenue, costs, pricing research, invoicing — presents numbers with context, not just raw data.",
        "signature": "-- Financial Analyst",
    },
    "trading_agent": {
        "id": "trading_agent",
        "name": "BettingBot",
        "role": "Sports Analyst",
        "model": "Kimi 2.5 (Deepseek)",
        "cost_input": "$0.14/M tokens",
        "cost_output": "$0.28/M tokens",
        "cost_tier": "economy",
        "specialty": "Live odds, arbitrage scanning, XGBoost predictions, Kelly criterion sizing, +EV identification",
        "description": "Thinks in probabilities, not hunches. Every bet has a mathematical edge backed by XGBoost.",
        "signature": "-- BettingBot",
    },
    "sales_agent": {
        "id": "sales_agent",
        "name": "Sales Agent",
        "role": "Lead Gen & Proposals",
        "model": "Kimi 2.5 (Deepseek)",
        "cost_input": "$0.14/M tokens",
        "cost_output": "$0.28/M tokens",
        "cost_tier": "economy",
        "specialty": "Lead generation, prospecting, proposal creation, client outreach",
        "description": "Finds leads, generates proposals, manages sales pipeline.",
        "signature": "-- Sales Agent",
    },
    "browser_agent": {
        "id": "browser_agent",
        "name": "Browser Agent",
        "role": "Web Automation",
        "model": "Kimi 2.5 (Deepseek)",
        "cost_input": "$0.14/M tokens",
        "cost_output": "$0.28/M tokens",
        "cost_tier": "economy",
        "specialty": "Web interaction, browser automation, scraping, screenshot capture",
        "description": "Automates web interactions via headless browser. Navigates, screenshots, evaluates JS, extracts text.",
        "signature": "-- Browser Agent",
    },
    "overseer": {
        "id": "overseer",
        "name": "Overseer (Admin)",
        "role": "Full System Control",
        "model": "Claude Opus 4.6",
        "cost_input": "$15.00/M tokens",
        "cost_output": "$75.00/M tokens",
        "cost_tier": "premium",
        "specialty": "Full system administration, tmux agents, cron management, deployment, security scanning",
        "description": "Admin-only agent with unrestricted access to all tools. Handles system-level operations.",
        "signature": "-- Overseer Admin",
    },
}


@router.get("/agents/profiles")
async def get_agent_profiles():
    """Return all agent profiles with model, cost, specialty, and allowed tools."""
    from agent_tool_profiles import AGENT_TOOL_PROFILES

    profiles = []
    for agent_id, profile in AGENT_PROFILES.items():
        tools = sorted(AGENT_TOOL_PROFILES.get(agent_id, set()))
        profiles.append({
            **profile,
            "tools": tools,
            "tool_count": len(tools),
        })

    # Sort: premium first, then by name
    tier_order = {"premium": 0, "standard": 1, "economy": 2}
    profiles.sort(key=lambda p: (tier_order.get(p["cost_tier"], 9), p["name"]))

    return {
        "agents": profiles,
        "total_agents": len(profiles),
    }


@router.get("/tools/catalog")
async def get_tools_catalog():
    """Return full tool catalog with descriptions, agent access, and phase access."""
    from agent_tools import AGENT_TOOLS
    from agent_tool_profiles import AGENT_TOOL_PROFILES
    from tool_router import PHASE_TOOLS, TOOL_RISK_LEVELS

    # Build tool → agents mapping
    tool_agents: dict[str, list[str]] = {}
    for agent_id, tools in AGENT_TOOL_PROFILES.items():
        for tool_name in tools:
            if tool_name not in tool_agents:
                tool_agents[tool_name] = []
            tool_agents[tool_name].append(agent_id)

    # Build tool → phases mapping
    tool_phases: dict[str, list[str]] = {}
    for phase, tools in PHASE_TOOLS.items():
        for tool_name in tools:
            if tool_name not in tool_phases:
                tool_phases[tool_name] = []
            tool_phases[tool_name].append(phase)

    # Build catalog from AGENT_TOOLS definitions
    catalog = []
    for tool_def in AGENT_TOOLS:
        name = tool_def["name"]
        catalog.append({
            "name": name,
            "description": tool_def.get("description", ""),
            "risk_level": TOOL_RISK_LEVELS.get(name, "unknown"),
            "agents": sorted(tool_agents.get(name, [])),
            "agent_count": len(tool_agents.get(name, [])),
            "phases": sorted(tool_phases.get(name, [])),
            "parameters": list(tool_def.get("input_schema", {}).get("properties", {}).keys()),
        })

    # Sort by name
    catalog.sort(key=lambda t: t["name"])

    # Summary stats
    risk_counts = {}
    for tool in catalog:
        level = tool["risk_level"]
        risk_counts[level] = risk_counts.get(level, 0) + 1

    return {
        "tools": catalog,
        "total_tools": len(catalog),
        "risk_summary": risk_counts,
        "phases": list(PHASE_TOOLS.keys()),
    }
