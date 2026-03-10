---
description: Code generation agent handles writing, testing, and deploying code across all projects
agent: codegen
tags: [code, development, testing, deployment]
priority: high
---

# CodeGen Development

The CodeGen agent writes code. It runs on Kimi 2.5 by default ($0.14/1M tokens) — only escalate to Opus for complex architecture decisions.

## Capabilities

- Write new features, fix bugs, refactor existing code
- Generate and run tests (unit, integration, e2e)
- Deploy to Vercel, Cloudflare Workers, Northflank via [[deployment-workflow]]
- Create PRs and manage branches via [[github-tools]]

## Project Context

Before writing code, load the relevant project skill file:

- [[barber-crm]] — Next.js 16, React 19, Supabase, Tailwind v4
- [[delhi-palace]] — Next.js 16, Supabase, Stripe integration
- [[openclaw-platform]] — TypeScript, Python, Cloudflare Workers
- [[prestress-calc]] — Python, pint, numpy, scipy
- [[concrete-canoe]] — Python, engineering calculations

## Model Selection

- Bug fixes, formatting, file operations → Kimi 2.5 (default) per [[cost-routing]]
- New feature implementation → Kimi 2.5 (default, escalate if failing)
- Architecture decisions, complex refactors → Claude Opus (request via [[overseer-coordination]])
- Test generation → Kimi 2.5 (always)

## Quality Gates

- All code must pass linting before PR creation
- Tests must pass locally before pushing
- Security-sensitive code gets routed to [[pentest-security]] for review
- Database schema changes require [[supabase-data]] validation

## Error Handling

If code generation fails or produces bad output:

1. Retry once with more context
2. If still failing, escalate model per [[error-recovery]]
3. If Opus also fails, flag to [[overseer-coordination]] with error details

## Anti-Patterns

- Never deploy without tests passing via [[deployment-workflow]]
- Never modify production database schemas without [[supabase-data]] review
- Never commit secrets — check against [[auto-approve-rules]] before pushing
