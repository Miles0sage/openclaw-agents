---
description: Scheduled automation — what runs when, and what triggers it
agent: overseer
tags: [tools, automation, cron, scheduled, monitoring]
priority: medium
---

# Cron Jobs

Automated tasks that run on schedule. Reduces manual intervention and catches problems early.

## Active Schedules

### Every 30 Seconds

- **Heartbeat monitor** — checks agent health in [[openclaw-platform]]
- Auto-recovery for unresponsive agents per [[error-recovery]]

### Every Hour

- **Cost snapshot** — log current spend to [[memory-system]]
- Check against [[budget-enforcement]] thresholds
- Alert via [[slack-integration]] if approaching daily limit

### Daily (02:00 UTC)

- **Security dependency scan** — `npm audit` / `pip-audit` on all projects
- Part of [[security-audit-workflow]] step 1
- Results logged, critical findings trigger [[bug-fix-workflow]]

### Weekly (Monday 06:00 UTC)

- **Full security audit** — [[security-audit-workflow]] on all active projects
- Report sent to [[overseer-coordination]] for review
- Findings prioritized per [[priority-matrix]]

### Monthly (1st, 00:00 UTC)

- **Budget reset** — monthly counters reset in [[budget-enforcement]]
- **Cost report** — full month summary via [[slack-integration]]
- **Memory cleanup** — archive old sessions in [[memory-system]]
- **Dependency update check** — identify outdated packages

## Adding New Cron Jobs

1. Define the schedule and task
2. Verify it does not conflict with existing jobs
3. Ensure it has [[error-recovery]] fallback
4. Log execution results in [[memory-system]]
5. Get approval from [[overseer-coordination]] per [[auto-approve-rules]]

## Anti-Patterns

- Never schedule expensive operations (Opus calls) in cron — use cheap models
- Never schedule destructive operations without human approval
- Never let cron jobs accumulate without review — audit quarterly
