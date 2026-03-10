# OpenClaw Job Execution Lifecycle

This document describes how jobs are created, routed, executed, and completed in the OpenClaw pipeline.

## Job Anatomy

A job represents a single task routed through the OpenClaw pipeline. Each job has a unique identifier and tracks all metadata, progress, and costs throughout its lifecycle.

### Job Object Fields

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "project": "barber-crm",
  "task": "Fix login button alignment on mobile",
  "priority": "P2",
  "status": "running",
  "created_at": "2026-03-04T17:45:32Z",
  "updated_at": "2026-03-04T17:45:45Z",
  "cost_usd": 0.0044,
  "agent": "codegen_pro",
  "phase": "EXECUTE",
  "progress_pct": 55,
  "phases": {
    "RESEARCH": {
      "status": "completed",
      "duration_seconds": 8,
      "cost_usd": 0.0005
    },
    "PLAN": {
      "status": "completed",
      "duration_seconds": 12,
      "cost_usd": 0.0008
    },
    "EXECUTE": {
      "status": "running",
      "duration_seconds": 15,
      "cost_usd": 0.0028
    }
  }
}
```

### Job Priority Levels

| Priority | Auto-Approve | Max Duration | Cost Budget | Use Case                                            |
| -------- | ------------ | ------------ | ----------- | --------------------------------------------------- |
| P0       | No (manual)  | 30 min       | $0.50       | Critical bugs, security issues, production downtime |
| P1       | Yes          | 15 min       | $0.10       | High-priority features, breaking bugs               |
| P2       | Yes          | 10 min       | $0.05       | Standard features, minor bugs                       |
| P3       | Yes          | 5 min        | $0.02       | Polish, documentation, chores                       |

## Job Lifecycle

Jobs flow through a sequential lifecycle from creation to completion. State transitions are immutable—jobs cannot move backward.

### 1. Created (status: `pending`)

**Trigger:** Job enters the queue via API endpoint or Slack channel message

**What happens:**

- Job ID is generated (UUID v4)
- Metadata is validated (project, task, priority)
- Job is persisted to the job queue
- Event `job.created` is published to event stream
- Overseer workers begin picking up unassigned jobs

**Duration:** < 1 second

**Example flow:**

```
POST /api/jobs → Job entry in queue → Event published → Overseer polls
```

### 2. Analyzing (status: `analyzing`)

**Trigger:** Overseer worker claims job from queue

**What happens:**

- Overseer reads job task and scans project files
- Codebase complexity is assessed (lines of code, dependencies, language)
- Agent type is selected based on priority and complexity
  - **Simple tasks (P3):** codegen_lite (faster, cheaper)
  - **Standard tasks (P2):** codegen_pro (balanced)
  - **Complex tasks (P1-P0):** codegen_expert (slower, comprehensive)
- Preliminary cost estimate is calculated
- Execution plan is drafted
- Job transitions to `pr_ready`

**Duration:** 5-15 seconds

**Cost:** ~$0.0008 (Gemini 2.5 Flash analysis)

### 3. PR Ready (status: `pr_ready`)

**Trigger:** Overseer completes analysis

**What happens:**

- Execution plan is written to progress.json
- For P1-P3: Auto-approval is triggered immediately
- For P0: Awaits manual approval via dashboard
- Event `job.ready_for_approval` is published
- Job awaits transition to `approved`

**Duration:** 0 seconds (instant for P1-P3), manual for P0

**Approval flow:**

```
Human reviews job in dashboard → clicks "Approve" → status → approved
(or automatic for P1-P3 after 2 second delay)
```

### 4. Approved (status: `approved`)

**Trigger:** Job approval (automatic for P1-P3, manual for P0)

**What happens:**

- Job is marked ready for execution
- Execution worker picks up job from `approved` queue
- Pipeline initialization begins
- Job transitions to `running`

**Duration:** < 1 second

**Event:** `job.approved` is published

### 5. Running (status: `running`)

**Trigger:** Execution worker claims approved job

**What happens:**

- Pipeline executes through 5 phases sequentially
- Progress is updated in real-time (progress_pct, current_phase)
- Tools are invoked as needed
- Cost accumulates with each tool call
- Event `job.phase_started` fires for each phase
- Event `job.phase_completed` fires as each phase ends

**Duration:** 10 seconds to 30 minutes (depends on complexity)

**Monitoring:** WebSocket updates to job viewer UI in real-time

**Failure handling:**

- On tool error: Up to 2 retries with backoff
- On phase error: Attempt re-execution if recoverable
- On repeated failure: Job marked as `failed` with error log
- Kill switch: `POST /api/jobs/{job_id}/kill` stops execution

### 6. Completed/Failed (status: `completed` or `failed`)

**Trigger:** Final phase completes or irrecoverable error occurs

**What happens:**

- Final status is written to result.json
- Git changes are committed and pushed (if applicable)
- Results are reported to originating channel (Slack, API callback)
- All artifacts are archived in job run directory
- Cost is finalized and charged
- Event `job.completed` or `job.failed` is published
- Job transitions to terminal state (immutable)

**Duration:** < 5 seconds

**Result structure:**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "output": "Applied fix to src/auth/login.tsx and committed changes",
  "cost_usd": 0.0044,
  "duration_seconds": 35,
  "git_commit": "abc123def456",
  "artifacts": ["src/auth/login.tsx", "src/styles/mobile.css"]
}
```

