---
description: GitHub repo management — issues, PRs, branches, and CI/CD integration
agent: codegen
tags: [tools, github, git, cicd, prs]
priority: medium
---

# GitHub Tools

All code lives on GitHub. Use `gh` CLI for automation, never the web UI for repetitive tasks.

## Repositories

- [[barber-crm]]: github.com/Miles0sage/Barber-CRM
- [[delhi-palace]]: github.com/Miles0sage/Delhi-Palce-
- [[openclaw-platform]]: github.com/cline/openclaw + github.com/Miles0sage/openclaw-assistant
- [[prestress-calc]]: github.com/Miles0sage/Mathcad-Scripts
- [[concrete-canoe]]: github.com/Miles0sage/concrete-canoe-project2026

## Branch Strategy

- `main` is production — never push directly without passing tests
- Feature branches: `feat/description`, `fix/description`, `security/description`
- PRs require passing CI before merge
- Delete branches after merge (keep main clean)

## Common Operations

```bash
# Create PR
gh pr create --title "feat: description" --body "summary"

# Check CI status
gh pr checks <pr-number>

# Create issue
gh issue create --title "Bug: description" --body "details"

# Close issue with PR
gh pr create --title "fix: issue" --body "Closes #123"
```

## CI/CD Integration

- Push to main triggers auto-deploy on Vercel ([[barber-crm]], [[delhi-palace]])
- Push to main triggers Northflank rebuild ([[openclaw-platform]])
- PRs run test suites automatically
- Failed CI blocks merge per [[auto-approve-rules]]

## Secrets Management

- Never commit `.env` files, API keys, or tokens
- Use platform-specific secret stores (Vercel env vars, Wrangler secrets, Northflank env)
- If a secret is accidentally committed → rotate immediately, notify [[pentest-security]]
- Check git history: `git log --all --full-history -- "*.env"`

## Cost

GitHub is free for all repos (public or private with free tier).
No [[budget-enforcement]] concern.
