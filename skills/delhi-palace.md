---
description: Delhi Palace restaurant website — ordering, KDS dashboard, Supabase real-time
agent: any
tags: [project, restaurant, nextjs, supabase, vercel]
priority: medium
---

# Delhi Palace

Restaurant website with online ordering and kitchen display system.

## Stack

- Next.js 16, React 19, Tailwind v4, Framer Motion
- Supabase — orders table, real-time subscriptions
- Stripe — payment processing
- Vercel — auto-deploy on push
- Colors: Red #8B0000, Gold #D4AF37, Cream #FFF8F0, Font: Outfit

## Live URLs

- App: https://delhi-palace.vercel.app
- Repo: github.com/Miles0sage/Delhi-Palce-
- Local: /root/Delhi-Palace/
- Dashboard: /dashboard (PIN 1234)

## Key Decisions

- [[codegen-development]] handles feature work and styling
- [[supabase-data]] manages orders table and real-time subs
- Deploy via Vercel auto-deploy — push to main triggers deploy
- SEO and performance work is Phase 3 (current)

## Sensitive Areas

- Dashboard PIN (1234) — same hardening needed as [[barber-crm]]
- Supabase service role key — Vercel env only
- Stripe keys — test mode, stored in Vercel env vars
- Admin email: admin@delhipalace.com

## Current Status

Phase 2 complete. Phase 3 executing (SEO + final polish).
Landing page, KDS redesign, menu badges, scroll animations all shipped.

## Cost

- All free tier (Vercel + Supabase)
- No ongoing cost — no [[budget-enforcement]] concern
