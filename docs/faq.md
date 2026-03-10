# Frequently Asked Questions

---

## Agents

### How many agents does OpenClaw have?

OpenClaw has **13 specialized agents** (souls), each optimized for a specific type of work:

- **Cheap tier ($0.14-0.28/1M tokens)**: Researcher, Content Creator, Financial Analyst, CodeGen Pro, BettingBot, Code Reviewer, Test Generator
- **Mid tier ($0.27-1.20/1M tokens)**: Pentest AI, CodeGen Elite, Architecture Designer
- **Premium tier ($15-75/1M tokens)**: Overseer, SupabaseConnector, Debugger

### How do I know which agent to use for my task?

Use the **routing rules table** in [Agents](agents.md):

- **Research** (market, technical, academic, news) → Researcher
- **Content** (blog, social, proposal, docs) → Content Creator
- **Finance** (revenue, costs, pricing, invoicing) → Financial Analyst
- **Simple code** (fix, add, build, CSS) → CodeGen Pro
- **Complex code** (refactor, architecture, multi-file) → CodeGen Elite
- **Security** (audit, vulnerability, pentest, RLS) → Pentest AI
- **Data queries** (fetch, schema, migration) → SupabaseConnector
- **System design** (architecture, scalability, API) → Architecture Designer
- **Testing** (tests, coverage, edge cases) → Test Generator
- **Deep bugs** (race condition, memory leak, heisenbug) → Debugger
- **Ambiguous tasks** (planning, decomposition) → Overseer

### Can I add my own agent?

Yes! See [Contributing](contributing.md) for step-by-step instructions on adding a new agent.

### What's the difference between CodeGen Pro and CodeGen Elite?

- **CodeGen Pro**: Fast, cheap ($0.14/1M tokens), handles simple tasks (button fixes, API endpoints, CSS, tests)
- **CodeGen Elite**: Expensive ($0.30/1M tokens), handles complex multi-file refactors, architectural changes, algorithms. 80.2% SWE-Bench accuracy.

**Rule**: Use Pro for bounded tasks. Escalate to Elite when a task touches 3+ files with shared state.

### Why does an agent refuse certain tasks?

Each agent has explicit boundaries in their soul definition. For example:

- CodeGen Pro refuses: architectural decisions, shipping without testing
- Content Creator refuses: writing without knowing the audience
- Debugger refuses: guessing at fixes without understanding root cause

These boundaries prevent agents from doing work they're not specialized for.

---

## Tools

### How many tools does OpenClaw have?

OpenClaw provides **75+ tools** organized into 12 categories:

1. File Operations (file_read, file_write, file_edit, glob_files, grep_search)
2. Shell & Git (shell_execute, git_operations, process_manage, env_manage, install_package)
3. Web & Research (web_search, web_fetch, web_scrape, research_task, deep_research)
4. GitHub (github_repo_info, github_create_issue)
5. Cloud & Deployment (vercel_deploy, claude_code_build, codex_build, aider_build)
6. Memory & Context (save_memory, search_memory, recall_memory)
7. Notion Integration (notion_search, notion_query, notion_create_page, notion_update_page)
8. Finance & Tracking (track_expense, financial_summary, invoice_tracker, process_document)
9. Testing & QA (auto_test)
10. Trading & Prediction Markets (sportsbook_odds, polymarket_trade, kalshi_markets, etc.)
11. Compute Utilities (compute_math, compute_stats, compute_sort, compute_hash, compute_matrix)
12. Admin & System (tmux_agents, manage_reactions, send_slack_message, security_scan, etc.)

### Can an agent use any tool?

No. Each agent has an **allowlist** of tools it can access. This is a security model — it prevents agents from doing work outside their specialty.

