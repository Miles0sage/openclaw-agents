---
description: When and how to route tasks to cheap vs expensive models
agent: overseer
tags: [cost, routing, optimization]
priority: high
---

# Cost Routing

Route by complexity, not by habit. Default to the cheapest model that can handle the task.

## Rules

- Simple Q&A, formatting, file search → Kimi 2.5 ($0.14/1M) via [[codegen-development]]
- Code generation, bug fixes → Kimi 2.5 via [[codegen-development]]
- Security analysis, threat modeling → Kimi Reasoner ($0.27/1M) via [[pentest-security]]
- Complex reasoning, planning, client comms → Claude Opus ($15/1M) via [[overseer-coordination]]
- Database schema changes → Claude Opus via [[supabase-data]] (accuracy critical)
- Test generation → Kimi 2.5 (always, no exceptions)

## Keyword-Based Fast Routing

These keywords skip the LLM classifier entirely (zero cost):

- `fix`, `bug`, `error`, `lint`, `format`, `style` → [[codegen-development]] on Kimi 2.5
- `scan`, `audit`, `vulnerability`, `owasp`, `cve` → [[pentest-security]] on Kimi Reasoner
- `schema`, `migrate`, `rls`, `table`, `query` → [[supabase-data]] on Opus
- `plan`, `prioritize`, `delegate`, `status`, `report` → [[overseer-coordination]] on Opus

## Cost Impact

At current usage (~100 requests/day):

- All Opus: ~$250/month
- With routing: ~$80/month (68% savings)
- See [[budget-enforcement]] for limits and [[model-pricing]] for exact rates

## When to Escalate

- Kimi returns low-confidence or incoherent answer → retry with Opus
- Task involves production deploy → always Opus via [[auto-approve-rules]]
- Security finding needs validation → escalate to Opus
- Three consecutive failures on cheap model → escalate per [[error-recovery]]

## When NOT to Downgrade

- Client-facing text (emails, Slack messages to users)
- Financial calculations (Stripe, billing, invoicing)
- Auth and session management code
- Anything touching [[barber-crm]] or [[delhi-palace]] payment flows
