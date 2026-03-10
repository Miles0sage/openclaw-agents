# Tool System

OpenClaw uses 75+ tools through the **Model Context Protocol (MCP)** to interact with external systems. This page explains the tool system and how to add new tools.

---

## What is a Tool?

A tool is a structured interface to an external system (API, database, shell, file system, etc.). Each tool has:

- **Name**: Unique identifier (e.g., `web_search`, `file_read`, `github_create_issue`)
- **Description**: What it does
- **Input schema**: Parameters it accepts (JSON Schema)
- **Output schema**: What it returns
- **Allowlist control**: Which agents can use it

Example: `web_search` tool

```
Name: web_search
Description: Search the web for information using Google
Inputs:
  - query (string, required): Search query
  - limit (int, optional): Max results (default: 8)
Outputs:
  - results (array of {title, url, snippet})
Allowed agents: researcher, content_creator, architecture_designer
```

---

## Tool Categories

### 1. File Operations

Core tools for reading/writing files and searching code.

| Tool | Purpose | Used By |
|------|---------|---------|
| `file_read` | Read file contents | All agents (read-only) |
| `file_write` | Create/overwrite files | CodeGen Pro, CodeGen Elite, Test Generator |
| `file_edit` | Find-replace in files | CodeGen Pro, CodeGen Elite, Test Generator |
| `glob_files` | Find files matching pattern | Most agents |
| `grep_search` | Search file contents by regex | Most agents |

### 2. Shell & Git

Execute commands and manage version control.

| Tool | Purpose | Used By |
|------|---------|---------|
| `shell_execute` | Run shell commands | CodeGen Pro, CodeGen Elite, Debugger, Pentest AI |
| `git_operations` | Git commands (add, commit, push, etc.) | CodeGen Pro, CodeGen Elite, Code Reviewer, Test Generator |
| `process_manage` | List/kill processes, check ports | CodeGen Pro, CodeGen Elite, Debugger |
| `env_manage` | Read/write environment variables | CodeGen Pro, CodeGen Elite, Debugger |
| `install_package` | Install Python/npm/apt packages | CodeGen Pro, CodeGen Elite, Test Generator |

### 3. Web & Research

Search the web and gather information.

| Tool | Purpose | Used By |
|------|---------|---------|
| `web_search` | Google/Exa web search | Researcher, Content Creator, Architecture Designer |
| `web_fetch` | Fetch and parse URL content | Researcher, Content Creator, Architecture Designer |
| `web_scrape` | Extract structured data from pages | Researcher |
| `research_task` | Deep research with sub-questions | Researcher |
| `deep_research` | Multi-step autonomous research | Researcher |
| `perplexity_research` | Perplexity Sonar research API | Researcher |

### 4. GitHub

Interact with GitHub repositories and PRs.

| Tool | Purpose | Used By |
|------|---------|---------|
| `github_repo_info` | Get repo status, issues, PRs | Researcher, Code Reviewer, Architecture Designer |
| `github_create_issue` | Create GitHub issues | Project Manager, Researcher |

### 5. Cloud & Deployment

Deploy to Vercel and use cloud coding tools.

| Tool | Purpose | Used By |
|------|---------|---------|
| `vercel_deploy` | Deploy to Vercel | CodeGen Elite, Overseer |
| `claude_code_build` | Claude Code headless | Overseer, CodeGen Elite |
| `codex_build` | GPT-5 coding (via CLI Proxy) | Overseer, CodeGen Elite |
| `codex_query` | Query GPT-5 for analysis | Code Reviewer, Overseer |
| `aider_build` | Aider AI pair programmer | CodeGen Pro, CodeGen Elite |
| `gemini_cli_build` | Gemini CLI free tier | CodeGen Pro, CodeGen Elite |
| `goose_build` | Goose MCP-native agent | CodeGen Pro, CodeGen Elite |
| `opencode_build` | OpenCode HTTP server | CodeGen Pro, CodeGen Elite |

### 6. Memory & Context

Store and retrieve persistent memories.

| Tool | Purpose | Used By |
|------|---------|---------|
| `save_memory` | Save important fact to long-term memory | Researcher, Content Creator, Financial Analyst, Overseer |
| `search_memory` | Search saved memories | Researcher, Content Creator, Financial Analyst |
| `recall_memory` | Unified memory recall (semantic + reflexion + topics + Supabase) | Researcher, Overseer |

### 7. Notion Integration

Interact with Notion databases and pages.

| Tool | Purpose | Used By |
|------|---------|---------|
| `notion_search` | Search Notion workspace | Researcher, Content Creator, Financial Analyst |
| `notion_query` | Query Notion database | Researcher, Content Creator, Financial Analyst |
| `notion_create_page` | Create Notion pages | Content Creator, Financial Analyst |
| `notion_update_page` | Update page properties/content | Content Creator, Financial Analyst |

