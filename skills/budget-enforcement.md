---
description: Daily and monthly spending limits, alerts, and what happens when budgets are exceeded
agent: overseer
tags: [cost, budget, limits, alerts, enforcement]
priority: critical
---

# Budget Enforcement

Hard limits exist to prevent runaway spending. These are non-negotiable.

## Limits

- **Daily limit:** $20
- **Monthly limit:** $1,000
- **Single task limit:** $5 (requires human approval above this)
- **Per-agent daily limit:** $10 (prevents one agent from hogging budget)

## Alert Thresholds

- 50% of daily limit ($10) → info message via [[slack-integration]]
- 75% of daily limit ($15) → warning via [[slack-integration]] + [[telegram-integration]]
- 90% of daily limit ($18) → critical alert, pause non-P0 tasks
- 100% of daily limit ($20) → halt all non-P0 tasks immediately

## When Budget is Exceeded

1. **Halt** all P2/P3 tasks per [[priority-matrix]]
2. **Downgrade** P1 tasks to cheapest possible model per [[cost-routing]]
3. **Continue** P0 tasks on any model needed (production down = spend what it takes)
4. **Alert** human via [[slack-integration]] and [[telegram-integration]]
5. **Log** the overrun event in [[memory-system]] with cause analysis

## Tracking

- Real-time tracking via `/tmp/openclaw_costs.jsonl` in [[memory-system]]
- Every API call logs: agent, model, tokens, cost_usd
- Queryable via `/api/costs/summary` endpoint on [[openclaw-platform]]
- [[overseer-coordination]] checks budget before delegating expensive tasks

## Monthly Reset

- Counters reset on 1st of each month at 00:00 UTC via [[cron-jobs]]
- Previous month archived in [[memory-system]]
- Monthly report generated and sent via [[slack-integration]]

## Optimization Levers

When budget is tight:

1. Increase Kimi usage ratio per [[cost-routing]] (cheapest first)
2. Batch similar tasks (fewer API calls)
3. Cache common responses in [[memory-system]] (avoid repeat queries)
4. Defer P3 tasks to next budget period
5. Review [[cost-optimization-patterns]] for structural savings

## Anti-Patterns

- Never disable budget enforcement "just for this task"
- Never split a large task into small ones to bypass per-task limits
- Never use Opus for tasks Kimi can handle just because budget has room
- See [[model-pricing]] for exact rates to verify routing decisions
