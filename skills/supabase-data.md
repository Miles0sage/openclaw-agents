---
description: Database agent handles Supabase queries, schema migrations, RLS policies, and data integrity
agent: supabase
tags: [database, supabase, schema, rls, data]
priority: high
---

# Supabase Data

The Supabase agent manages all database operations. Uses Claude Opus for schema changes (accuracy critical) and Kimi 2.5 for read queries.

## Capabilities

- Schema design and migration generation
- Row Level Security (RLS) policy creation and testing
- Query optimization and indexing recommendations
- Data validation and integrity checks
- Real-time subscription setup

## Active Databases

- [[barber-crm]]: `banxtacevgopeczuzycz.supabase.co` — orders, bookings, services, clients
- [[delhi-palace]]: Supabase instance — orders table, real-time subscriptions
- [[openclaw-platform]]: D1 database (Cloudflare, not Supabase) — sessions, costs

## Model Selection

- Read queries, data lookups → Kimi 2.5 per [[cost-routing]]
- Schema migrations → Claude Opus (must be correct first time)
- RLS policy creation → Claude Opus (security-critical, reviewed by [[pentest-security]])
- Index recommendations → Kimi Reasoner (needs analysis)

## Schema Change Protocol

1. Generate migration SQL
2. Review with [[pentest-security]] for RLS implications
3. Test in staging/local environment
4. Get approval from [[overseer-coordination]] per [[auto-approve-rules]]
5. Apply migration via [[deployment-workflow]]
6. Verify data integrity post-migration

## RLS Rules

Every table must have RLS enabled. Default policies:

- Users can only read/write their own data (`auth.uid() = user_id`)
- Admin role bypasses RLS for dashboard queries
- Service role used only by backend (never exposed to client)
- Public tables (menus, services) use `SELECT` only for anon role

## Anti-Patterns

- Never disable RLS "temporarily" — create proper policies instead
- Never use service role key in client-side code
- Never run destructive migrations without backup verification
- Never skip the staging test for schema changes
