---
description: What to test, how to test, and when tests gate deployment
agent: codegen
tags: [testing, quality, ci, gates]
priority: high
---

# Testing Strategy

Tests are the gate between code and production. No tests, no deploy.

## Test Pyramid

- **Unit tests** (70%): Fast, isolated, test single functions
- **Integration tests** (20%): Test module interactions, API endpoints, database queries
- **E2E tests** (10%): Full user flow, browser automation (only for critical paths)

## Per-Project Requirements

### [[barber-crm]]

- Auth flows: login, signup, session management
- Booking flow: create, modify, cancel
- Payment flow: Stripe checkout, webhook handling
- API endpoints: all CRUD operations

### [[delhi-palace]]

- Order submission and real-time updates
- Dashboard authentication
- Menu display and filtering
- Supabase real-time subscriptions

### [[openclaw-platform]]

- 187/187 tests must pass (routing, workflows, integration)
- Agent routing accuracy (keyword matching, complexity classification)
- Gateway health endpoints
- Session persistence across restarts

### [[prestress-calc]]

- 358/358 tests must pass
- Engineering calculations validated against ACI 318-19 examples
- Unit conversion accuracy (pint)
- Edge cases: zero values, extreme spans, unusual strand patterns

## Test-Driven Bug Fixes

Every bug fix via [[bug-fix-workflow]] must include:

1. A test that reproduces the bug (fails before fix)
2. The fix itself
3. Verification that the new test passes
4. Full suite still passes (no regressions)

## When Tests Block Deploy

- Any test failure blocks production deploy per [[deployment-workflow]]
- Flaky tests must be fixed or quarantined, not skipped
- New features require tests before PR merge via [[github-tools]]
- [[auto-approve-rules]]: code without tests is never auto-approved

## Cost

Tests run locally or in CI — zero API cost. [[codegen-development]] generates tests on Kimi 2.5 (cheapest model). Testing is the highest-ROI activity in the system.
