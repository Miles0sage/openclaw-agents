---
description: What actions get auto-approved vs require human confirmation
agent: overseer
tags: [approval, safety, governance, automation]
priority: critical
---

# Auto-Approve Rules

Not everything needs human approval. But some things absolutely do.

## Auto-Approve (No Human Needed)

- Read-only operations: file search, code review, status checks
- Test execution: running existing test suites
- Formatting and linting: code style fixes
- Documentation updates: README, comments, inline docs
- Non-production deploys: staging, preview, local
- Cost queries: checking budget status via [[budget-enforcement]]
- Memory reads: loading session context via [[memory-system]]

## Require Human Approval

- Production deployments via [[deployment-workflow]] — always confirm
- Database schema migrations via [[supabase-data]] — destructive if wrong
- Spending above $5 in a single task — flag via [[budget-enforcement]]
- Deleting files, branches, or data — irreversible
- API key rotation or secret changes — security sensitive
- New agent registration in [[openclaw-platform]] — architecture change
- Any action on payment systems (Stripe) in [[barber-crm]] or [[delhi-palace]]

## Conditional Auto-Approve

- Bug fixes: auto-approve IF tests pass AND no security flags from [[pentest-security]]
- New features: auto-approve IF tests pass AND cost under $2 AND non-payment code
- PR creation via [[github-tools]]: auto-approve (humans review PRs anyway)
- Cron job changes via [[cron-jobs]]: auto-approve IF non-destructive

## Escalation Path

1. Task arrives at [[overseer-coordination]]
2. Check this file's rules
3. If auto-approve → proceed, log decision via [[memory-system]]
4. If human needed → send approval request via [[slack-integration]] or [[telegram-integration]]
5. Wait for response (timeout: 30 minutes, then remind)
6. If no response in 2 hours → park task, move to next

## Anti-Patterns

- Never auto-approve "just this once" for production deploys
- Never batch an approval-required action with auto-approved ones to sneak it through
- Never approve your own security review — [[pentest-security]] reviews [[codegen-development]], not itself