### 8. Finance & Tracking

Track expenses, invoices, and financial metrics.

| Tool | Purpose | Used By |
|------|---------|---------|
| `track_expense` | Log expense/income | Financial Analyst, Project Manager |
| `financial_summary` | Get spending summary by period | Financial Analyst, Project Manager |
| `invoice_tracker` | Manage invoices (create, update, list) | Financial Analyst |
| `process_document` | OCR receipts/invoices | Financial Analyst |

### 9. Testing & QA

Run and analyze tests.

| Tool | Purpose | Used By |
|------|---------|---------|
| `auto_test` | Run tests, analyze failures, suggest fixes | CodeGen Pro, CodeGen Elite, Test Generator, Code Reviewer |

### 10. Trading & Prediction Markets

Odds, arbitrage, Kelly sizing, +EV hunting.

| Tool | Purpose | Used By |
|------|---------|---------|
| `sportsbook_odds` | Get live odds from 200+ bookmakers | BettingBot |
| `sportsbook_arb` | Scan for arbitrage opportunities | BettingBot |
| `sports_predict` | XGBoost NBA predictions | BettingBot |
| `sports_betting` | Place bets with Kelly sizing | BettingBot |
| `polymarket_prices` | Polymarket real-time prices | BettingBot |
| `polymarket_trade` | Place Polymarket trades | BettingBot |
| `polymarket_monitor` | Monitor markets for mispricing | BettingBot |
| `kalshi_markets` | Kalshi market data | BettingBot |
| `kalshi_trade` | Place Kalshi trades | BettingBot |
| `betting_brain` | Research + line analysis | BettingBot |
| `money_engine` | Unified scanning for +EV | BettingBot |
| `arb_scanner` | Cross-platform arbitrage | BettingBot |
| `prediction_market` | General prediction market queries | BettingBot |
| `prediction_tracker` | Track prediction accuracy | BettingBot |
| `bet_tracker` | Bet ledger + P&L system | BettingBot |

### 11. Compute Utilities

Math, statistics, conversions (precise, no LLM guessing).

| Tool | Purpose | Used By |
|------|---------|---------|
| `compute_math` | Evaluate mathematical expressions | All agents |
| `compute_stats` | Statistics (mean, median, percentiles) | All agents |
| `compute_sort` | Sort numbers/strings (O(n log n)) | All agents |
| `compute_search` | Binary search, linear scan, filter, regex | All agents |
| `compute_hash` | Cryptographic hashes (SHA-256, BLAKE2) | All agents |
| `compute_convert` | Unit/base conversions | All agents |
| `compute_matrix` | Matrix operations | All agents |
| `compute_prime` | Prime operations (factorize, generate) | All agents |

### 12. Admin & System

System-level tools for Overseer only.

| Tool | Purpose | Used By |
|------|---------|---------|
| `tmux_agents` | Spawn/monitor Claude Code agents | Overseer |
| `manage_reactions` | Auto-reaction rules | Overseer |
| `process_manage` | List/kill processes | Overseer, CodeGen Elite, Debugger |
| `env_manage` | Manage environment variables | Overseer, CodeGen Elite |
| `create_job` | Create new job | Project Manager, Overseer |
| `list_jobs` | List jobs by status | Project Manager, Overseer |
| `approve_job` | Approve pending jobs | Project Manager, Overseer |
| `create_proposal` | Create proposal with auto-approval | Project Manager |
| `get_cost_summary` | Cost/budget overview | Project Manager, Overseer |
| `get_events` | System events log | Project Manager, Overseer |
| `send_slack_message` | Send Slack notifications | Project Manager, Overseer |
| `send_sms` | Send SMS via Twilio | Overseer |
| `email_triage` | AI-triage unread emails | Project Manager |
| `plan_my_day` | Create daily plan from calendar + tasks | Project Manager, Overseer |
| `morning_briefing` | Daily briefing with news + email summary | Project Manager, Financial Analyst |
| `agency_status` | Full agency overview | Overseer |
| `kill_job` | Cancel running job | Overseer |
| `blackboard_read` | Read shared state entry | Overseer |
| `blackboard_write` | Write shared state entry | Overseer |
| `flush_memory_before_compaction` | Save memories before context compaction | Overseer |
| `rebuild_semantic_index` | Rebuild memory search index | Overseer |
| `get_reflections` | Get past job learnings | Overseer |
| `security_scan` | OXO security scan | Overseer, Pentest AI |
| `read_ai_news` | AI industry news from RSS | Overseer |
| `read_tweets` | Recent tweets from AI accounts | Overseer |

---

## Adding a New Tool

### Step 1: Implement the Tool

Create a function in `agent_tools.py`:

```python
def my_new_tool(param1: str, param2: int) -> dict:
    """
    Brief description of what the tool does.

    Args:
        param1: Description of param1
        param2: Description of param2

    Returns:
        A dictionary with the result
    """
    # Implementation
    result = {"status": "success", "data": "..."}
    return result
```

