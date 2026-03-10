# GitHub Copilot Pro Setup Guide

This guide explains how to use GitHub Copilot Pro ($19/mo) with OpenClaw and other repos.

## What is GitHub Copilot Pro?

GitHub Copilot Pro is a subscription plan for GitHub Copilot that adds:
- **Inline code completions** in your editor (all repos)
- **Agent Mode** — ask Copilot to create full PRs from GitHub issues
- **Actions integration** — use Copilot in GitHub Actions workflows
- **@workspace context** — ask Copilot about your entire codebase

**Cost:** $19/month

**Where to buy:** https://github.com/copilot

---

## Prerequisites

1. **GitHub account** with push access to the repos
2. **Copilot Pro subscription** ($19/mo) — must be activated at https://github.com/copilot
3. **Editor:** VS Code, Cursor, JetBrains IDE, Vim, or Neovim
4. **Copilot extension installed** in your editor

---

## Step 1: Activate Copilot Pro on GitHub

1. Go to https://github.com/copilot
2. Click "Subscribe to Copilot Pro" ($19/month)
3. Add payment method (credit card)
4. Confirm subscription

Your GitHub account now has Copilot Pro enabled.

---

## Step 2: Install Copilot Extension in Your Editor

### VS Code
1. Open VS Code Extensions (Ctrl+Shift+X / Cmd+Shift+X)
2. Search for "GitHub Copilot"
3. Install the official "GitHub Copilot" extension (GitHub)
4. Sign in when prompted (uses GitHub OAuth)
5. Restart VS Code

### Cursor
Cursor has Copilot built-in. Just configure:
1. Settings → "Copilot" → Enable "Copilot (Pro)"
2. Sign in with GitHub account

### JetBrains IDE (IntelliJ, PyCharm, WebStorm, etc.)
1. Go to Settings → Plugins
2. Search for "GitHub Copilot"
3. Install official plugin
4. Sign in with GitHub

### Vim/Neovim
Use `github/copilot.vim` plugin:
```bash
git clone https://github.com/github/copilot.vim.git ~/.vim/pack/github/start/copilot.vim
```
Then run `:Copilot setup` in Vim.

---

## Step 3: Configure Copilot Context (`.github/copilot-instructions.md`)

Each repo now has a `.github/copilot-instructions.md` file that tells Copilot:
- What the project is about
- Key conventions and patterns
- What NOT to do
- Where to find important files

**These instructions are automatically picked up by Copilot** when you work on the repo.

### OpenClaw instructions file
- **Location:** `./.github/copilot-instructions.md`
- Covers: multi-agent job pipeline, 81 MCP tools, Python conventions, phase-gated tools, LLM fallback chain
- Tells Copilot about the agent allowlists, job pipeline flow, and key gotchas

### Other repos
- Barber CRM: Next.js + Supabase + Stripe setup
- Delhi Palace: Next.js + Sanity CMS pattern
- PrestressCalc: Python + sympy engineering calcs with 1597+ tests

---

## Step 4: Use Copilot

### Inline Completions (In Your Editor)

Start typing code. Copilot will suggest completions (gray text).

Example:
```python
# You type:
def process_job(job: Job) ->

# Copilot suggests:
def process_job(job: Job) -> JobResult:
    """Process a single job through the pipeline.

    Args:
        job: The job to process

    Returns:
        JobResult with outcomes
    """
    # [rest of function skeleton]
```

