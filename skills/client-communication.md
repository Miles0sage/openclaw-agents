---
description: How to communicate with clients — tone, channel, timing, and escalation
agent: overseer
tags: [communication, client, tone, reporting]
priority: medium
---

# Client Communication

Clients judge quality by communication as much as by output. Get this right.

## Tone Rules

- Concise and professional — no fluff, no filler words
- Lead with the answer, then provide context
- Use bullet points for status updates, not paragraphs
- Never use jargon the client does not know
- Match the client's energy — if they are brief, be brief

## Channel Selection

- Urgent / time-sensitive → [[telegram-integration]] (fastest response)
- Detailed updates, reports → [[slack-integration]] (threaded, searchable)
- Formal deliverables → email (via [[overseer-coordination]])
- Code reviews, PRs → [[github-tools]] (keeps context with code)

## Status Updates

Send proactively, do not wait to be asked:

- Task started: "Working on X, ETA Y"
- Task blocked: "Blocked on X, need Y from you"
- Task complete: "Done. Here is the result: [link]. Let me know if changes needed."
- Task failed: "X failed because Y. Recovery plan: Z. ETA: W."

## Escalation to Human

When [[auto-approve-rules]] requires human input:

1. State what needs approval clearly
2. Provide options with pros/cons
3. Include a recommended option
4. Set a response deadline
5. If no response in 2 hours, send reminder
6. If no response in 4 hours, proceed with lowest-risk option

## Anti-Patterns

- Never surprise a client with a production issue after the fact
- Never send an update that requires them to ask follow-up questions for basic info
- Never use Opus for formatting status messages — use templates from [[memory-system]]
- Never communicate security findings to clients before [[pentest-security]] validates them
