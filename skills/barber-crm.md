---
description: Barber CRM project — Next.js booking system with AI receptionist and Stripe payments
agent: any
tags: [project, barber, crm, nextjs, supabase]
priority: medium
---

# Barber CRM

Live client project. Handle with care — real users, real payments.

## Stack

- Next.js 16, React 19, Tailwind v4, Framer Motion
- Supabase (`banxtacevgopeczuzycz.supabase.co`) — bookings, clients, services
- Stripe (test mode) — payment processing
- Vapi AI Receptionist — phone +1 (928) 325-9472
- Vercel — auto-deploy on push

## Live URLs

- App: https://nextjs-app-sandy-eight.vercel.app
- Repo: github.com/Miles0sage/Barber-CRM
- Local: /root/Barber-CRM/

## Key Decisions

- [[codegen-development]] handles all feature work
- [[supabase-data]] validates any schema changes to bookings/orders tables
- [[pentest-security]] reviews Stripe webhook handlers and NextAuth config
- Deploy via Vercel auto-deploy — no manual [[deployment-workflow]] needed

## Sensitive Areas

- Stripe webhook signature validation — never bypass
- NextAuth session tokens — rotate if compromised
- Vapi API keys — stored in Vercel env vars, never in code
- Admin dashboard PIN (1234) — needs hardening per [[pentest-security]]

## Current Status

Phase 3 complete. AI Receptionist live. PRs #17-#21 merged.
Next work: Phase 4 improvements, PIN hardening, booking flow optimization.

## Cost

- Vapi: ~$5/month (low call volume)
- Supabase: Free tier
- Vercel: Free tier
- Total: ~$5/month — no [[budget-enforcement]] concern
