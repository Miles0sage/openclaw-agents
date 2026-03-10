---
description: Per-token costs for each available model — the source of truth for routing decisions
agent: overseer
tags: [cost, pricing, models, tokens]
priority: high
---

# Model Pricing

These are the rates that drive [[cost-routing]] decisions. Updated as of February 2026.

## Available Models

| Model         | Input $/1M | Output $/1M | Best For                         | Agent                     |
| ------------- | ---------- | ----------- | -------------------------------- | ------------------------- |
| Kimi 2.5      | $0.14      | $0.14       | Code, Q&A, formatting            | [[codegen-development]]   |
| Kimi Reasoner | $0.27      | $1.10       | Analysis, security, reasoning    | [[pentest-security]]      |
| Claude Haiku  | $0.25      | $1.25       | Fast classification, routing     | Router                    |
| Claude Sonnet | $3.00      | $15.00      | Mid-complexity tasks             | Fallback                  |
| Claude Opus   | $15.00     | $75.00      | Planning, client comms, critical | [[overseer-coordination]] |

## Cost Per Typical Task

| Task Type     | Model         | Avg Tokens      | Est Cost |
| ------------- | ------------- | --------------- | -------- |
| Bug fix       | Kimi 2.5      | 2K in / 1K out  | $0.0004  |
| Feature build | Kimi 2.5      | 5K in / 3K out  | $0.0011  |
| Security scan | Kimi Reasoner | 3K in / 2K out  | $0.003   |
| Task planning | Claude Opus   | 2K in / 1K out  | $0.105   |
| Client email  | Claude Opus   | 1K in / 500 out | $0.052   |

## Monthly Projections (100 req/day)

| Strategy           | Monthly Cost | Savings vs All-Opus |
| ------------------ | ------------ | ------------------- |
| All Opus           | $250         | baseline            |
| Smart routing      | $80          | 68%                 |
| Aggressive routing | $45          | 82%                 |

## Decision Rules

- If task cost estimate > $1 → require [[auto-approve-rules]] approval
- If daily spend > $20 → alert via [[budget-enforcement]]
- If monthly spend > $200 → halt non-critical tasks
- Always log actual cost to [[memory-system]] for tracking

## Rate Limits

- Kimi: 1000 RPM (no practical limit for us)
- Claude Opus: 50 RPM (throttle heavy usage)
- Claude Haiku: 200 RPM (comfortable for routing)

## When Prices Change

Update this file immediately. [[cost-routing]] and [[budget-enforcement]] depend on these numbers. Incorrect pricing leads to budget overruns or unnecessary model upgrades.
