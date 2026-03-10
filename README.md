# OpenClaw

[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge)](LICENSE)

**Autonomous multi-agent system that takes tasks (GitHub issues, feature requests, bug reports), decomposes them into subtasks, routes to specialized AI agents, and delivers working code.**

OpenClaw is a production-grade agent framework that routes tasks intelligently across 12 specialized agents (CodeGen, Security, Testing, Research, etc.), executes with 75+ integrated tools, and verifies results before reporting costs and duration.

---

## Quick Start

**Requirements:**
- Python 3.11+
- Supabase account ([free tier](https://supabase.com))
- At least one LLM API key (Claude, Gemini, DeepSeek, or Bailian)

**Installation:**

```bash
git clone https://github.com/Miles0sage/openclaw-agents.git
cd openclaw-agents
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your API keys

# Start the gateway
python gateway.py

# In another terminal, verify it's running
curl http://localhost:18789/health
```

**Send a task (Python):**

```python
import httpx

response = httpx.post(
    "http://localhost:18789/api/job/create",
    json={
        "project": "my-project",
        "task": "Add dark mode toggle to login button",
        "priority": "P1"
    },
    headers={"X-Auth-Token": "YOUR_GATEWAY_TOKEN"}
)

print(response.json())
# {"job_id": "job-20260310-...", "status": "pending"}
```

**Send a task (curl):**

```bash
curl -X POST http://localhost:18789/api/job/create \
  -H "X-Auth-Token: YOUR_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project": "my-project", "task": "Add dark mode toggle", "priority": "P1"}'
```

---

## Docker (Optional)

```bash
docker compose up
```

---

## Architecture

OpenClaw decomposes tasks through a coordinated multi-agent pipeline:

```
Task Input → Gateway → Overseer (routing) → Specialist Agent → MCP Tools → Verification → Output
```

**12 Agent Souls** (each with specialized model and cost tier):

| Agent | Model | Cost | Specialty |
|-------|-------|------|-----------|
| Overseer | Claude Opus 4.6 | $15/1M | Task decomposition, routing, verification |
| CodeGen Pro | Kimi 2.5 | $0.14/1M | Frontend, backend, API, quick fixes |
| CodeGen Elite | MiniMax M2.5 | $0.30/1M | Complex refactors, algorithms, architecture |
| Pentest AI | Kimi Reasoner | $0.27/1M | Security audits, vulnerability assessment |
| SupabaseConnector | Claude Opus 4.6 | $15/1M | Database queries, schema, migrations |
| Code Reviewer | Kimi 2.5 | $0.14/1M | PR reviews, code audits, tech debt |
| Test Generator | Kimi 2.5 | $0.14/1M | Unit/integration/E2E tests, coverage |
| Debugger | Claude Opus 4.6 | $15/1M | Race conditions, memory leaks, root cause |
| Researcher | Kimi 2.5 | $0.14/1M | Market research, tech deep dives |
| Content Creator | Kimi 2.5 | $0.14/1M | Blog posts, documentation, proposals |
| Architecture Designer | MiniMax M2.5 | $0.30/1M | System design, API contracts, scalability |
| Financial Analyst | Kimi 2.5 | $0.14/1M | Revenue tracking, cost analysis, pricing |

**75+ Integrated Tools:**
- Code: file operations, shell execution, git
- Database: Supabase queries, migrations, RLS audits
- Browser: navigation, screenshots, JavaScript execution
- Security: vulnerability scanning, penetration testing
- Research: web search, deep research, synthesis
- Sports: live odds, arbitrage, XGBoost predictions
- Trading: prediction markets, Kelly sizing
- Monitoring: cost tracking, job viewer, analytics

---

## Testing

```bash
# Run all tests
pytest

# Run specific test suite
pytest tests/ -k "agent_routing"

# With coverage report
pytest --cov=openclaw tests/

# 592 tests covering agent routing, error recovery, cost gating, LLM fallback, tool execution, and reflexion
```

---

## Configuration

Edit `.env` after running `cp .env.example .env`:

**Required:**
- `ANTHROPIC_API_KEY` — Claude API key
- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_KEY` — Supabase service role key

**Recommended:**
- `DEEPSEEK_API_KEY` — For cheaper agents (Kimi 2.5)
- `MINIMAX_API_KEY` — For complex reasoning tasks
- `BAILIAN_API_KEY` — Fallback coding model

**Optional:**
- `TELEGRAM_BOT_TOKEN` — For Telegram integration
- `SLACK_BOT_TOKEN` — For Slack integration
- `GEMINI_API_KEY` — For research and fallback

See `.env.example` for full documentation on each variable.

---

## Typical Costs

- Simple code fix → $0.02
- Feature implementation → $0.08
- Complex refactor → $0.15
- Security audit → $0.10
- Database query → $0.30
- Full system redesign → $0.50

Costs vary by task complexity and agent selection. All costs include 4-tier LLM fallback (no retries charged separately).

---

## Performance

**v4.2 Results:**
- 90%+ success rate across all job types
- 12 seconds for simple tasks, 3 min for complex refactors
- Full test suite: 592 tests in 0.72 seconds
- ~$40/month for typical usage (including fallback chain)

---

## Development

**Add a new tool:**
1. Implement in `tools/` folder
2. Register in `allowed_tools` (see `CLAUDE.md`)
3. Write tests in `tests/test_tools/`
4. Restart gateway: `python gateway.py`

**Add a new agent:**
1. Define in `CLAUDE.md`
2. Register routing rules in `agent_router.py`
3. Test with `pytest tests/test_agent_routing.py`

See `CLAUDE.md` for agent personas and routing rules. See `ARCHITECTURE.md` for deep technical details.

---

## Project Status

| Component | Status |
|-----------|--------|
| Core Pipeline | ✅ Production |
| 12 Agents | ✅ Deployed |
| 75+ Tools | ✅ Integrated |
| Error Recovery | ✅ 3-tier fallback + reflexion |
| Testing | ✅ 592 tests |
| Stripe Integration | ⏳ In progress |

---

## License

[MIT](LICENSE)

---

## Resources

- [CLAUDE.md](CLAUDE.md) — Agent identities, protocols, routing rules
- [ARCHITECTURE.md](ARCHITECTURE.md) — Pipeline phases, tool ecosystem, data models
- [Contributing](CONTRIBUTING.md) — Development guide
- [Issues](https://github.com/Miles0sage/openclaw-agents/issues) — Feature requests and bug reports

**OpenClaw v4.2** · Last updated 2026-03-10