## The 5-Phase Pipeline

All jobs executing successfully flow through exactly 5 phases. Each phase handles a specific concern in the job lifecycle.

### Phase 1: RESEARCH (0-20% progress)

**Objective:** Understand the codebase and context for the task

**Activities:**

- Read project README and configuration files
- Search for relevant code patterns matching the task
- Identify related files and dependencies
- Gather existing error messages or test failures
- Build mental model of the codebase structure

**Tools available:**

- `file_read` — Read individual files
- `glob_files` — Find files matching patterns
- `grep_search` — Search file contents with regex
- `git_operations` — View git history and diffs

**Success criteria:**

- Understand project structure
- Identify all relevant files
- Understand existing patterns
- Know where changes will be needed

**Duration:** 5-20 seconds

**Cost:** $0.0002-0.0008 (Gemini 2.5 Flash)

**Typical output:**

```
Research complete. Found 3 related auth files:
- src/auth/login.tsx (main component, 142 lines)
- src/auth/hooks/useAuth.ts (hook, 45 lines)
- src/styles/mobile.css (responsive styles, 89 lines)

Pattern: Mobile styles use @media (max-width: 768px)
Problem: Confirm button uses hardcoded width: 100px (too narrow on mobile)
Solution: Change to width: 100% within mobile query
```

### Phase 2: PLAN (20-40% progress)

**Objective:** Create detailed execution plan and estimate complexity

**Activities:**

- Break task into numbered executable steps
- Identify which files need changes
- Select tools required for execution
- Estimate cost and complexity
- Plan verification strategy
- Identify edge cases and risks

**Tools available:**

- Internal: ExecutionPlan object creation (no tool call)
- Analysis: Codebase understanding from Phase 1

**Success criteria:**

- Step-by-step plan is clear and complete
- All required changes are identified
- Verification plan is sound
- Cost estimate is reasonable

**Duration:** 5-15 seconds

**Cost:** $0.0003-0.0012 (Gemini 2.5 Flash)

**Typical ExecutionPlan output:**

```json
{
  "steps": [
    {
      "step": 1,
      "description": "Edit src/styles/mobile.css",
      "action": "Change button width from 100px to 100%",
      "tools": ["file_edit"],
      "risk": "low"
    },
    {
      "step": 2,
      "description": "Edit src/auth/login.tsx",
      "action": "Add responsive className to button",
      "tools": ["file_edit"],
      "risk": "low"
    },
    {
      "step": 3,
      "description": "Test on mobile viewport",
      "action": "Run visual tests",
      "tools": ["shell_execute"],
      "risk": "low"
    }
  ],
  "estimated_cost_usd": 0.015,
  "estimated_duration_seconds": 30,
  "complexity": "low"
}
```