- **Accept:** Tab or Cmd+Right Arrow
- **Reject:** Esc
- **Cycle suggestions:** Alt+] / Alt+[

### Chat with Copilot (In Your Editor)

Press **Ctrl+Shift+I** (or Cmd+Shift+I on Mac) to open Copilot Chat.

Examples:
```
"Explain the job pipeline flow"
"How do phase-gated tools work?"
"Create a new agent tool with tests"
"What's the difference between CEO and PA worker?"
```

### @workspace Context

In Copilot Chat, use `@workspace` to make Copilot aware of your entire codebase.

Example:
```
@workspace what are all the agent tools available?
@workspace show me how errors are handled in the job pipeline
@workspace refactor this function to match the existing patterns
```

This makes Copilot search your entire repo for relevant code.

---

## Step 5: Agent Mode (Create PRs from Issues)

Agent Mode lets Copilot create full pull requests from GitHub issues.

### Enable in VS Code:
1. Open Command Palette (Ctrl+Shift+P / Cmd+Shift+P)
2. Search "GitHub Copilot: Open Agent in GitHub"
3. Click "Open Agent"

Or go directly to: https://github.com/copilot

### Create a PR with Agent Mode:
1. Go to the GitHub issue you want to work on
2. Click "Ask Copilot" (Copilot Agent button at top of issue)
3. Copilot reviews the issue and creates a PR with code changes
4. Review the PR, request changes if needed
5. Merge when ready

**Example workflow:**
- Create GitHub issue: "Add new Notion API tool to agent_tools.py"
- Click "Ask Copilot" in issue
- Copilot:
  - Reads the issue description
  - Reads `.github/copilot-instructions.md`
  - Creates a PR with: new tool code + tests + docstring
- You review, request changes, merge

---

## Step 6: GitHub Actions Integration (Optional)

You can use Copilot in GitHub Actions via API. This is advanced and optional.

For example, to auto-fix code style issues:
1. Add GitHub Actions with Copilot API
2. On each PR, run linter → Copilot fixes issues → push fix commit

See [GitHub Actions docs](https://docs.github.com/en/copilot/github-copilot-in-the-cli/using-github-copilot-in-the-cli) for details.

---

## Repo-Specific Tips

### OpenClaw
- Ask `@workspace what are the phase-gated tools?`
- Use Agent Mode to create new MCP tools (scaffold + tests)
- Copilot will reference the job pipeline phases when suggesting code

### Barber CRM
- Ask `@workspace how do we handle Stripe webhooks?`
- Use for scaffolding new API routes and Supabase queries
- Copilot knows the Next.js + Supabase patterns

### Delhi Palace
- Ask `@workspace how are GROQ queries used?`
- Use for adding new content types to Sanity schema
- Copilot references the Portable Text patterns

### PrestressCalc
- Ask `@workspace what tests exist for beam calculations?`
- Use for adding new AASHTO design checks
- Copilot will suggest test fixtures and parameter shapes

---

## Keyboard Shortcuts

| Action | Shortcut |
|--------|----------|
| Accept inline suggestion | Tab |
| Reject suggestion | Esc |
| Cycle suggestions | Alt+] / Alt+[ |
| Open Copilot Chat | Ctrl+Shift+I |
| Open Copilot Agent (PR creation) | GitHub web interface |
| Quick fix (VS Code) | Ctrl+. |
| Command Palette | Ctrl+Shift+P |

---

## Best Practices

1. **Provide context:** Use `@workspace` and mention specific files/functions
2. **Be specific:** "Add error handling to `process_job()` following the pattern in `verify_job()`"
3. **Review carefully:** Copilot is fast but not always correct; always review PRs before merging
4. **Use for scaffolding:** Copilot is best at boilerplate, not novel logic
5. **Test generated code:** Always run tests on Copilot-generated code
6. **Reference instructions:** Copilot reads `.github/copilot-instructions.md`; update it when patterns change

---

## Troubleshooting

### Copilot not showing suggestions
- Check: is Copilot Pro subscription active? Go to https://github.com/settings/copilot
- Restart editor
- Check extension is installed: Ctrl+Shift+X → search "GitHub Copilot"

### Suggestions don't match our patterns
- Make sure `.github/copilot-instructions.md` is up to date
- Ask Copilot to "follow the pattern in [specific file]"
- Use @workspace context to ground Copilot in the codebase

### Agent Mode not creating PRs
- Make sure you're on a public repo (private repos may have limitations)
- Check that the issue is clear and specific
- Try rephrasing the issue description

### Want to disable Copilot for a specific file
In VS Code:
- Settings → Copilot → Disabled Files
- Add pattern: e.g., `**/node_modules/**`

---

## Free Alternative: GitHub Copilot Free

If you don't want to pay for Pro:
- GitHub Copilot Free provides inline completions in public repos only
- No Agent Mode, no @workspace context
- Still very useful for learning and scaffolding

For Miles (active contributor): Pro is recommended for the full Agent Mode experience.

---

## Next Steps

1. **Activate Copilot Pro** at https://github.com/copilot
2. **Install extension** in your editor
3. **Read `.github/copilot-instructions.md`** for your repo (it's automatically used)
4. **Try Agent Mode:** Pick an issue, click "Ask Copilot", review the PR
5. **Use @workspace context** in chat for codebase-aware questions

---

## Links

- **GitHub Copilot Home:** https://github.com/copilot
- **Copilot Pro Plans:** https://github.com/features/copilot/plans
- **Copilot Documentation:** https://docs.github.com/en/copilot
- **Copilot in GitHub:** https://docs.github.com/en/copilot/github-copilot-in-github
- **Copilot in Your IDE:** https://docs.github.com/en/copilot/copilot-in-your-ide

---

## FAQ

**Q: Does Copilot send my code to GitHub?**
A: Your code is sent to GitHub servers for processing, but it's not used to train models (unless you opt in).

**Q: Can I use Copilot for commercial projects?**
A: Yes, Copilot Pro includes commercial use rights.

**Q: Will Copilot steal code from open source?**
A: Copilot can suggest code similar to open source. Always review and check licenses.

**Q: Can I use Copilot in GitHub Actions?**
A: Yes, via the Copilot API. See advanced setup docs.

**Q: What if I don't want Copilot to suggest certain patterns?**
A: Add them to `.github/copilot-instructions.md` under "Don'ts" section.

---

## Support

- GitHub Copilot Issues: https://github.com/github/copilot-docs/issues
- GitHub Community: https://github.com/orgs/community/discussions/categories/copilot
- Contact GitHub Support: https://support.github.com
