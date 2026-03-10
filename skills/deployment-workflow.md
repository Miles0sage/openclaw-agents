---
description: Staging to testing to production deployment process for all projects
agent: codegen
tags: [workflow, deployment, staging, production, cicd]
priority: critical
---

# Deployment Workflow

Every production deploy follows this flow. No exceptions. No shortcuts.

## Pre-Deploy Checklist

- [ ] All tests passing (zero failures, zero skips on critical tests)
- [ ] [[pentest-security]] audit complete (no critical/high findings)
- [ ] [[auto-approve-rules]] checked — human approval obtained if required
- [ ] Budget verified via [[budget-enforcement]] — deploy cost within limits
- [ ] Secrets verified — no keys in code, all env vars set

## Platform-Specific Deploy

### Vercel (Barber CRM, Delhi Palace)

1. Push to main branch via [[github-tools]]
2. Vercel auto-deploys (webhook trigger)
3. Verify preview URL before promoting
4. Check Vercel dashboard for build errors
5. Monitor for 15 minutes post-deploy

### Cloudflare Workers (OpenClaw Workers)

1. Run `wrangler deploy` from worker directory
2. Verify with health check endpoint
3. Check Cloudflare dashboard for errors
4. Test via curl against production URL

### Northflank (OpenClaw Gateway)

1. Push to main — Northflank auto-builds
2. Wait for build success (Python buildpack, ~5-10 min)
3. Verify container health (port 18789, not 8000)
4. Check logs for startup errors
5. Test gateway health endpoint

### Local/VPS (Direct Deploy)

1. SSH to VPS
2. Pull latest code
3. Restart service (systemd or Docker)
4. Verify health endpoint
5. Check heartbeat via [[openclaw-platform]] monitor

## Rollback Plan

If production deploy causes issues:

1. Identify the problem (logs, health checks, user reports)
2. Revert to last known good commit: `git revert HEAD && git push`
3. For Northflank: previous build auto-restores
4. For Vercel: instant rollback in dashboard
5. For Workers: `wrangler rollback`
6. Notify team via [[slack-integration]]
7. Log incident in [[memory-system]]
8. Follow [[error-recovery]] for root cause analysis

## Post-Deploy

1. Smoke test all critical paths (auth, payments, core features)
2. Monitor error rates for 30 minutes
3. Update status in [[memory-system]]
4. Close related issues via [[github-tools]]
