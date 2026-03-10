---
description: How to prioritize competing tasks when multiple requests arrive simultaneously
agent: overseer
tags: [priority, triage, scheduling, delegation]
priority: high
---

# Priority Matrix

When multiple tasks compete for attention, use this matrix. Do not rely on gut feel.

## Priority Levels

### P0 — Drop Everything

- Production is down (any live project)
- Security breach or data leak detected by [[pentest-security]]
- Payment system broken in [[barber-crm]] or [[delhi-palace]]
- Budget enforcement failure in [[budget-enforcement]]
- Action: All agents pivot. [[overseer-coordination]] takes command.

### P1 — Today

- Client-facing bugs (users are seeing errors)
- Failing CI/CD pipeline blocking deploys via [[deployment-workflow]]
- Expiring API keys or certificates
- Scheduled demo or presentation prep
- Action: Next task in queue. Preempts P2/P3 work.

### P2 — This Week

- New feature development for [[barber-crm]], [[delhi-palace]]
- Phase progression on [[prestress-calc]]
- Infrastructure improvements to [[openclaw-platform]]
- Security audit findings (non-critical) from [[security-audit-workflow]]
- Action: Normal queue processing via [[codegen-development]].

### P3 — Backlog

- Documentation updates
- Code refactoring (no user-facing impact)
- [[concrete-canoe]] software tasks (competition timeline permitting)
- Nice-to-have features, UI polish
- Action: Fill gaps between higher-priority work.

## Tie-Breaking Rules

When two tasks share the same priority level:

1. Revenue-generating projects first ([[barber-crm]] > [[concrete-canoe]])
2. Blocked tasks first (unblocks other work)
3. Smaller tasks first (quick wins build momentum)
4. Older tasks first (prevent stale backlog)

## Interruption Policy

- P0 interrupts anything immediately
- P1 interrupts P2/P3 at next natural break point
- P2 never interrupts P1
- P3 never interrupts anything — only runs when queue is empty

## Cost Awareness

Higher priority does not mean more expensive model. A P0 bug fix might still run on Kimi 2.5 via [[cost-routing]] if it is a straightforward fix. Priority controls ordering, not model selection.
