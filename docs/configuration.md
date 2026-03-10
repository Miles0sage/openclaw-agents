# Configuration

OpenClaw agents and tools are configured through several key files.

---

## CLAUDE.md — Agent Souls

The **CLAUDE.md** file defines all agent personalities, routing rules, and behavioral constraints.

**Location**: `./CLAUDE.md`

**Format**: Markdown with structured sections for each agent:

```markdown
### AgentName (Role)

**Model**: Model name | **Cost**: Price per 1M tokens | **Signature**: Signature text

**Personality**: One-paragraph voice/style description

**What I do**: Bullet list of responsibilities
**What I refuse**: Bullet list of constraints
**Productive flaw**: Key weakness or bias

**Tools**: List of tools the agent can access

ALWAYS/NEVER rules specific to this agent
```

**Key sections**:

- **Universal Rules**: Constraints that apply to ALL agents
- **Agent Souls**: Individual agent profiles (13 total)
- **Routing Rules**: Task type → Agent mapping
- **Three-Tier Uncertainty Routing**: How to handle timeless facts, slow-changing facts, volatile data
- **Failure Recovery Protocol**: Retry rules

**To modify agents**:

1. Edit the soul section for that agent
2. Update routing rules if responsibilities change
3. Update tool allowlists in `agent_tool_profiles.py` (see below)
4. Restart the gateway: `systemctl restart openclaw-gateway`

---

## agent_tool_profiles.py — Tool Allowlists

Defines which agents can access which tools.

**Location**: `./agent_tool_profiles.py`

**Structure**:

```python
AGENT_TOOL_PROFILES: dict[str, set[str]] = {
    "overseer": {
        # Overseer gets all tools
        "file_read", "file_write", "file_edit", "glob_files", "grep_search",
        "shell_execute", "git_operations", "process_manage", "env_manage",
        # ... 75+ tools ...
    },
    "codegen_pro": {
        # CodeGen Pro gets subset of tools
        "file_read", "file_write", "file_edit", "glob_files", "grep_search",
        "shell_execute", "git_operations", "install_package", "process_manage",
        "auto_test",
    },
    # ... 13 agents total ...
}
```

**Security model**: The gateway checks this allowlist BEFORE executing any tool. Unauthorized tools are rejected with a 403 error.

**To add a new tool to an agent**:

1. Run `python -c "from agent_tool_profiles import get_tools_for_agent; print(get_tools_for_agent('agent_name'))"`
2. Edit `AGENT_TOOL_PROFILES['agent_name'].add('new_tool')`
3. Test: `python -c "from agent_tool_profiles import is_tool_allowed; print(is_tool_allowed('agent_name', 'new_tool'))"`

---

## Environment Variables (.env)

**Location**: `./.env`

**Required keys**:

```bash
# Claude API
ANTHROPIC_API_KEY=sk-ant-...

# Supabase
SUPABASE_URL=https://djdilkhedpnlercxggby.supabase.co
SUPABASE_KEY=eyJ...

# Optional: Deployment
VERCEL_TOKEN=...
GITHUB_TOKEN=...
SLACK_WEBHOOK=...
```

**Loading**: The gateway loads .env via `EnvironmentFile=./.env` in systemd service

**To update env vars**:

```bash
# Edit the file
nano ./.env

# Restart the gateway
systemctl restart openclaw-gateway

# Verify
grep MY_VAR ./.env
```

---

## Gateway Configuration (config.json)

The gateway loads configuration from environment and command-line flags.

**Key settings**:

```python
# In gateway.py
CONFIG = {
    "port": int(os.getenv("GATEWAY_PORT", 18789)),
    "agents_enabled": [
        "overseer",
        "codegen_pro",
        "codegen_elite",
        # ... up to 13 agents ...
    ],
    "fallback_model": "gpt-3.5-turbo",  # If agent model fails
    "max_retries": 3,
    "timeout_seconds": 300,
}
```

**To modify**: Edit gateway.py, then restart:

```bash
systemctl restart openclaw-gateway
```

---

## Cost Tiers

Agent costs (input/output) per 1M tokens:

| Agent | Model | Cost |
|-------|-------|------|
| Researcher | Kimi 2.5 | $0.14/$0.28 |
| Content Creator | Kimi 2.5 | $0.14/$0.28 |
| Financial Analyst | Kimi 2.5 | $0.14/$0.28 |
| CodeGen Pro | Kimi 2.5 | $0.14/$0.28 |
| BettingBot | Kimi 2.5 | $0.14/$0.28 |
| Code Reviewer | Kimi 2.5 | $0.14/$0.28 |
| Test Generator | Kimi 2.5 | $0.14/$0.28 |
| Pentest AI | Kimi Reasoner | $0.27/$0.68 |
| CodeGen Elite | MiniMax M2.5 | $0.30/$1.20 |
| Architecture Designer | MiniMax M2.5 | $0.30/$1.20 |
| Overseer | Claude Opus 4.6 | $15/$75 |
| SupabaseConnector | Claude Opus 4.6 | $15/$75 |
| Debugger | Claude Opus 4.6 | $15/$75 |

**Routing principle**: Always use the cheapest agent that maintains quality.

---

## Adding a New Agent

### Step 1: Define the soul in CLAUDE.md

```markdown
### NewAgent (Role)

**Model**: Model name | **Cost**: $X/$Y | **Signature**: -- NewAgent

**Personality**: Your description here

**What I do**: List of responsibilities
**What I refuse**: List of constraints
**Productive flaw**: Known weakness

**Tools**: Tool list
```

### Step 2: Create tool profile in agent_tool_profiles.py

```python
AGENT_TOOL_PROFILES["new_agent"] = {
    "file_read",
    "file_write",
    "glob_files",
    # Add tools appropriate for this agent
}
```

### Step 3: Add routing rule in CLAUDE.md

```markdown
| Task type | new_agent | Why it's the right choice |
```

### Step 4: Update gateway.py if needed

Add agent to `agents_enabled` list.

### Step 5: Test the agent

```bash
python -c "from agent_tool_profiles import get_tools_for_agent; print(get_tools_for_agent('new_agent'))"
```

### Step 6: Restart the gateway

```bash
systemctl restart openclaw-gateway
```

---

## See Also

- [Agents](agents.md) — Agent profiles and routing rules
- [Tools](tools.md) — Tool documentation and adding new tools
- [Contributing](contributing.md) — Development guidelines
