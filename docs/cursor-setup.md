# Cursor Pro IDE Setup for OpenClaw & Portfolio Projects

**Date**: 2026-03-07 | **Cursor Version**: Latest Pro ($20/mo)

This guide walks through setting up Cursor Pro IDE for working on OpenClaw and portfolio projects, both locally and remotely via SSH.

---

## What is Cursor Pro?

Cursor Pro is an AI-native code editor based on VS Code that provides:
- **AI Composer**: Write entire files or features with Claude's help
- **Code Understanding**: Codebase-aware autocomplete and navigation
- **Background Agents**: Autonomous code actions and refactoring
- **Tab Autocomplete**: Next-token prediction (GitHub Copilot-like)
- **Cost**: $20/month (unlimited API calls with own Claude API key, or Cursor-hosted)

Cursor reads `.cursorrules` files in the project root to understand coding standards, project context, and how to help effectively.

---

## Quick Setup (5 minutes)

### 1. Install Cursor
- Download from https://cursor.com
- Available for macOS, Windows, Linux
- Install like VS Code

### 2. Setup for OpenClaw (Remote SSH)

**Option A: Remote SSH (Recommended)**
```bash
# On Miles' Windows PC, open Cursor
# Ctrl+Shift+P → "Remote: Open Folder in SSH"
# SSH Target: root@<your-vps-ip>
# Folder: ./

# First time will ask for password, then connects
# Cursor downloads VS Code Server on remote automatically
```

**Option B: Local Clone**
```bash
# Clone locally on Windows
git clone https://github.com/Miles0sage/openclaw.git
# Open with Cursor (File → Open Folder → select openclaw/)
# Cursor will read .cursorrules automatically
```

### 3. Verify Setup
- Open `./` in Cursor
- Should see notification: "Using .cursorrules file"
- Try Cmd+K (Mac) or Ctrl+K (Windows) to open Composer
- Composer prompt should show project context loaded

---

## Directory Structure

Cursor is set up for all four major projects:

| Project | Path | Type | .cursorrules |
|---------|------|------|-------------|
| OpenClaw | `./` | Python/FastAPI | ✅ Created |
| Barber CRM | `/root/Barber-CRM/` | Next.js/React | ✅ Created |
| Delhi Palace | `/root/Delhi-Palace/` | Next.js/React | ✅ Created |
| PrestressCalc | `/root/Mathcad-Scripts/` | Python/Streamlit | ✅ Created |

Each project root contains `.cursorrules`, `.cursorignore`, and `.vscode/settings.json`.

---

## Using Cursor Composer (The Magic Part)

Cursor Composer lets you write code with AI guidance. It reads your `.cursorrules` to stay aligned with project conventions.

### Basic Workflow

```
1. Open Cursor Composer: Cmd+K (Mac) or Ctrl+K (Windows)
2. Describe what you want: "Add a new API endpoint for user signup"
3. Composer generates code, respecting .cursorrules
4. Review changes, accept/edit, commit
```

### Examples

**Example 1: OpenClaw — Add a new agent tool**
```
Composer Prompt:
"Add a new MCP tool to agent_tools.py that fetches current stock prices.
Tool name: fetch_stock_price
Parameters: symbol (str), currency (str, default 'USD')
Returns: price (float), timestamp (datetime)
Add to all agent tool allowlists that need it.
Follow CLAUDE.md routing rules."

Composer will:
- Read agent_tools.py to understand tool structure
- Read agent_tool_profiles.py to add to allowlists
- Generate code matching OpenClaw conventions (type hints, async, error handling)
- Respect agent routing (which agents get which tools)
```

**Example 2: Barber CRM — Fix booking form validation**
```
Composer Prompt:
"The booking form isn't validating phone numbers correctly.
Fix the validation in src/components/booking/BookingForm.tsx.
Phone must be 10 digits, (123) 456-7890 format accepted.
Show error message if invalid."

Composer will:
- Read BookingForm.tsx to understand current logic
- Check tsconfig.json for TypeScript settings
- Generate fix following Next.js/React patterns from .cursorrules
- Include proper error handling and type safety
```

