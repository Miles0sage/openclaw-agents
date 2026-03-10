---
description: What to do when production goes down — immediate response, communication, and post-mortem
agent: overseer
tags: [incident, outage, response, postmortem, production]
priority: critical
---

# Incident Response

Production is down. Follow this playbook. Speed matters, but do not panic.

## Severity Classification

- **SEV1**: Complete outage — no users can access the system
- **SEV2**: Partial outage — some features broken, core still works
- **SEV3**: Degraded — slow performance, intermittent errors
- **SEV4**: Minor — cosmetic issues, non-critical bugs

## Immediate Response (First 5 Minutes)

### SEV1/SEV2

1. **Acknowledge** — post in [[slack-integration]] `#incidents`: "Investigating [project] outage"
2. **Diagnose** — check health endpoints on [[openclaw-platform]], Vercel, Northflank
3. **Rollback if obvious** — last deploy broke it? Revert per [[deployment-workflow]] rollback plan
4. **Escalate** — if not obvious, pull [[overseer-coordination]] + [[codegen-development]] immediately

### SEV3/SEV4

1. Log the issue in [[memory-system]]
2. Create issue via [[github-tools]]
3. Prioritize per [[priority-matrix]] (usually P1 for SEV3, P2 for SEV4)
4. Route to [[bug-fix-workflow]]

## Communication During Incident

- Update [[slack-integration]] every 15 minutes (even if no progress)
- Format: "Status: [investigating/identified/fixing/resolved]. ETA: [time]. Impact: [what users see]."
- Notify affected clients via [[telegram-integration]] if user-facing
- Do NOT speculate about cause in public channels

## Common Root Causes

- Port mismatch (18789 vs 8000) — see [[openclaw-platform]] deployment history
- Secret rotation missed — check env vars
- Dependency broke — check [[security-audit-workflow]] last scan
- Budget exceeded — check [[budget-enforcement]] status
- Agent unresponsive — check heartbeat per [[error-recovery]]

## Post-Mortem (Within 24 Hours)

1. Timeline: what happened, when, in what order
2. Root cause: why it happened (5 Whys technique)
3. Impact: how many users affected, for how long
4. Fix: what resolved it
5. Prevention: what changes prevent recurrence
6. Store in [[memory-system]] for future reference

## Anti-Patterns

- Never ignore alerts hoping they resolve themselves
- Never deploy a fix without testing (even under pressure)
- Never blame an agent — fix the system that allowed the failure
- Never skip the post-mortem — recurring incidents are worse than the first one
