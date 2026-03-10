---
description: Telegram bot commands, webhook handling, and mobile-first agent access
agent: any
tags: [tools, telegram, bot, mobile, webhooks]
priority: medium
---

# Telegram Integration

Mobile-first interface for quick commands and notifications. Active and working.

## Current Setup

- Bot framework: Grammy (TypeScript)
- Source: `src/telegram/` (66 files) in [[openclaw-platform]]
- HTTP gateway bridge: `src/telegram/http-gateway.ts`
- Session keys: `telegram:{userId}:{chatId}` for [[memory-system]]
- Env vars: `OPENCLAW_HTTP_GATEWAY_URL`, `OPENCLAW_HTTP_GATEWAY_TOKEN`

## Message Flow

1. User sends message to Telegram bot
2. Grammy receives via webhook
3. `http-gateway.ts` forwards to FastAPI gateway
4. Gateway routes to agent via [[cost-routing]]
5. Agent response returns through gateway → Grammy → Telegram

## Use Cases

- Quick status checks (mobile, on the go)
- Approval responses for [[auto-approve-rules]] requests
- Bug reports forwarded to [[bug-fix-workflow]]
- Deploy triggers (with human confirmation)

## Commands

- `/status` — system health from [[openclaw-platform]]
- `/costs` — budget summary from [[budget-enforcement]]
- `/deploy <project>` — trigger [[deployment-workflow]] (requires approval)
- `/audit <project>` — trigger [[security-audit-workflow]]

## Fallback Behavior

If HTTP gateway is unavailable:

1. Grammy falls back to local dispatch (built-in)
2. Reduced functionality (no agent routing)
3. Alert sent via [[slack-integration]] about gateway down
4. Follow [[error-recovery]] for gateway restoration

## Anti-Patterns

- Do not send long code blocks via Telegram (use [[github-tools]] PR link instead)
- Do not rely on Telegram for critical approvals (network can be flaky)
- Always have [[slack-integration]] as backup channel
