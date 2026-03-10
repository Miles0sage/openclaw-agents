---
description: End-to-end workflow for building and delivering a client website
agent: overseer
tags: [workflow, website, delivery, client]
priority: medium
---

# Website Build Workflow

Step-by-step process for delivering a client website. [[overseer-coordination]] manages the flow.

## Phase 1 — Requirements (Overseer)

1. Gather requirements from client via [[slack-integration]] or [[telegram-integration]]
2. Decompose into tasks using [[priority-matrix]]
3. Create GitHub repo via [[github-tools]]
4. Set up project skill file (like [[barber-crm]] or [[delhi-palace]])
5. Estimate cost and timeline — check [[budget-enforcement]]

## Phase 2 — Build (CodeGen)

1. [[codegen-development]] scaffolds project (Next.js + Tailwind + Supabase)
2. Build core pages: landing, dashboard, auth
3. Set up database schema via [[supabase-data]]
4. Implement business logic (bookings, orders, payments)
5. Run tests continuously — fail fast

## Phase 3 — Security (Pentest)

1. [[pentest-security]] runs [[security-audit-workflow]] on completed code
2. Fix any critical/high findings before proceeding
3. Verify auth flows, payment handlers, API security
4. Check RLS policies with [[supabase-data]]

## Phase 4 — Deploy (CodeGen + Overseer)

1. Follow [[deployment-workflow]] for staging deploy
2. Client review on staging URL
3. Fix feedback items (loop back to Phase 2 if needed)
4. Production deploy with [[auto-approve-rules]] human approval
5. DNS and domain configuration

## Phase 5 — Handoff

1. Document admin access, environment variables, API keys
2. Set up [[cron-jobs]] for monitoring and backups
3. Configure alerts via [[slack-integration]]
4. Log project completion in [[memory-system]]

## Cost Estimate

Typical client website: $15-30 in API costs over 1-2 weeks.
Breakdown: 70% [[codegen-development]] (Kimi), 20% [[overseer-coordination]] (Opus), 10% [[pentest-security]] (Reasoner).
Track actual spend via [[budget-enforcement]].
