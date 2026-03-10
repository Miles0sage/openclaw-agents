---
description: What to do when agents fail, models return errors, or deployments break
agent: any
tags: [errors, recovery, resilience, fallback]
priority: high
---

# Error Recovery

Things break. Have a plan. Follow these steps in order — do not skip levels.

## Model Failure (API errors, timeouts, bad output)

1. **Retry once** with same model and same prompt (transient errors are common)
2. **Retry with more context** — add examples, clarify constraints
3. **Escalate model** — Kimi 2.5 → Kimi Reasoner → Claude Opus per [[cost-routing]]
4. **Flag to Overseer** — if Opus also fails, [[overseer-coordination]] decides next step
5. **Park the task** — log failure in [[memory-system]], move to next task, revisit later

## Deployment Failure

1. Check [[deployment-workflow]] prerequisites — did tests pass? Did [[pentest-security]] approve?
2. Check logs — Northflank, Vercel, or Cloudflare dashboard
3. Common fixes:
   - Port mismatch (gateway runs on 18789, not 8000) — see [[openclaw-platform]]
   - Build OOM — reduce parallelism or use buildpack instead of Docker
   - Secret missing — verify env vars are set
4. If rollback needed — revert to last known good commit via [[github-tools]]
5. Notify via [[slack-integration]] with error details

## Test Failure

1. Read the error message — 80% of the time it tells you exactly what is wrong
2. Check if it is a flaky test (run again) vs a real regression
3. If real regression — [[codegen-development]] fixes, re-runs full suite
4. If flaky — fix the test itself (timing, state, ordering issues)
5. Never skip failing tests to ship faster — see [[auto-approve-rules]]

## Budget Overrun

1. Immediately halt non-critical tasks per [[budget-enforcement]]
2. Check [[model-pricing]] — are we routing correctly per [[cost-routing]]?
3. Report to [[overseer-coordination]] with cost breakdown
4. Resume only critical tasks until budget resets

## Agent Unresponsive

1. [[heartbeat_monitor]] detects within 30 seconds
2. Auto-restart attempted (3 retries with 10s backoff)
3. If still down — route tasks to backup agent per [[cost-routing]]
4. Alert via [[slack-integration]]
5. Log incident in [[memory-system]] for post-mortem