**Requirements**:
- Type hints on all parameters and return value
- Google-style docstring
- Return JSON-serializable dict or string
- Handle errors gracefully (return error dict, don't raise)

### Step 2: Add to Tool Profiles

Update `agent_tool_profiles.py` to add your tool to agent allowlists:

```python
AGENT_TOOL_PROFILES: dict[str, set[str]] = {
    "codegen_pro": {
        # ... existing tools ...
        "my_new_tool",  # Add here
    },
    "researcher": {
        # ... existing tools ...
        "my_new_tool",  # Add if researcher should use it
    },
}
```

**Principle**: Each agent gets a filtered set of tools. Only add tools to agents that should use them.

### Step 3: Write Tests

Create a test in `tests/test_tools.py`:

```python
def test_my_new_tool():
    result = my_new_tool("test_input", 42)
    assert result["status"] == "success"
    assert "data" in result
```

### Step 4: Update Gateway (if external-facing)

If users should call this tool via the Gateway HTTP API, add it to the MCP server:

1. Register in `gateway/mcp_tools.py`
2. Test via `curl http://localhost:8789/tools/my_new_tool`

### Step 5: Document It

Add to this page:

```markdown
| my_new_tool | Brief description | CodeGen Pro, Researcher |
```

---

## Tool Design Principles

### 1. Be Precise
Tools should return exact data, not approximations. If you need SQL results, query the database. Never guess.

### 2. Handle Errors Gracefully
Return `{"status": "error", "message": "..."}` instead of raising exceptions. Agents need to see errors and decide what to do.

### 3. Limit Output
Web scraping tools should extract specific data, not return entire HTML. Queries should have WHERE clauses, not unbounded result sets.

### 4. Respect Security Models
Never bypass authentication. Respect RLS policies. Don't hardcode secrets in tools.

### 5. Track Costs
If a tool calls an external API with a cost, log it:

```python
# At end of tool
cost_cents = token_count * price_per_token / 10000
log_event("tool_call", {"tool": "my_new_tool", "cost_cents": cost_cents})
```

---

## Tool Integration Flow

When an agent calls a tool:

```
Agent (e.g., CodeGen Pro)
    ↓
Calls: file_edit(path="/root/project/main.py", old_string="...", new_string="...")
    ↓
Gateway validates: Is "file_edit" in CodeGen Pro's allowlist? YES
    ↓
Execute tool with parameters
    ↓
Tool returns: {"status": "success", "lines_changed": 5}
    ↓
Agent receives result and decides next step
    ↓
Log to event engine: {agent: "codegen_pro", tool: "file_edit", cost_cents: 0}
```

**Security checkpoint**: The Gateway checks the allowlist BEFORE executing the tool. Unauthorized tools are rejected.

---

## Common Tool Patterns

### Pattern 1: Read-Only Tools
File reading, web searching, database queries (SELECT only).

**Never require confirmation**, safe for all agents.

```python
def file_read(path: str) -> dict:
    """Read file contents (read-only, always safe)."""
    try:
        with open(path, 'r') as f:
            content = f.read()
        return {"status": "success", "content": content}
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

### Pattern 2: Mutating Tools with Confirmation
File writes, database updates, deployments.

**Require explicit confirmation in agent request**.

```python
def file_write(path: str, content: str, overwrite: bool = False) -> dict:
    """Write file (requires overwrite=True for existing files)."""
    if os.path.exists(path) and not overwrite:
        return {"status": "error", "message": "File exists. Set overwrite=True to confirm."}

    try:
        with open(path, 'w') as f:
            f.write(content)
        return {"status": "success", "path": path}
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

### Pattern 3: Tools with Limits
Queries with WHERE clauses, searches with result limits.

```python
def web_search(query: str, limit: int = 8) -> dict:
    """Search the web. Limit results to prevent huge returns."""
    if limit > 50:
        return {"status": "error", "message": "limit must be <= 50"}

    results = search(query, limit)
    return {"status": "success", "results": results}
```

---

## Tool Debugging

### Check if Tool is Installed

```bash
# List all tools available to an agent
python -c "from agent_tool_profiles import get_tools_for_agent; print(get_tools_for_agent('codegen_pro'))"
```

### Test Tool Directly

```bash
# In Python REPL
from agent_tools import file_read
result = file_read("/root/project/README.md")
print(result)
```

### Check Allowlist

```python
from agent_tool_profiles import is_tool_allowed
is_allowed = is_tool_allowed("researcher", "vercel_deploy")
print(is_allowed)  # False (researcher can't deploy)
```

---

## See Also

- [Agents](agents.md) — Which agent uses which tools
- [Configuration](configuration.md) — Tool allowlist configuration
- [Contributing](contributing.md) — How to contribute new tools