**Example 3: PrestressCalc — Add new test case**
```
Composer Prompt:
"Add 5 edge case tests for calculate_initial_loss in test_losses.py.
Test: zero input, very large input, negative values, boundary conditions.
Compare against Eriksson reference values (±0.1 MPa tolerance)."

Composer will:
- Read existing tests to match style
- Use pytest conventions from .cursorrules
- Generate tests with proper assertions and error messages
```

### Composer Tips
- **Be specific**: "Fix the bug" is vague. "Phone validation fails when format is (123) 456-7890" is clear.
- **Reference files**: "In src/components/booking/BookingForm.tsx, the phone validation..."
- **Reference context**: Mention .cursorrules if you want specific patterns: "Following OpenClaw async/await patterns..."
- **Accept incrementally**: Don't accept huge diffs at once. Review, accept file-by-file.
- **Cursor remembers**: If you say "no, use Pydantic v2 syntax", it learns for next request.

---

## Remote SSH Setup (Detailed)

If connecting to VPS via SSH:

### Prerequisites
- SSH key configured (should already be in `/root/.ssh/id_rsa`)
- Can SSH manually: `ssh root@<your-vps-ip>`

### Cursor Remote SSH Steps

1. **Open Cursor**
2. **Ctrl+Shift+P** (or Cmd+Shift+P on Mac) → "Remote: Open Folder in SSH"
3. **Enter SSH target**: `root@<your-vps-ip>`
4. **Select folder**: `./` (or other project)
5. **First time**: Cursor downloads VS Code Server (~100MB), takes 30 seconds
6. **Connected**: Now editing files on VPS directly

### Performance Notes
- **Latency**: Network latency may feel slightly sluggish (typical for SSH)
- **Caching**: Cursor caches file tree locally, should feel responsive after first load
- **Large files**: gateway.py (228KB) and autonomous_runner.py (4739 lines) may take a moment to open first time
- **Bandwidth**: Minimal after initial sync; code edits stream efficiently

### Alternative: Local Clone (Faster)

If SSH feels slow, clone locally:
```bash
# On Windows PC
git clone https://github.com/Miles0sage/openclaw.git C:\dev\openclaw
# Open C:\dev\openclaw in Cursor
# Work locally, push with git
```

Trade-off: Local is faster, but must push changes to deploy.

---

## VS Code Settings for Cursor

Cursor uses VS Code settings. Each project has `.vscode/settings.json`:

### OpenClaw Settings
```json
{
  "python.defaultInterpreterPath": "/usr/bin/python3",
  "python.linting.ruffEnabled": true,
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["tests", "-v"],
  "editor.formatOnSave": true,
  "editor.defaultFormatter": "ms-python.black-formatter"
}
```

**What this does**:
- Uses Python 3.13 interpreter
- Enables Ruff linter (fast, strict)
- Enables pytest (recognizes `tests/` folder)
- Auto-formats on save with Black
- Ruler at 88 chars (Black standard) and 120 (soft limit)

### Barber CRM Settings
```json
{
  "typescript.tsdk": "node_modules/typescript/lib",
  "[typescript]": {
    "editor.defaultFormatter": "esbenp.prettier-vscode",
    "editor.formatOnSave": true
  },
  "editor.codeActionsOnSave": {
    "source.fixAll.eslint": true
  }
}
```

**What this does**:
- Uses local TypeScript version
- Auto-formats TypeScript with Prettier
- Auto-fixes ESLint issues on save
- Strict mode enabled (tsconfig.json)

---

## Recommended Cursor Extensions

Install these in Cursor for better experience:

### For OpenClaw (Python)
- `ms-python.python` — Python language server
- `ms-python.vscode-pylance` — Type checking
- `ms-python.black-formatter` — Code formatting
- `charliermarsh.ruff` — Linting (faster than pylint)
- `ms-python.pytest` — Pytest integration
- `ms-vscode.remote-ssh` — SSH support (for remote VPS)

### For Barber CRM / Delhi Palace (Next.js/TypeScript)
- `dbaeumer.vscode-eslint` — ESLint integration
- `esbenp.prettier-vscode` — Code formatting
- `bradlc.vscode-tailwindcss` — Tailwind CSS autocomplete
- `unifiedjs.vscode-mdx` — Markdown support
- `GitHub.copilot` — Tab autocomplete (optional, uses own credits)

