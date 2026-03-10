---
description: Full OWASP Top 10 security audit process for any project
agent: pentest
tags: [workflow, security, owasp, audit]
priority: high
---

# Security Audit Workflow

Systematic security review. Run before every production deploy and weekly via [[cron-jobs]].

## Step 1 — Dependency Scan (Kimi 2.5, 5 min)

1. Run `npm audit` / `pip-audit` on the project
2. Check for known CVEs in dependencies
3. Flag any critical/high severity vulnerabilities
4. Auto-fix where safe (`npm audit fix`), escalate breaking changes

## Step 2 — Static Analysis (Kimi Reasoner, 15 min)

1. Scan all API routes for input validation issues
2. Check for SQL injection (raw queries, missing parameterization)
3. Check for XSS (unescaped user input in templates)
4. Check for CSRF (missing tokens on state-changing endpoints)
5. Check for IDOR (authorization checks on every endpoint)

## Step 3 — Auth Review (Kimi Reasoner, 10 min)

1. Verify session management (expiry, rotation, secure flags)
2. Check password/PIN handling (hashing, not plaintext)
3. Review API key exposure (not in client code, not in git history)
4. Verify RLS policies with [[supabase-data]]

## Step 4 — Infrastructure Review (Kimi Reasoner, 10 min)

1. Check CORS configuration (not wildcard in production)
2. Verify HTTPS enforcement (no mixed content)
3. Check rate limiting on all public endpoints
4. Review Cloudflare/Vercel security headers
5. Verify secrets are in env vars, not code — cross-check with [[github-tools]] history

## Step 5 — Report (Pentest → Overseer, 5 min)

1. Generate findings report with severity ratings
2. Send to [[overseer-coordination]] for prioritization
3. Critical findings → immediate fix via [[bug-fix-workflow]]
4. High findings → block deployment per [[auto-approve-rules]]
5. Medium/Low → add to backlog per [[priority-matrix]]
6. Log audit results in [[memory-system]]

## Project-Specific Checklists

- [[barber-crm]]: Stripe webhooks, Vapi auth, NextAuth config, admin PIN
- [[delhi-palace]]: Supabase RLS, admin PIN, order submission validation
- [[openclaw-platform]]: Gateway token auth, rate limiting, session isolation

## Cost

Full audit: ~$0.50-1.00 (mostly Kimi Reasoner at $0.27/1M).
Per [[cost-routing]], only escalate novel findings to Opus.
