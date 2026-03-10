# OpenClaw Launch Announcement Posts

Ready-to-post content for all platforms. Links already filled in.

**Repo:** https://github.com/Miles0sage/openclaw-agents
**Landing:** https://miles0sage.github.io/openclaw-agents/

---

## 1. TWITTER/X THREAD (8 tweets)

1/ just open-sourced something I've been building for a year: OpenClaw, a multi-agent AI framework for automating software engineering tasks. 12 specialized agents, 75+ tools, 510 jobs completed, $76 total cost.

shipped it because AI tooling should be hackable, not proprietary. code: https://github.com/Miles0sage/openclaw-agents

2/ the architecture is simple but works: overseer agent decomposes tasks -> routes to specialists (CodeGen, Debugger, SecurityAudit, Researcher, etc.) -> each uses the right LLM for the job -> tools run in parallel when possible -> verification gates prevent garbage output.

3/ why open-source this?

because the AI agent space is consolidating around big APIs, and I think builders should own their systems.

you want to add a new agent? fork it. replace Claude with Llama? patch it. integrate your custom tools? 30 lines of code.

4/ the economics are interesting: simple fixes cost $0.02, feature builds average $0.08, major refactors ~$0.50. that's because I built a 4-tier LLM fallback: Claude Opus -> MiniMax M2.5 -> Kimi 2.5 -> Gemini Flash. when one fails, the next picks up automatically.

5/ tested it hard: 592 passing tests, 90%+ success rate across 510 real jobs. error recovery is built in — the agents know how to handle stale dependencies, failed deploys, missing credentials. not perfect, but reliable enough to ship.

6/ MCP integration means you're not locked into my tools. want to add Notion, Linear, Slack, GitHub integrations? there's an MCP server for that. chain them together, build your own tool packages.

what's missing: proper caching, streaming responses, dashboard analytics. those are next.

7/ this works in dev and production. tested it on barber CRM, ecommerce sites, custom calculators. one person built this (no VC, no full-time team) by shipping fast and learning from failures.

if you're building agent systems, this is a reference implementation.

8/ star the repo if this is interesting: https://github.com/Miles0sage/openclaw-agents

docs: https://miles0sage.github.io/openclaw-agents/

MIT licensed, so use it however you want. feedback and PRs welcome.

---

## 2. REDDIT r/programming

**Title:** I open-sourced a production multi-agent AI framework that completed 510 jobs for $76. Here's what I learned building it solo.

**Body:**

I've been iterating on OpenClaw for about a year, and I finally cleaned it up enough to open-source. It's a Python framework that decomposes software engineering tasks into subtasks and routes them across 12 specialized AI agents.

**The Basics:**

- 510 jobs completed, $0.15 average cost per job
- 592 passing tests, 90%+ success rate
- 75+ MCP-integrated tools (code operations, database queries, browser automation, security audits, research)
- 4-tier LLM fallback (Claude Opus -> MiniMax M2.5 -> Kimi 2.5 -> Gemini Flash)
- Single person built it, no VC, no hire

**Architecture (really simple):**

Task input -> Gateway -> Overseer agent (reads task, routes to specialist) -> Specialist executes with tools -> Verification gate -> Output

The Overseer doesn't execute anything; it's just a smart router. CodeGen Pro handles frontend/backend tasks, Debugger does deep root cause analysis, Security Specialist does pentesting, Researcher queries external APIs. Each agent has different cost tiers and LLM choices.

**Why This Matters:**

The current AI tooling landscape is consolidating around big APIs. Companies like OpenAI (Swarm), Anthropic (some internal stuff), and startups are building closed-source agent systems. OpenClaw is hackable: you can swap LLMs, add custom agents, integrate your own tools via MCP, change routing logic.

**Real Numbers:**

- Simple fixes: $0.02-0.05
- Feature implementations: $0.08-0.15
- Major refactors: $0.30-0.50

Cost scales with task complexity, not agent selection. The framework finds the cheapest path to completion.

**What's Production-Ready:**

- Job routing and cost optimization
- Error recovery and reflexion quality gates
- Parallel execution of independent tasks
- Multi-LLM fallback (no single point of failure)
- Supabase integration for persistence

**What's Not Yet:**

- Caching layer (every job re-queries LLMs, could be cheaper)
- Streaming responses (current system waits for full output)
- Dashboard for observability (you get logs, not visualization)

**Tech Stack:**

Python 3.11+, Supabase (PostgreSQL), MCP (Model Context Protocol), support for Claude, Kimi, MiniMax, Bailian, Gemini.

**Why I'm Sharing:**

Because I learned more shipping this than I would have building it behind closed doors. The agent space needs reference implementations that people can actually fork, study, and deploy. Too much is proprietary right now.

Repo: https://github.com/Miles0sage/openclaw-agents
Docs: https://miles0sage.github.io/openclaw-agents/

MIT licensed. Questions in the comments or issues, happy to unblock people.

---

## 3. REDDIT r/MachineLearning

**Title:** [P] OpenClaw: Agent Routing Architecture with 4-Tier LLM Fallback — 590+ Tests, 510 Real Jobs, $76 Total Cost

