---
description: OpenClaw multi-agent platform — this system's self-knowledge for routing and architecture decisions
agent: any
tags: [project, openclaw, platform, agents, infrastructure]
priority: critical
---

# OpenClaw Platform

This is the system itself. Treat changes here with extra caution — breaking this breaks everything.

## Architecture

```
Cloudflare Worker → FastAPI Gateway (<your-vps-ip>:18789) → Agents
                                                          ├── Overseer (Claude Opus)
                                                          ├── CodeGen (Kimi 2.5)
                                                          └── Pentest (Kimi Reasoner)
```

## Key Components

- Gateway: `gateway.py` — FastAPI, session memory, agent routing
- Router: `agent_router.py` — 52+ keywords, intelligent task routing
- Heartbeat: `heartbeat_monitor.py` — 30s health checks, auto-recovery
- Workers: `workers/personal-assistant/`, `workers/agency-router/`
- Config: `config.json` — agent definitions, routing rules

## Live Endpoints

- Gateway: http://<your-vps-ip>:18789
- Personal Assistant: https://personal-assistant.amit-shah-5201.workers.dev
- Agency Router: https://agency-router.amit-shah-5201.workers.dev
- Token: `moltbot-secure-token-2026`

## Channels

- Telegram: active via [[telegram-integration]]
- Slack: ready via [[slack-integration]]
- Discord: code ready, needs bot token config
- Signal, iMessage, Line, Matrix: code exists in src/

## Modification Rules

- Any change to gateway.py requires [[pentest-security]] review
- Config changes need [[overseer-coordination]] approval per [[auto-approve-rules]]
- New agents must be registered in config.json and router
- Test with 187/187 tests passing before any deploy via [[deployment-workflow]]

## Cost

- Cloudflare Workers: $0-10/month
- VPS (gateway): included in existing server
- API costs: governed by [[budget-enforcement]] and [[cost-routing]]
