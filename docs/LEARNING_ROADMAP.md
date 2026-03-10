# Miles' Learning Roadmap: Coding + AI Agents

## Track 1: Python Fundamentals

### Week 1-2: Core Python
- **Variables, types, functions, loops, conditionals**
- Resource: [Python for Everybody](https://www.py4e.com/) (free, video + exercises)
- Practice: Read `pipeline/models.py` — it's 75 lines of clean Python (dataclasses, enums)
- Exercise: Add a new field to `PlanStep` and make the test pass

### Week 3-4: Web & APIs
- **HTTP requests, JSON, REST APIs, FastAPI basics**
- Resource: [FastAPI Tutorial](https://fastapi.tiangolo.com/tutorial/) (free)
- Practice: Read `gateway.py` (370 lines) — it's a FastAPI app
- Exercise: Add a new API endpoint to the gateway that returns system uptime

### Week 5-6: Git & Dev Workflow
- **Branches, commits, PRs, code review, CI**
- Resource: [Git Immersion](https://gitimmersion.com/) (free)
- Practice: Make a branch, change something, open a PR
- Exercise: Fix a test, commit it, push it

## Track 2: AI Agent Development

### Week 1: How LLMs Work
- **Tokens, prompts, temperature, system prompts, tool calling**
- Read: OpenClaw's `CLAUDE.md` — you already wrote the agent "souls"
- Understand: Why different models cost different amounts
- Key concept: An LLM is a function that takes text in and produces text out

### Week 2-3: Build Your First Agent
- **Single-agent loop: prompt -> LLM -> tool use -> response**
- Read: `pipeline/errors.py` — see how error classification works
- Build: A simple script that calls an LLM API and uses a tool
- Resource: [Anthropic Cookbook](https://github.com/anthropics/anthropic-cookbook)

### Week 4-5: Multi-Agent Systems
- **How OpenClaw decomposes tasks and routes to specialists**
- Read: `supervisor.py` (557 lines) — the decomposition engine
- Read: `autonomous_runner.py` lines 855-938 — agent selection logic
- Key concepts: Agent routing, tool calling, memory, guardrails

### Week 6+: Advanced Topics
- **Evaluation, self-improvement, RAG**
- Read: `pipeline/guardrails.py` — safety limits prevent runaway agents
- Build: Add a new agent type to OpenClaw
- Study: How `reflexion.py` lets agents learn from past failures

## Recommended Order

1. Start with Python basics (Track 1, Week 1-2) while Claude handles the code
2. Read OpenClaw code alongside learning — it's real production code
3. Start Track 2 once you can read Python comfortably
4. By week 4, you should be able to modify OpenClaw configs and small features
5. By week 8, you should be able to add new agent types and tools

## How to Practice Inside OpenClaw

| Level | What to do |
|-------|-----------|
| Beginner | Read `pipeline/models.py`, modify a dataclass field |
| Intermediate | Add a new test in `tests/`, make it pass |
| Advanced | Add a new MCP tool to `agent_tools.py` |
| Expert | Add a new agent type with its own soul in `CLAUDE.md` |