**Body:**

I built and open-sourced OpenClaw, a multi-agent framework optimized for cost-efficient task routing and reliability. The system completed 510 real jobs at $0.15 average cost using a hierarchical decomposition approach with intelligent agent selection.

**Core Architecture:**

The framework uses a two-stage pipeline:

1. **Overseer Agent** (reads task, decomposes into subtasks, routes each to best specialist)
2. **Specialist Agents** (12 total: CodeGen Pro, Debugger, Security, Researcher, etc.)

Each specialist has:
- Dedicated LLM selection (based on cost/capability tradeoff)
- Task-specific tool allowlist (security agent doesn't get write access to databases)
- Quality gates (reflexion + verification before output)

**Reliability Innovation: 4-Tier LLM Fallback**

Instead of single-model dependency, the system cascades:
- Primary: Claude Opus (highest capability, $15/M)
- Fallback 1: MiniMax M2.5 (fast, cheap, $0.007/M)
- Fallback 2: Kimi 2.5 (long-context, $0.003/M)
- Fallback 3: Gemini Flash (free tier, unlimited)

If any tier fails (rate limit, API error, timeout), the system automatically retries with the next tier. Prevents single points of failure and distributes cost across multiple providers.

**Cost Optimization:**

The Overseer learns task difficulty and assigns agents accordingly:
- Simple: CodeGen Pro ($0.14/M input)
- Complex: CodeGen Elite ($0.30/M) or just accept longer execution time
- Trade-offs are explicit

Result: $0.15 average cost vs $5+ for naive "always use Opus" approach.

**Evaluation:**

- 592 passing tests (routing, error recovery, tool execution, cost management)
- 510 real production jobs across 4 projects
- 90%+ success rate
- Completion time: 12s-3min depending on complexity

**Key Design Decisions:**

1. **Hierarchical routing** over flat selection (Overseer bottleneck prevents route misses)
2. **Per-agent tool allowlists** over global tool access (security + cost)
3. **Verification gates** over raw output (checks for partial failures before returning)
4. **Reflexion loops** on complex tasks (agent reviews its own output, retries if needed)

**Limitations:**

- No caching (same query runs multiple times across jobs)
- No streaming (client waits for full response)
- Overseer is single-threaded bottleneck for task decomposition
- LLM fallback adds latency vs. single-model approach

MIT licensed. Built by one person without VC funding. Hackable: fork it, swap LLMs, add agents, integrate custom tools.

Repo: https://github.com/Miles0sage/openclaw-agents
Docs: https://miles0sage.github.io/openclaw-agents/

Feedback and PRs welcome. Interested in: caching strategies, streaming architecture, cost prediction models.

---

## 4. HACKER NEWS

**Title:** Show HN: OpenClaw - Autonomous Multi-Agent AI Framework (MIT Licensed)

**URL:** https://github.com/Miles0sage/openclaw-agents

---

## 5. HACKER NEWS COMMENT (post on your own submission)

Hey, I'll give some context since this is my work.

I built OpenClaw over a year as a solo project to automate code tasks across several real products (barber CRM, ecommerce site, a 1600-line calculation tool). The goal was simple: submit a task in English, get working code back.

The key insight was that different tasks need different LLMs. Writing a frontend component? CodeGen Pro is cheap and fast ($0.14/M). Debugging a race condition? Debugger uses Claude Opus ($15/M). Researching a library? Researcher uses Kimi ($0.003/M). So instead of paying Opus for everything, I built a router.

**Real numbers:**
- 510 jobs completed
- $76 total cost across all of them
- 592 tests covering routing, error recovery, tool execution
- 90%+ success rate

**Why open-source?**

The AI agent space is consolidating around proprietary APIs. I think builders should be able to fork a system, swap the LLM backend (Claude->Llama), add custom agents, integrate their own tools. This is a reference implementation for that.

**Current limitations I'm aware of:**
- No caching (each job re-queries LLMs from scratch)
- No streaming (waits for full response before returning)
- Overseer is single-threaded (bottleneck for large task decomposition)
- Cost prediction could be smarter

I've learned way more from shipping this publicly and getting feedback than I would have building it privately. The codebase is messy in some places but documented. Happy to answer questions or take PRs.

---

## 6. LINKEDIN

I just open-sourced something I've been building for a year: OpenClaw, an autonomous multi-agent AI framework.

Here's the story: I wanted to submit a task in English and get working code back. Not a chatbot. Not a prompt wrapper. An actual autonomous system that could design, code, test, and debug software.

So I built a router.

Instead of paying Claude Opus for every task, I built 12 specialized agents:
- CodeGen Pro for frontend/backend ($0.14/M)
- Debugger for root cause analysis (Claude Opus, $15/M)
- Security Specialist for pentesting ($0.27/M)
- Researcher for external queries ($0.003/M)
- Others for test generation, code review, content creation

Each agent gets only the tools it needs. Each uses the LLM that's best for the job.

The Results:
- 510 jobs completed
- $76 total cost ($0.15 per job average)
- 592 passing tests
- 90%+ success rate

One person. No VC. No full-time team. Just iteration and shipping.

Why I'm sharing this:

Because I think the AI tooling landscape needs reference implementations that people can actually use, fork, and modify. Too much is locked up in proprietary APIs.

OpenClaw is MIT licensed. Want to swap Claude for Llama? Fork it. Need a custom agent for your domain? 30 lines of code. Want to use your own MCP tools? Standard integration.

If you're building agent systems, this is a reference implementation.

GitHub: https://github.com/Miles0sage/openclaw-agents
Docs: https://miles0sage.github.io/openclaw-agents/

---

## 7. DEV.TO ARTICLE

**Title:** How I Built an Autonomous AI Agent System That Completes 510 Jobs for $76 (And Open-Sourced It)

**Tags:** ai, opensource, python, machinelearning

I spent a year building an autonomous multi-agent AI system that routes software engineering tasks across 12 specialized agents, each optimized for a specific domain. Today I'm open-sourcing it as OpenClaw.

Here's what I learned.

### The Problem

I wanted a system that could:
1. Accept a task in plain English
2. Break it down into subtasks
3. Route each subtask to the right agent
4. Execute with tools (code, database, browser, security scanning)
5. Verify the output before returning it

Not a chatbot. Not a prompt template. An actual autonomous system.

### The Architecture (Surprisingly Simple)

```
Task Input
    |
Gateway (HTTP API)
    |
Overseer Agent (reads task, decomposes, routes)
    |
Specialist Agents (CodeGen, Debugger, Security, etc.)
    |-- Each agent has a tool allowlist
    |-- Each agent has an LLM selection (Claude, Kimi, MiniMax, Gemini)
    |-- Each agent runs verification gates
    +-- Results compose into final output
```

### Why Task Routing Matters for Cost

Here's the key insight: **different tasks need different LLMs.**

If you use Claude Opus for every task, you pay $15/M input tokens. But:
- Simple frontend component? CodeGen Pro ($0.14/M) handles it fine
- Deep debugging? Debugger uses Opus because it's worth the cost
- Research query? Kimi ($0.003/M) is overkill but cheap enough
- Boilerplate code? Gemini Flash (free) works

By routing intelligently, I reduced cost from $5+ per job to $0.15 average.

### The 4-Tier LLM Fallback

Instead of depending on one model, I cascade:

```
tier_1 = Claude Opus ($15/M, highest capability)
tier_2 = MiniMax M2.5 ($0.007/M, fast)
tier_3 = Kimi 2.5 ($0.003/M, long-context)
tier_4 = Gemini Flash (free, unlimited)
```

If Claude times out or hits a rate limit, the system automatically retries with MiniMax. If MiniMax fails, Kimi. If Kimi fails, Gemini.

In production, this prevented ~15% of failures from turning into 100% downtime.

### Real-World Performance (510 Jobs, $76)

| Metric | Value |
|--------|-------|
| Jobs Completed | 510 |
| Total Cost | $76 |
| Avg Cost per Job | $0.15 |
| Success Rate | 90%+ |
| Passing Tests | 592 |
| Completion Time | 12 seconds-3 minutes |

Cost breakdown:
- Simple fixes: $0.02-0.05
- Feature implementations: $0.08-0.15
- Major refactors: $0.30-0.50

### The Tool System (75+ MCP Integrations)

Each agent gets only the tools it needs:
- **Code operations:** Git, GitHub API, file system
- **Databases:** PostgreSQL, SQLite queries
- **Browser automation:** Playwright for testing and web scraping
- **Security:** Vulnerability scanning
- **Research:** Web search, API queries, external data
- **Monitoring:** systemd, process management, log inspection

Security Specialist doesn't have write access to databases. CodeGen Pro doesn't have delete permissions.

### Testing: 592 Tests

I learned the hard way that you need to test:
- **Agent routing:** Does the task go to the right specialist?
- **Error recovery:** What happens when an LLM fails?
- **Cost management:** Are we staying within budget?
- **Tool execution:** Do the tools actually work?
- **Reflexion:** Can agents fix their own mistakes?

### Key Learnings

**1. Routing beats raw capability.** You don't need Opus for everything. Most jobs complete fine with cheaper models if you route correctly.

**2. Fallback chains prevent cascading failures.** When one LLM fails, your system should have a backup.

**3. Tool allowlists are security.** Don't give every agent access to everything. Restrict by role.

**4. Reflexion is worth it.** Let agents review their own output before returning. Catches 10-15% of mistakes.

**5. Testing autonomous systems is hard.** You need coverage for routing, error recovery, tool execution, and cost management.

### How to Use It

```bash
git clone https://github.com/Miles0sage/openclaw-agents.git
cd openclaw-agents
pip install -r requirements.txt
cp .env.example .env
# Add your API keys
python gateway.py
```

### What's Next

- **RepurposeOS**: Content repurposing engine built on OpenClaw
- **Caching layer** (save previous outputs, reuse if task is identical)
- **Streaming** (return output as generated)
- **Dashboard** (visualize job success, cost, latency)

MIT licensed. Feedback, issues, and PRs welcome.

Repository: https://github.com/Miles0sage/openclaw-agents
Documentation: https://miles0sage.github.io/openclaw-agents/
