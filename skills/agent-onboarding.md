---
description: How to add a new agent to the system — registration, routing, testing, and deployment
agent: overseer
tags: [agents, onboarding, setup, configuration]
priority: medium
---

# Agent Onboarding

Adding a new agent to [[openclaw-platform]] is a structured process. Follow every step.

## Step 1 — Define the Agent

1. What does this agent do? (single responsibility)
2. Which model does it run on? (see [[model-pricing]])
3. What keywords route to it? (see [[cost-routing]])
4. What projects does it serve? (see project skill files)

## Step 2 — Create Skill File

1. Create `./skills/{agent-name}.md` following this template
2. Include: description, capabilities, model selection, anti-patterns
3. Add [[wikilinks]] to related skills (projects, workflows, tools)
4. Update [[index]] to include the new agent under Agent Capabilities

## Step 3 — Register in Config

1. Add agent definition to `config.json` in [[openclaw-platform]]
2. Include: name, model, endpoint, health check URL, keywords
3. Update `agent_router.py` with new routing keywords
4. Update `heartbeat_monitor.py` to track the new agent

## Step 4 — Test

1. Write routing tests: verify keywords route to new agent
2. Write capability tests: verify agent produces correct output
3. Write integration tests: verify agent works with [[overseer-coordination]]
4. All 187+ tests must still pass (no regressions)

## Step 5 — Deploy

1. Follow [[deployment-workflow]] for staging deploy
2. Verify agent health check via heartbeat monitor
3. Test routing via curl: `POST /api/route {"message": "keyword test"}`
4. Get approval from [[auto-approve-rules]] for production deploy
5. Deploy to production
6. Monitor for 30 minutes via [[cron-jobs]] heartbeat

## Step 6 — Announce

1. Notify team via [[slack-integration]]
2. Update [[overseer-coordination]] delegation rules
3. Log in [[memory-system]] for future reference

## Current Agents

- [[overseer-coordination]] — Claude Opus
- [[codegen-development]] — Kimi 2.5
- [[pentest-security]] — Kimi Reasoner
- [[supabase-data]] — Claude Opus

## Estimated Time

New agent onboarding: 2-4 hours (including tests and deploy).
