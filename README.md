# OpenClaw Agents

**Multi-agent AI framework: 85+ tools, 11 agent souls, priority job routing, reflexion quality gates, 4-tier LLM fallback.**

Built for autonomous software engineering, deployed in production since 2025.

---

## Architecture

OpenClaw is built on **8 pillars** that work independently or together:

| Pillar | What it does | Key files |
|--------|-------------|-----------|
| **Pipeline** | Data models, error classification, guardrails | `pipeline/` |
| **Agent Routing** | Semantic dispatch + per-agent tool allowlists | `agent_router.py`, `agent_tool_profiles.py` |
| **Autonomous Executor** | 5-phase job runner (Research→Plan→Execute→Review→Deliver) | `autonomous_runner.py` |
| **Hands System** | Scheduled autonomous agents via APScheduler | `scheduled_hands.py` |
| **Reflexion Loop** | Post-job self-improvement, prompt injection | `reflexion.py` |
| **Eval Harness** | Per-phase quality scoring, regression detection | `eval_harness.py`, `phase_scoring.py` |
| **Cost Tracking** | Per-token accounting, budget gates, 15+ model pricing | `cost_tracker.py` |
| **Event Engine** | Job lifecycle events, reactions, approval gates | `event_engine.py` |

### How a job flows

```
User request
    ↓
Agent Router (semantic + keyword matching)
    ↓
Tool Profile filter (only tools this agent is allowed)
    ↓
5-Phase Pipeline:
  1. RESEARCH  — gather context, read files, search
  2. PLAN      — decompose into steps, estimate cost
  3. EXECUTE   — run tools, write code, make changes
  4. REVIEW    — code review, security scan
  5. DELIVER   — verify output, report results
    ↓
Reflexion (store what worked / what failed)
    ↓
Event Engine (emit job.completed, trigger reactions)
```

### Agent Souls

11 specialized agents, each with distinct model + cost tier:

| Agent | Model | $/1M tokens | Specialty |
|-------|-------|-------------|-----------|
| Overseer | Claude Opus | $15/$75 | PM, routing, verification |
| CodeGen Pro | Kimi 2.5 | $0.14/$0.28 | Fast bounded tasks |
| CodeGen Elite | MiniMax M2.5 | $0.30/$1.20 | Complex refactors |
| Pentest AI | Kimi Reasoner | $0.27/$0.68 | Security audits |
| Researcher | Kimi 2.5 | $0.14/$0.28 | Deep research |
| BettingBot | Kimi 2.5 | $0.14/$0.28 | Sports analytics |
| Content Creator | Kimi 2.5 | $0.14/$0.28 | Writing |
| Financial Analyst | Kimi 2.5 | $0.14/$0.28 | Cost/revenue tracking |
| Test Generator | Kimi 2.5 | $0.14/$0.28 | Edge-case testing |
| Debugger | Claude Opus | $15/$75 | Deep debugging |
| Architecture Designer | MiniMax M2.5 | $0.30/$1.20 | System design |

**Routing rule**: Always pick the cheapest agent that won't compromise quality.

---

## Quick Start

```bash
# Clone
git clone https://github.com/Miles0sage/openclaw-agents.git
cd openclaw-agents

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env — set GATEWAY_AUTH_TOKEN and at least one LLM provider key

# Setup (creates required data directories)
python setup.py

# Run gateway
python gateway.py

# Register a demo client
curl -X POST http://localhost:8000/api/admin/clients \
  -H "Content-Type: application/json" \
  -H "X-Auth-Token: YOUR_GATEWAY_AUTH_TOKEN" \
  -d '{"name": "Demo User", "email": "demo@example.com", "plan": "starter"}'

# Submit a job (use the api_key from the response above)
curl -X POST http://localhost:8000/api/intake \
  -H "Content-Type: application/json" \
  -H "X-Client-Key: YOUR_API_KEY" \
  -d '{"project_name": "my-app", "description": "Fix the login button color to blue", "task_type": "bug_fix"}'

# Check job status
curl http://localhost:8000/api/jobs
```

---

## Quick Start with Docker

```bash
# Clone
git clone https://github.com/Miles0sage/openclaw-agents.git
cd openclaw-agents

# Configure
cp .env.example .env
# Edit .env — set GATEWAY_AUTH_TOKEN and at least one LLM provider key

# Start gateway + dashboard
docker compose up --build
```

The gateway will be available at `http://localhost:8000` and the Next.js dashboard at `http://localhost:3000`.