### For All Projects
- `ms-vscode.remote-ssh` — Remote SSH (if using SSH)
- `GitHub.github-copilot-chat` — Copilot chat (optional, separate from Cursor)
- `ms-vscode.makefile-tools` — Makefile support

**Install**: Cursor > Extensions (Ctrl+Shift+X) > search > Install

---

## Working with .cursorrules

### How Cursor Uses .cursorrules

When you open a project folder, Cursor:
1. Looks for `.cursorrules` in the root
2. Reads the file (plain text, markdown-style)
3. Passes it to Claude when you use Composer
4. Claude follows the guidelines when generating code

### Editing .cursorrules

If you want to add conventions:
1. Edit `./.cursorrules` (or project root)
2. Add your guideline under relevant section
3. Cursor auto-reloads (no restart needed)
4. Next Composer request uses updated rules

### Example: Adding a New Convention

**Current .cursorrules**:
```
## Coding Conventions
- **Language**: Python 3.13
- **Framework**: FastAPI (async/await everywhere)
```

**You want to add**:
```
## Coding Conventions
- **Language**: Python 3.13
- **Framework**: FastAPI (async/await everywhere)
- **Logging**: Always use structured JSON logs via logger from routers/shared.py
```

Just edit the file, save, and next Composer request will follow this rule.

---

## Workflow Examples

### Scenario 1: Fix a Bug in OpenClaw

```
1. Open OpenClaw in Cursor (local or SSH)
2. Ctrl+K → Composer
3. Paste error message:
   "TypeError: 'NoneType' object has no attribute 'route' in gateway.py line 245"
4. Composer finds the bug, reads related code, proposes fix
5. Review diff, accept
6. Run `python3 -m pytest tests/test_gateway.py -v` to verify
7. Git commit and push
```

### Scenario 2: Add Feature to Barber CRM

```
1. Open Barber-CRM in Cursor (local preferred for speed)
2. Ctrl+K → Composer
3. "Add SMS notification when appointment is confirmed.
   Use Twilio API. Store SMS config in .env.local"
4. Composer generates:
   - lib/twilio.ts (Twilio client setup)
   - api/appointments/route.ts (add SMS send logic)
   - Updates to .env.example
5. Review code (type safety, error handling)
6. Accept changes
7. npm run build to verify TypeScript compiles
8. Commit and push (auto-deploys to Vercel)
```

### Scenario 3: Write Tests for PrestressCalc

```
1. Open Mathcad-Scripts in Cursor
2. Ctrl+K → Composer
3. "Write 10 test cases for calculate_initial_loss in test_losses.py.
   Test normal case, edge cases, invalid inputs.
   Validate against Eriksson reference values within ±0.1 MPa."
4. Composer generates test_losses.py additions with proper pytest style
5. Run: python3 -m pytest tests/test_losses.py -v
6. All tests pass
7. Commit to git
```

---

## Common Issues & Fixes

### Issue: "Cannot find module" error in Composer

**Cause**: Cursor's Python path not set correctly.

**Fix**:
1. Settings (Ctrl+,)
2. Search: "python.defaultInterpreterPath"
3. Set to `/usr/bin/python3` (VPS) or local Python path
4. Reload window (Ctrl+Shift+P → Reload Window)

### Issue: Composer seems slow / unresponsive

**Cause**: Large files (gateway.py 228KB) or network latency (SSH).

**Fix**:
- **Local mode**: Clone repo locally, work faster
- **SSH**: Check network connection (`ssh root@<your-vps-ip>` manually)
- **Large files**: Composer works best on <10K line files; split if possible

### Issue: .cursorrules not being read

**Cause**: File not in root of open folder.

**Fix**:
1. Verify `.cursorrules` is in `./` (not in subdirectory)
2. Ctrl+Shift+P → "Reload Window"
3. Ctrl+K → Composer should now show "Using .cursorrules" notice

### Issue: TypeScript errors in Barber CRM

**Cause**: `tsconfig.json` has strict mode enabled.

**Fix**: This is intentional (strict mode catches bugs). Either:
1. Fix the TypeScript error (recommended)
2. Ask Composer: "Fix TypeScript strict mode error in X file"

### Issue: Git authentication on VPS (SSH)

**Cause**: SSH key not configured for git pushes.

