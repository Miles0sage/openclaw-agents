# OpenClaw — Vision Document

## The Problem

Right now, AI coding tools (Cline, Claude Code, Cursor, Copilot) are **single-agent, single-session**. You sit there, prompt by prompt, babysitting the AI. You're the bottleneck.

- One task at a time
- You manage context, you decide what to do next
- When you close the tab, work stops
- No memory between sessions
- No cost control — burn through API credits blindly

## What OpenClaw Is

**OpenClaw is an autonomous AI agency that runs 24/7 without you.**

It's not a coding assistant. It's a **team of AI agents** with a project manager that:

1. **Takes a job** ("make the KDS page production-ready")
2. **Researches** the codebase autonomously
3. **Creates a plan** with steps delegated to specialist agents
4. **Executes** — coder agent writes code, hacker agent audits security, database agent handles migrations
5. **Verifies** — runs builds, tests, checks for errors
6. **Delivers** — commits, pushes, notifies you on Slack

You wake up, check Slack, and the work is done.

## Architecture

```
          ┌─────────────────────────────┐
          │      Job Queue (FIFO)       │
          │  "Fix auth bug" "Add SEO"   │
          └──────────┬──────────────────┘
                     │
          ┌──────────▼──────────────────┐
          │    Project Manager Agent     │
          │  (orchestrates everything)   │
          └──────────┬──────────────────┘
                     │ delegates
        ┌────────────┼────────────────┐
        ▼            ▼                ▼
   ┌─────────┐ ┌──────────┐  ┌────────────┐
   │  Coder  │ │ Hacker   │  │  Research   │
   │  Agent  │ │  Agent   │  │   Agent     │
   │(writes) │ │(audits)  │  │ (searches)  │
   └─────────┘ └──────────┘  └────────────┘
        │            │                │
        ▼            ▼                ▼
   ┌─────────────────────────────────────┐
   │        34 MCP Tools                 │
   │  git, shell, file ops, web search,  │
   │  deploy, slack, math, scraping...   │
   └─────────────────────────────────────┘
        │
        ▼
   ┌─────────────────────────────────────┐
   │      Multi-Provider Chain           │
   │  Gemini (FREE) → Kimi → MiniMax    │
   │        → Anthropic (fallback)       │
   └─────────────────────────────────────┘
```

## Key Differentiators vs Cline/Cursor/Claude Code

| Feature              | Cline/Cursor      | OpenClaw                            |
| -------------------- | ----------------- | ----------------------------------- |
| Runs without you     | No                | Yes — fully autonomous              |
| Multi-agent          | No — single agent | Yes — PM delegates to specialists   |
| Cost control         | None              | Budget gates, per-job cost tracking |
| Provider flexibility | One provider      | 4 providers, cheapest-first routing |
| Free tier            | No                | Gemini 3 Flash = $0.00 for research |
| Job queue            | No                | FIFO queue, processes overnight     |
| Tool filtering       | All tools always  | Per-agent allowlists (security)     |
| Memory               | Per-session       | Persistent across jobs              |
| Notifications        | None              | Slack alerts on complete/fail       |
| Self-hosted          | No                | Your VPS, your data, your control   |

## Business Model

### Three Revenue Streams

1. **AI Agency Services** — clients submit jobs, OpenClaw executes, you review & deliver. $500-5K per project. Cost: $2-15 in API credits.

2. **SaaS Platform** — developers run their own OpenClaw instance. $49-199/mo.

3. **Managed AI Ops** — retainer clients ($1-3K/mo) get ongoing AI-powered development.

## Current State (v2.3)

- 5-phase autonomous pipeline (research → plan → execute → verify → deliver)
- 34 MCP tools (code, web, deploy, compute, communication)
- 4 AI providers (Anthropic, Gemini, Kimi, MiniMax)
- Multi-agent delegation (PM → coder/hacker/research/database)
- Cost tracking with budget gates
- Prompt caching (50-90% cost reduction)
- Slack notifications
- Gateway API on VPS
- Web dashboard

## Roadmap

- Systemd service — auto-restart, production reliability
- Telegram/Discord alerts
- Client portal — non-technical clients submit jobs via web UI
- PicoClaw — lightweight version running local models (zero API cost)
- Billing integration — Stripe, auto-invoice clients
- Multi-repo support — manage entire organizations

## The One-Liner

> **OpenClaw is a self-hosted AI development team that takes jobs, delegates to specialist agents, and ships code while you sleep.**
