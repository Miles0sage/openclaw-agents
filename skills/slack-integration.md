---
description: Slack notifications, slash commands, and agent communication channel
agent: any
tags: [tools, slack, notifications, communication]
priority: medium
---

# Slack Integration

Primary communication channel for agent-to-human and agent-to-agent messaging.

## Capabilities

- Send notifications (deploy status, error alerts, task completion)
- Receive commands (slash commands for triggering workflows)
- Thread-based conversations (context preserved per thread)
- Approval requests from [[auto-approve-rules]]

## Message Routing

- `#deployments` — all deploy notifications from [[deployment-workflow]]
- `#security-alerts` — critical findings from [[pentest-security]]
- `#agent-status` — heartbeat and health from [[openclaw-platform]]
- `#general` — task updates, progress reports from [[overseer-coordination]]
- DM — approval requests, budget alerts from [[budget-enforcement]]

## Integration with Agents

- [[overseer-coordination]] posts task decomposition and progress
- [[codegen-development]] posts PR links and test results
- [[pentest-security]] posts audit findings and alerts
- [[supabase-data]] posts migration status

## Webhook Setup

- Slack webhook active on [[openclaw-platform]]
- Incoming webhooks for notifications
- Outgoing webhooks for slash commands → gateway → agent routing
- Session keys: `slack:{userId}:{channelId}` for [[memory-system]]

## Message Format

Keep messages concise and actionable:

- Status: one-line summary + link to details
- Alerts: severity + description + recommended action
- Approvals: what needs approval + options (approve/reject) + timeout

## Anti-Patterns

- Do not spam channels — batch non-urgent updates
- Do not send sensitive data (keys, passwords) in messages
- Do not use Slack for large data transfers — use [[github-tools]] links instead
