---
description: Issue triage through fix, test, and deploy — the standard bug resolution flow
agent: overseer
tags: [workflow, bugfix, triage, testing]
priority: high
---

# Bug Fix Workflow

Fast, reliable bug resolution. Most bugs should be fixed and deployed within 1 hour.

## Step 1 — Triage (Overseer, 5 min)

1. Receive bug report via [[slack-integration]], [[telegram-integration]], or [[github-tools]]
2. Classify severity using [[priority-matrix]] (P0-P3)
3. Identify affected project: [[barber-crm]], [[delhi-palace]], [[openclaw-platform]], [[prestress-calc]]
4. Check if it is a known issue in [[memory-system]]

## Step 2 — Reproduce (CodeGen, 10 min)

1. [[codegen-development]] reads the error and attempts to reproduce
2. If reproducible → proceed to fix
3. If not reproducible → request more context, check logs
4. If intermittent → add logging, wait for next occurrence

## Step 3 — Fix (CodeGen, 15-30 min)

1. [[codegen-development]] writes the fix on a feature branch
2. Write a regression test that would have caught the bug
3. Run full test suite — must pass with zero failures
4. If fix touches auth/payments → route to [[pentest-security]] for review

## Step 4 — Review (Overseer, 5 min)

1. [[overseer-coordination]] reviews the fix against the original report
2. Check [[auto-approve-rules]] — does this need human approval?
3. If auto-approvable → proceed to deploy
4. If not → request human review via [[slack-integration]]

## Step 5 — Deploy (CodeGen, 10 min)

1. Follow [[deployment-workflow]] (staging first if P1+)
2. Verify fix on staging
3. Deploy to production
4. Monitor for 15 minutes post-deploy

## Step 6 — Close (Overseer, 2 min)

1. Close GitHub issue via [[github-tools]]
2. Notify reporter via original channel
3. Log fix in [[memory-system]] for future reference
4. If root cause suggests systemic issue → create follow-up task

## Cost

Typical bug fix: $0.10-0.50 (Kimi 2.5 for code, minimal Opus for triage).
Per [[cost-routing]], only escalate to Opus if Kimi cannot identify the fix.