For example:
- CodeGen Pro can use `file_edit`, `shell_execute`, but NOT `vercel_deploy` (that's for CodeGen Elite)
- Researcher can use `web_search`, `web_fetch`, but NOT `file_write`
- Overseer can use all tools (it's the coordinator)

### How do I add a new tool?

See [Contributing](contributing.md) for step-by-step instructions. TL;DR:

1. Implement the tool function in `agent_tools.py`
2. Add it to agent allowlists in `agent_tool_profiles.py`
3. Write tests in `tests/test_tools.py`
4. Document it in `docs/tools.md`
5. Submit a PR

### Can I write my own tools?

Yes. Tools are Python functions that return JSON-serializable dicts. See [Tools](tools.md) for the design principles and patterns.

---

## Routing & Execution

### How does the Overseer route tasks?

The Overseer receives all inbound jobs and makes routing decisions based on:

1. **Task type** (e.g., "fix a bug" → CodeGen Pro)
2. **Complexity** (e.g., multi-file refactor → CodeGen Elite instead of Pro)
3. **Cost** (e.g., prefer cheaper agents if quality is equal)
4. **Specialist availability** (e.g., security task → Pentest AI)

If unsure, Overseer escalates up the cost hierarchy rather than down.

### What happens if a task fails?

The agent:

1. Diagnoses the error
2. Modifies the approach
3. Retries (max 3 times per failing prompt)

If all 3 attempts fail, the job is marked as permanent failure with full diagnostic context. The Overseer decides whether to escalate, try a different agent, or report back to the user.

### Can tasks run in parallel?

Yes! The Overseer can spawn multiple agents simultaneously for independent subtasks. This is faster and cheaper than serial execution.

---

## Configuration

### Where is the configuration file?

Configuration lives in three places:

1. **Agent souls**: `./CLAUDE.md` (personality, routing rules)
2. **Tool allowlists**: `./agent_tool_profiles.py` (which agents can use which tools)
3. **Environment**: `./.env` (API keys, secrets)

### How do I change an agent's tools?

Edit `agent_tool_profiles.py`:

```python
AGENT_TOOL_PROFILES["codegen_pro"].add("new_tool")
```

Then restart the gateway:

```bash
systemctl restart openclaw-gateway
```

### How do I update environment variables?

Edit `.env`:

```bash
nano ./.env
```

Then restart:

```bash
systemctl restart openclaw-gateway
```

### Where are API keys stored?

In `./.env` (not committed to git). Never hardcode secrets in source files.

---

## Cost & Budget

### How much does OpenClaw cost?

Costs depend on which agents you use:

- **Cheap agents** ($0.14-0.28 per 1M tokens): Researcher, Content Creator, CodeGen Pro, etc.
- **Mid agents** ($0.27-1.20 per 1M tokens): Pentest AI, CodeGen Elite
- **Premium agents** ($15-75 per 1M tokens): Overseer, Debugger, SupabaseConnector

A typical job costs $0.01-0.50 depending on complexity.

### How do I minimize costs?

1. **Route to the cheapest agent that works**: CodeGen Pro before CodeGen Elite
2. **Prefer specific tools**: use `file_edit` instead of `shell_execute` when possible
3. **Set clear requirements**: ambiguous tasks cause retries
4. **Monitor spending**: Overseer logs cost with every job result

### Can I set a budget limit?

Not yet. Cost tracking is enabled, and alerts are logged when spending exceeds thresholds. Future versions will support hard budget caps.

---

## Troubleshooting

### A task failed. What should I do?

1. Check the error message and logs
2. Verify the task description is clear and complete
3. Check that the agent has access to required tools
4. Try again with more specific requirements
5. If it fails a second time, escalate to Overseer or try a different agent

### An agent refuses my task.

This is intentional — agents have explicit boundaries. For example:

- CodeGen Pro refuses: "Ship untested code" or "Make architectural decisions"
- Content Creator refuses: "Write without knowing the audience"
- Debugger refuses: "Guess at fixes without diagnosing root cause"

**Solution**: Provide more context or context or use a different agent that specializes in that task type.

### The gateway won't start.

```bash
# Check logs
journalctl -u openclaw-gateway -f

# Verify config
cat ./.env

# Check for port conflicts
lsof -i :18789
```

### An agent is too slow / too expensive.

Check the routing:

```bash
python -c "from CLAUDE import ROUTING_RULES; print(ROUTING_RULES)"
```

You might be routing to an expensive agent when a cheaper one would work. See the routing table in [Agents](agents.md).

---

## Development

### How do I run tests?

```bash
pytest tests/ -v
pytest tests/test_agents.py::test_specific_test -v
pytest tests/ --cov=openclaw --cov-report=html
```

### How do I debug an agent?

```bash
# Run agent directly
python -c "from openclaw import Overseer; job = {'task': '...'}; result = Overseer.execute(job)"

# Check logs
journalctl -u openclaw-gateway -f | grep agent_name

# Check tool access
python -c "from agent_tool_profiles import get_tools_for_agent; print(get_tools_for_agent('agent_name'))"
```

### Can I modify an agent's behavior?

Yes, by editing their soul in `CLAUDE.md`. Changes to personality, routing rules, or ALWAYS/NEVER constraints take effect on restart:

```bash
systemctl restart openclaw-gateway
```

---

## Getting Help

- **Agent routing questions**: See [Agents](agents.md)
- **Tool documentation**: See [Tools](tools.md)
- **Configuration help**: See [Configuration](configuration.md)
- **Contributing**: See [Contributing](contributing.md)
- **Report a bug**: Open an Issue on GitHub

---

## See Also

- [Agents](agents.md) — Complete agent profiles
- [Tools](tools.md) — Complete tool reference
- [Configuration](configuration.md) — Config file guide
- [Contributing](contributing.md) — Development guide