The compose setup mounts `./data` into the gateway container so job state and artifacts persist between restarts.

---

## Configuration

### Environment Variables

Copy `.env.example` and fill in your keys:

```bash
# Required
GATEWAY_AUTH_TOKEN=        # Admin auth token (required to start)

# LLM Providers (at least one required)
ANTHROPIC_API_KEY=        # Claude models
DEEPSEEK_API_KEY=         # Kimi/DeepSeek models (cheapest)

# Optional providers (fallback chain)
GEMINI_API_KEY=           # Google Gemini
OPENROUTER_API_KEY=       # OpenRouter (multi-model)
XAI_API_KEY=              # Grok models

# Notifications (optional)
SLACK_BOT_TOKEN=          # Slack notifications
TELEGRAM_BOT_TOKEN=       # Telegram alerts

# Storage (optional, falls back to local JSON)
SUPABASE_URL=             # Supabase for persistence
SUPABASE_SERVICE_KEY=     # Supabase service role key
```

### 4-Tier LLM Fallback

OpenClaw automatically falls back through providers if one fails:

1. **Primary**: Claude Opus (highest quality)
2. **Fast**: Kimi 2.5 / DeepSeek (95% cheaper)
3. **Budget**: Gemini Flash (free tier available)
4. **Emergency**: OpenRouter / Grok (last resort)

---

## Key Concepts

### Phase-Gated Tools

Tools are restricted by pipeline phase. A PLAN phase can't execute shell commands. An EXECUTE phase can't skip to DELIVER.

### Per-Agent Tool Allowlists

Each agent only sees tools relevant to its role. The Researcher can't deploy to production. The BettingBot can't modify source code.

### Reflexion Loop

After every job, OpenClaw stores a structured reflection:
- What worked
- What failed
- Missing tools
- Suggested improvements

Before the next similar job, these reflections are injected into the prompt.

### Hands (Scheduled Agents)

Pre-built autonomous agents that run on cron schedules:

```python
Hand(
    name="daily_cost_report",
    schedule="0 9 * * *",       # 9am daily
    handler=hand_daily_cost_report,
    description="Generate daily cost summary",
)
```

Built-in hands: cost reports, health checks, eval regression checks, AI news research, email triage, morning briefings.

### Circuit Breakers

Hands auto-disable after 5 consecutive failures. Jobs have cost caps and iteration limits. The system self-heals.

---

## Project Structure

```
openclaw-agents/
├── gateway.py              # FastAPI server (HTTP API)
├── autonomous_runner.py    # 5-phase job executor
├── agent_router.py         # Semantic agent dispatch
├── agent_tool_profiles.py  # Per-agent tool allowlists
├── agent_tools.py          # 85+ tool implementations
├── tool_router.py          # Phase-aware tool dispatch
├── scheduled_hands.py      # Cron-scheduled autonomous agents
├── reflexion.py            # Post-job self-improvement
├── eval_harness.py         # Quality scoring + regression detection
├── phase_scoring.py        # Per-phase Process Reward Model
├── cost_tracker.py         # Token-level cost accounting
├── cost_gates.py           # Budget guardrails
├── event_engine.py         # Job lifecycle events
├── reactions.py            # Auto-reaction handlers
├── approval_engine.py      # Human-in-the-loop gates
├── pipeline/
│   ├── models.py           # Phase enum, PlanStep, ExecutionPlan
│   ├── errors.py           # 6-category error classification
│   └── guardrails.py       # Cost caps, iteration limits
├── tests/                  # 190+ tests
├── benchmarks/             # HumanEval + custom eval suite
├── .env.example            # Template for API keys
├── requirements.txt        # Python dependencies
└── CLAUDE.md               # Agent soul definitions
```

---

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test category
python -m pytest tests/ -k "test_routing"
python -m pytest tests/ -k "test_cost"
python -m pytest tests/ -k "test_pipeline"
```

---

## Benchmarks

```bash
# Run eval harness (mock mode — no API calls)
python benchmarks/runner.py

# Run with real API calls
OPENCLAW_BENCH_BACKEND=api python benchmarks/runner.py
```

---

## License

MIT License — see [LICENSE](LICENSE).

---

## Contributing

1. Fork the repo
2. Create a feature branch
3. Make changes + add tests
4. Submit a PR

Focus areas: new agent souls, tool implementations, eval tasks, cost optimizations.

---

Built by [Cybershield Agency](https://cybershieldagency.com) — AI-first software engineering.