### Phase 3: EXECUTE (40-70% progress)

**Objective:** Implement the solution according to the plan

**Primary Executor:** OpenCode with Gemini 2.5 Flash (~$0.001/job, fastest)

**Fallback chain (if OpenCode fails):**

1. **SDK Haiku** (~$0.02, more capable)
2. **SDK Sonnet** (~$0.50, most capable, P0 only)

**Activities:**

- Execute plan steps in order
- Run file edits and writes
- Execute shell commands for testing
- Commit changes to git
- Log all actions to execute.jsonl event stream
- Accumulate cost in real-time

**Tools available:**

- `file_edit` — Find-replace in existing files
- `file_write` — Create new files
- `shell_execute` — Run commands (npm, python, etc.)
- `git_operations` — Commit and push changes
- `install_package` — Install dependencies if needed

**Success criteria:**

- All plan steps completed successfully
- No shell command errors
- Git commits are clean
- Files are formatted correctly

**Duration:** 5-20 seconds

**Cost:** $0.001-0.05 (most jobs use OpenCode at ~$0.001)

**Typical execution:**

```
Step 1: file_edit src/styles/mobile.css — SUCCESS
Step 2: file_edit src/auth/login.tsx — SUCCESS
Step 3: shell_execute "npm run test:mobile" — SUCCESS
Step 4: git_operations commit "Fix login button alignment on mobile" — SUCCESS
All steps completed. Cost: $0.0028
```

### Phase 4: VERIFY (70-90% progress)

**Objective:** Validate code quality and security

**Triple AI Code Review:**

1. **Code Reviewer** (Kimi 2.5) — Logic, patterns, best practices
2. **Static Analysis** — Linting, type checking, formatting
3. **Pentest AI** (Kimi Reasoner) — Security vulnerabilities

**Activities:**

- Review changed files for logic errors
- Check against project code patterns
- Run static analysis tools (eslint, prettier, tsc)
- Check for security vulnerabilities
- Verify tests pass
- Compare against acceptance criteria

**Findings severity levels:**

- **Critical** — Blocks merge (security exploit, logic error, breaking change)
- **Major** — Blocks merge (performance issue, bad pattern, accessibility)
- **Minor** — Non-blocking (style nitpick, comment, optimization)
- **Info** — Non-blocking (alternative suggestion, documentation)

**Success criteria:**

- Zero critical findings
- Zero major findings
- Static analysis passes
- Tests pass (if applicable)

**Duration:** 8-15 seconds

**Cost:** $0.0008-0.003 (Kimi 2.5 + static tools)

**If blocked:**

- Re-execute Phase 3 with fix instructions
- Return to Phase 4 verification
- Repeat until blocked findings are resolved

**Typical review output:**

```
✓ Code Reviewer (Kimi 2.5): No issues found
✓ Static Analysis (ESLint): All checks passed
✓ Pentest AI (Kimi Reasoner): No vulnerabilities detected
VERDICT: PASS — Ready to deliver
```

### Phase 5: DELIVER (90-100% progress)

**Objective:** Finalize changes and report results

**Activities:**

- Apply any final formatting fixes
- Create final git commit (if not already committed)
- Push to remote repository
- Generate summary report
- Store artifacts in job directory
- Publish completion event
- Report to originating channel

**Tools available:**

- `git_operations` — Final push to main/master
- `file_write` — Generate report files
- Event publishing (internal)

**Success criteria:**

- Code is merged to main branch
- All artifacts are saved
- Result report is accurate
- Completion event is published

**Duration:** 3-8 seconds

**Cost:** Minimal (~$0.0001)

**Typical delivery:**

```
Pushing to GitHub...
✓ Commit abc123def456 pushed to main branch
✓ Artifacts saved to data/jobs/runs/{job_id}/artifacts/
✓ Result written to result.json
✓ Slack notification sent to #engineering
COMPLETE: Job finished in 35 seconds, cost $0.0044
```

## File Structure

Each job creates a directory to store all execution artifacts and logs.