**Fix**:
1. SSH to VPS: `ssh root@<your-vps-ip>`
2. Check key: `ls ~/.ssh/id_rsa`
3. If missing: `ssh-keygen -t rsa -b 4096` (generate key)
4. Add to GitHub: GitHub → Settings → SSH Keys → Add
5. Test: `git clone git@github.com:Miles0sage/openclaw.git` (should work)
6. In Cursor, git push now works

---

## Cursor Pro Features You'll Love

### 1. Codebase Chat
- Ctrl+Shift+L → Ask about entire codebase
- "What does this function do?" highlights context
- "Show me all places where X is called"
- Great for understanding large projects

### 2. Tab Autocomplete (Free)
- Cursor predicts next line of code
- Press Tab to accept
- Learns from .cursorrules and project patterns
- Feels like GitHub Copilot but better

### 3. Inline Editing (Free)
- Ctrl+K on selected code → Edit just that chunk
- "Make this function async"
- "Rename X to Y everywhere in this function"
- Keeps context of surrounding code

### 4. Background Agents (Pro Feature)
- Auto-refactor, auto-test, auto-document
- Less used in OpenClaw (manual control preferred)
- Configure via `.cursorrules` if desired

### 5. Privacy
- Can use own Claude API key (Anthropic's token)
- Or use Cursor-hosted (Claude Pro through Cursor)
- Code never leaves your machine for local edits
- Composer uploads code context only for the request

---

## Pro Tips for Maximum Efficiency

1. **Use specific prompts**: "Fix the booking form validation" is vague. "In src/components/booking/BookingForm.tsx, phone validation fails when format is (123) 456-7890. Fix by..." is precise.

2. **Reference .cursorrules in prompts**: "Following the OpenClaw async/await pattern, add a new tool that..."

3. **Test before commit**: Composer generates code, you test (pytest, npm run build), then commit. Don't skip testing.

4. **Batch related changes**: "Add user auth AND user preferences page" is better than two separate Composer requests.

5. **Use SSH for read-heavy, local for write-heavy**: SSH is fine for exploration, but faster to edit locally if making lots of changes.

6. **Keep .cursorrules updated**: As project evolves, update .cursorrules. Claude learns from it.

7. **Leverage Codebase Chat**: Before Composing, use Ctrl+Shift+L to understand the architecture. Ask "What's the flow from user input to database?" Then Composer knows context.

---

## Switching Between Projects in Cursor

Cursor handles multiple projects easily:

```
1. File → Open Folder
2. Select ./ (or any project)
3. Cursor loads .cursorrules for that project
4. Composer now aware of that project's conventions
5. To switch: File → Open Folder → different project
```

You can also use **Workspace** (File → Save Workspace) to open multiple projects side-by-side:
```
Workspace includes:
- ./
- /root/Barber-CRM/
- /root/Delhi-Palace/
- /root/Mathcad-Scripts/

Then Cursor has full context across all projects.
```

---

## Deploying Changes Made in Cursor

After making changes in Cursor:

### OpenClaw
```bash
git add .
git commit -m "feature: add new tool"
git push origin main
systemctl restart openclaw-gateway
journalctl -u openclaw-gateway -n 10  # Verify startup
```

### Barber CRM / Delhi Palace (Vercel)
```bash
git add .
git commit -m "fix: booking form validation"
git push origin main
# Auto-deploys to Vercel (watch dashboard.vercel.com)
```

### PrestressCalc
```bash
git add .
git commit -m "test: add edge case tests"
git push origin main
python3 -m pytest tests/ -v  # Run tests locally
```

---

## Summary

| Task | Tool | Time |
|------|------|------|
| Small fix (1-3 files) | Cursor Composer | 2 min |
| Feature addition | Cursor Composer + manual testing | 15 min |
| Codebase exploration | Cursor Codebase Chat | 5 min |
| Complex refactor | Composer + Code Review | 30 min |
| Emergency hotfix | Local clone + Cursor + test + push | 10 min |

Cursor Pro transforms the development workflow from "write code" to "describe intent, review, test, ship". With .cursorrules tuned to your projects, Claude in Composer understands your codebase deeply and generates code that fits seamlessly.

Happy coding!

---

**Questions?** Refer to:
- `.cursorrules` in each project root
- `CLAUDE.md` in each project (detailed project guides)
- https://cursor.com/docs (official Cursor docs)
