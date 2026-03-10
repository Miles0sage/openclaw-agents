---
description: How agent memories are stored, recalled, and used for context across sessions
agent: any
tags: [tools, memory, sessions, context, persistence]
priority: high
---

# Memory System

Agents forget everything between requests unless you explicitly persist context. This file explains how.

## Session Storage

- Location: `/tmp/openclaw_sessions/{sessionKey}.json`
- Format: JSON array of message objects `[{role, content, timestamp}]`
- Keys: `{channel}:{userId}:{chatId}` (e.g., `telegram:U123:C456`)
- Loaded on gateway startup — survives restarts
- Saved after every message exchange

## Cost Tracking

- Location: `/tmp/openclaw_costs.jsonl`
- Format: JSON Lines, one entry per API call
- Fields: timestamp, agent, model, input_tokens, output_tokens, cost_usd
- Used by [[budget-enforcement]] for real-time spend tracking
- Queried by [[overseer-coordination]] for reporting

## What to Remember

- User preferences (communication style, project priorities)
- Previous decisions and their outcomes (avoids repeating mistakes)
- Error patterns (if the same error recurs, recall the fix)
- Project status (what phase each project is in)
- Approval history (what was approved/rejected and why)

## What NOT to Remember

- API keys, tokens, passwords (use env vars, not memory)
- Full code files (use [[github-tools]] references instead)
- Raw API responses (summarize, then discard)
- Temporary debug output

## Memory in Workflows

- [[bug-fix-workflow]]: check if bug was seen before, recall previous fix
- [[deployment-workflow]]: recall last deploy status and any issues
- [[security-audit-workflow]]: recall previous audit findings for delta comparison
- [[overseer-coordination]]: recall user preferences for delegation decisions

## Cleanup

- Sessions older than 30 days: archive to disk, remove from active memory
- Cost logs: rotate monthly, keep summaries
- Error logs: keep last 100, summarize patterns

## Future: Graphiti MCP

Plan to upgrade to knowledge-graph-based memory (FalkorDB) for temporally-aware context. Currently using flat file storage which works but does not support relationship queries.