```
data/jobs/runs/{job-id}/
├── job.json              # Initial job metadata
├── progress.json         # Live progress (updated real-time)
│                         # Fields: phase, progress_pct, current_step,
│                         # tools_called, cost_usd, eta_seconds
├── execute.jsonl         # Event log (newline-delimited JSON)
│                         # One JSON object per line, one event per line
├── result.json           # Final result (written on completion/failure)
│                         # Fields: status, output, cost, duration, git_commit, artifacts
├── plan.json             # ExecutionPlan from Phase 2
│
├── review_code.json      # Code Reviewer findings (Phase 4)
├── review_static.json    # Static Analysis findings (Phase 4)
├── review_security.json  # Pentest AI findings (Phase 4)
│
└── artifacts/            # Directory for generated/modified files
    ├── src/
    │   └── auth/
    │       └── login.tsx
    └── src/
        └── styles/
            └── mobile.css
```

### progress.json format

Updated in real-time, allows UI to show live progress:

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "phase": "EXECUTE",
  "progress_pct": 55,
  "current_step": 2,
  "total_steps": 3,
  "step_description": "Edit src/auth/login.tsx",
  "tools_called": ["file_read", "file_edit"],
  "cost_usd": 0.0028,
  "duration_seconds": 15,
  "eta_seconds": 12,
  "status": "running"
}
```

### execute.jsonl format

Event log with one JSON object per line:

```jsonl
{"type":"job.phase_started","phase":"RESEARCH","timestamp":"2026-03-04T17:45:32Z"}
{"type":"job.tool_called","tool":"glob_files","pattern":"**/*.tsx","timestamp":"2026-03-04T17:45:33Z"}
{"type":"job.tool_completed","tool":"glob_files","result_count":12,"cost_usd":0.0001,"timestamp":"2026-03-04T17:45:34Z"}
{"type":"job.phase_completed","phase":"RESEARCH","duration_seconds":8,"cost_usd":0.0005,"timestamp":"2026-03-04T17:45:40Z"}
```

## Monitoring Live Jobs

### Job Viewer UI

**URL:** `https://<your-domain>/job_viewer.html`

**Features:**

- Real-time progress bar (0-100%)
- Current phase display
- Cost meter (accumulated cost in USD)
- Event log (live updates)
- Kill switch button
- Artifact preview (for certain file types)
- Phase timeline (visual breakdown of time per phase)

### WebSocket Real-Time Updates

**Endpoint:** `ws://<your-domain>/ws/jobs/{job_id}`

**Message frequency:** Every 500ms (or on significant event)

**Payload:**

```json
{
  "type": "progress",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "phase": "EXECUTE",
  "progress_pct": 55,
  "cost_usd": 0.0028
}
```

### REST API Endpoints

**Get current job state:**

```
GET /api/jobs/{job_id}/live
```

**Response:**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "phase": "EXECUTE",
  "progress_pct": 55,
  "cost_usd": 0.0028
}
```

**Stream all events (SSE):**

```
GET /api/events/stream
```

**List all jobs:**

```
GET /api/jobs?status=running&project=barber-crm
```

## Cost Tracking

All costs are tracked in real-time at multiple levels.

### Per-Phase Breakdown

```json
{
  "RESEARCH": { "cost_usd": 0.0005, "duration_seconds": 8 },
  "PLAN": { "cost_usd": 0.0008, "duration_seconds": 12 },
  "EXECUTE": { "cost_usd": 0.0028, "duration_seconds": 15 },
  "VERIFY": { "cost_usd": 0.0002, "duration_seconds": 6 },
  "DELIVER": { "cost_usd": 0.0001, "duration_seconds": 3 },
  "total_cost_usd": 0.0044
}
```

### Per-Tool Breakdown

```json
{
  "file_read": { "calls": 3, "cost_usd": 0.0008 },
  "glob_files": { "calls": 2, "cost_usd": 0.0001 },
  "file_edit": { "calls": 2, "cost_usd": 0.001 },
  "shell_execute": { "calls": 1, "cost_usd": 0.0015 },
  "git_operations": { "calls": 1, "cost_usd": 0.001 }
}
```

### Typical Job Costs

| Job Type         | Complexity | Cost Range    | Primary Executor  |
| ---------------- | ---------- | ------------- | ----------------- |
| Simple bug fix   | Low        | $0.001-0.005  | OpenCode (Gemini) |
| Standard feature | Medium     | $0.02-0.05    | Haiku fallback    |
| Complex refactor | High       | $0.10-0.50    | Sonnet (P0 only)  |
| Security audit   | Variable   | $0.005-0.02   | Kimi Reasoner     |
| Documentation    | Very Low   | $0.0005-0.002 | OpenCode          |

## Error Recovery

When jobs fail, OpenClaw implements multiple recovery strategies.

### Kill Switch

**Trigger:** `POST /api/jobs/{job_id}/kill`

**Behavior:**

- Sets file-based kill flag in job directory
- Guardrails check flag at every iteration (every tool call)
- Execution stops gracefully within 2-5 seconds
- Job status transitions to `failed`
- Partial results are preserved for debugging

**Typical use case:** Job stuck, human wants to stop execution

### Automatic Retries

**Tool failures:** Up to 2 retries with exponential backoff (1s, 3s)

**Phase failures:** If recoverable, entire phase re-executes up to 2 times

**Circuit breaker:** After 2 consecutive failures, skip tool and proceed

### Error Logging

Failed jobs retain complete event logs for debugging:

```json
{
  "type": "job.tool_failed",
  "tool": "shell_execute",
  "command": "npm run test:mobile",
  "error": "npm ERR! ERESOLVE unable to resolve dependency tree",
  "timestamp": "2026-03-04T17:45:45Z",
  "attempt": 1,
  "will_retry": true
}
```

### Manual Intervention

For P0 jobs, humans can:

1. View full event log in dashboard
2. Manually trigger Phase 3 re-execution with different parameters
3. Skip to Phase 5 delivery and deploy manually
4. Kill job and reassign to different agent type

## Event Types

All events are published to the event stream and can be consumed via SSE or WebSocket.

| Event Type               | Description                    | Payload                                    |
| ------------------------ | ------------------------------ | ------------------------------------------ |
| `job.created`            | Job entered queue              | job_id, project, task, priority            |
| `job.analyzing`          | Overseer began analysis        | job_id, agent_type                         |
| `job.ready_for_approval` | Execution plan created         | job_id, plan_summary, estimated_cost       |
| `job.approved`           | Job approved for execution     | job_id, approved_by, approved_at           |
| `job.running`            | Execution worker began Phase 1 | job_id, worker_id                          |
| `job.phase_started`      | Phase began execution          | job_id, phase, timestamp                   |
| `job.tool_called`        | Tool invocation started        | job_id, tool, parameters                   |
| `job.tool_completed`     | Tool invocation finished       | job_id, tool, result, cost_usd             |
| `job.tool_failed`        | Tool invocation failed         | job_id, tool, error, attempt, will_retry   |
| `job.phase_completed`    | Phase finished                 | job_id, phase, duration_seconds, cost_usd  |
| `job.completed`          | Job finished successfully      | job_id, output, cost_usd, git_commit       |
| `job.failed`             | Job failed (terminal)          | job_id, error, phase_failed, event_log_url |

## Best Practices

### For Job Creators

- Be specific in task descriptions (not "fix the code", but "fix login button alignment on mobile")
- Set appropriate priority level
- Reference GitHub issue numbers if applicable
- Provide acceptance criteria

### For Monitoring

- Use dashboard for visual progress
- Use WebSocket for real-time applications
- Use REST API for polling status
- Check event log for debugging failures

### For Cost Management

- P3 jobs use lower-cost agents automatically
- P0 jobs may incur higher costs (Sonnet fallback)
- Monitor per-job costs in dashboard
- Set cost alerts at project level

### For Debugging

- Enable verbose event logging in progress.json
- Download complete execute.jsonl event log
- Check review\_\* JSON files for Phase 4 findings
- Reproduce failure locally if possible
