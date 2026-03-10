# OpenClaw System Architecture

**Version:** v4.1 (Audit-hardened, 2026-03-04)
**Status:** Production-ready
**Success Rate:** 90%+ across all projects

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Core Architecture](#core-architecture)
3. [Agent Roster](#agent-roster)
4. [Request Flow](#request-flow)
5. [Job Pipeline (5-Phase Model)](#job-pipeline-5-phase-model)
6. [Component Details](#component-details)
7. [Data Storage](#data-storage)
8. [Security Model](#security-model)
9. [Routing System](#routing-system)
10. [Deployment](#deployment)
11. [Cost Model](#cost-model)
12. [Scalability & Performance](#scalability--performance)

---

## System Overview

OpenClaw is a **multi-agent AI agency platform** that orchestrates specialized AI agents through a FastAPI gateway. It routes complex technical tasks through a 5-phase pipeline (Research → Plan → Execute → Verify → Deliver), with each phase handled by agents optimized for that stage.

### Key Principles

- **Agent Specialization**: Each agent has a specific role, cost tier, and expertise profile
- **Identity-Driven Communication**: Agents maintain distinct personas to prevent confusion
- **Cost Optimization**: Routes tasks to the cheapest capable agent for each job type
- **Fallback Chains**: Escalates to more capable (expensive) agents only when needed
- **Event-Driven**: All state changes emit events for real-time monitoring and audit trails
- **Persistent Storage**: All job state stored to disk, recoverable on crash/restart

---

## Core Architecture

### System Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        OPENCLAW GATEWAY                            │
│                    (FastAPI + WebSocket)                           │
│                    Port 8000 (Systemd service)                      │
└─────────────────────────────────────────────────────────────────────┘
                               │
                    ┌──────────┼──────────┐
                    │          │          │
                    ▼          ▼          ▼
            ┌──────────┐ ┌─────────┐ ┌──────────┐
            │  REST    │ │WebSocket│ │ Webhooks │
            │  API     │ │  Live   │ │ (Slack,  │
            │ Endpoints│ │ Job     │ │  Discord)│
            │          │ │ Viewer  │ │          │
            └──────────┘ └─────────┘ └──────────┘
                    │          │          │
                    └──────────┼──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  ORCHESTRATOR       │
                    │  (Message Router)   │
                    │  (Identity Manager) │
                    └──────────┬──────────┘
                               │
                ┌──────────────┼──────────────┐
                │              │              │
                ▼              ▼              ▼
        ┌─────────────┐ ┌──────────────┐ ┌──────────────┐
        │JOB RUNNER   │ │EVENT ENGINE  │ │AGENT ROUTER  │
        │             │ │              │ │(Complexity   │
        │ 5-Phase     │ │ Pub/Sub      │ │ Analysis)    │
        │ Pipeline    │ │ Event Broker │ │              │
        └──────┬──────┘ └──────┬───────┘ └──────┬───────┘
               │               │                 │
    ┌──────────▼───────────────▼────────────────▼──────────┐
    │                    AGENT DISPATCH LAYER             │
    └──────────────────────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
    ┌─────────┐  ┌────────────┐  ┌──────────────┐
    │ OpenCode│  │Claude SDK  │  │External APIs │
    │(Gemini) │  │(Opus,      │  │(Deepseek,    │
    │         │  │Sonnet,     │  │MiniMax,      │
    │Local    │  │Haiku)      │  │Supabase)     │
    │Executor │  │            │  │              │
    └─────────┘  └────────────┘  └──────────────┘
```

---

## Agent Roster

Each agent runs on a specific model optimized for its role. Routing is determined by task complexity and cost constraints.

### Agent Configuration

| Agent                     | Model            | Cost/1M Input | Tier     | Role        | Primary Skills                                |
| ------------------------- | ---------------- | ------------- | -------- | ----------- | --------------------------------------------- |
| **Overseer** (PM)         | Claude Opus 4.6  | $15           | Premium  | Coordinator | Decomposition, QA, Client communication       |
| **CodeGen Pro**           | Kimi 2.5         | $0.14         | Standard | Developer   | Clean code, testing, APIs, routine tasks      |
| **CodeGen Elite**         | MiniMax M2.5     | $0.30         | Standard | Complex Dev | Multi-file refactor, architecture, SWE-Bench  |
| **Pentest AI**            | Kimi (Reasoner)  | $0.27         | Standard | Security    | Vulnerabilities, threat modeling, RLS         |
| **SupabaseConnector**     | Claude Opus 4.6  | $15           | Premium  | Data        | SQL, schema exploration, RLS validation       |
| **Code Reviewer**         | Kimi 2.5         | $0.14         | Standard | Reviewer    | PR review, code audit, pattern matching       |
| **Architecture Designer** | MiniMax M2.5     | $0.30         | Standard | Architect   | System design, scalability, API contracts     |
| **Test Generator**        | Kimi 2.5         | $0.14         | Standard | Tester      | Test generation, edge case detection          |
| **Debugger**              | Claude Opus 4.6  | $15           | Premium  | Debug       | Race conditions, memory leaks, complex bugs   |
| **Vision AI**             | Claude Haiku 4.5 | $0.80         | Economy  | Vision      | Scene description, OCR, object identification |

### Agent Communication Rules

- **Only PM can talk to clients** - Developers, security agents, and specialists route through PM
- **Agent signatures required** - Every message ends with agent emoji + name (e.g., `— Overseer`)
- **Identity validation** - Orchestrator enforces message routing rules before dispatch
- **Internal channels only** - Inter-agent communication stays within the system

---

## Request Flow

### Phase 0: Inbound Request

1. Request arrives via:
   - REST API endpoint (`POST /jobs/create`)
   - Webhook from Slack, Discord, Telegram
   - WebSocket connection from client UI
   - Direct function call from CLI/SDK

2. **Request Validation**
   - Authentication token check
   - Rate limiting (30 req/min per IP)
   - Payload schema validation
   - Quota check (daily/monthly spend limits)

3. **Job Creation**
   - Generate unique job ID (format: `job-YYYYMMDD-HHMMSS-{random}`)
   - Store to `./data/jobs/jobs.jsonl`
   - Emit `job.created` event

4. **Agent Routing Decision**
   - AgentRouter analyzes task intent/complexity (semantic + keyword matching)
   - Returns routing decision with confidence score (0-1)
   - Cached for 5 minutes to avoid repeated analysis

### Example Request Path

```json
Request → Validation → Job Creation → Routing → Pipeline Start → Result Delivery
```

---

## Job Pipeline (5-Phase Model)

Every job progresses through exactly 5 phases. Progress is broadcast live via WebSocket.

```
PHASE 0: RESEARCH (0-20%)
├─ Read relevant files
├─ Search codebase
├─ Gather context
└─ Document findings

PHASE 1: PLAN (20-40%)
├─ Create execution steps
├─ Estimate cost
├─ Define acceptance criteria
└─ Assign primary agent

PHASE 2: EXECUTE (40-70%)
├─ Run execution steps
├─ Handle errors/retries
├─ Generate code/output
└─ Save artifacts

PHASE 3: VERIFY (70-90%)
├─ Code review (Kimi 2.5)
├─ Static analysis
├─ Security audit (Kimi Reasoner)
└─ Block on critical/major issues

PHASE 4: DELIVER (90-100%)
├─ Apply changes to repo
├─ Commit & push (if code)
├─ Send notification
└─ Archive job data
```

### Execution Strategy

The job pipeline selects the execution strategy based on task type:

1. **OpenCode (Gemini 2.5 Flash)**
   - Primary execution backend
   - Cost: ~$0.001 per execution
   - Best for: Code generation, file editing, shell commands
   - Falls back to Claude SDK on failure

2. **Claude SDK (Haiku/Sonnet/Opus)**
   - Fallback when OpenCode fails
   - Cost: $0.02 (Haiku) → $0.50 (Sonnet/Opus)
   - Escalation: P1/P2 use Haiku, P0 uses Sonnet/Opus

3. **External Agent Calls**
   - Specialized agents (Pentest AI, SupabaseConnector, etc.)
   - Routed via Orchestrator
   - Can run in parallel or serial depending on dependencies

### Phase Progress Example

```
Job started: job-20260304-093000-abc123
0%   [====        ] Research phase
20%  [========    ] Planning phase
40%  [============] Executing phase
70%  [================] Verifying phase (Code Review: 1/3 complete)
90%  [==================] Delivering phase
100% [====================] Complete (Status: success)
```

---

## Component Details

### 1. Gateway (gateway.py - 8,110 lines)

**Responsibility**: HTTP/WebSocket server, job orchestration, state management

**Key Endpoints:**

```
POST   /jobs/create              Create new job
GET    /jobs/<id>                Get job status
GET    /jobs/<id>/result         Get job result
WS     /jobs/<id>/stream         WebSocket live feed
GET    /health                   System health check
GET    /cost/summary             Monthly cost report
GET    /cost/metrics             Detailed cost breakdown
POST   /cost/export              Export cost data
GET    /agents/status            Agent availability
GET    /webhooks/verify/:token   Verify webhook auth
```

**Core Functions:**

- `create_job()`: Validate request, generate job ID, store to disk, emit event
- `get_job_status()`: Read `data/jobs/runs/{id}/progress.json`, broadcast via WebSocket
- `execute_job_pipeline()`: Orchestrate 5-phase execution
- `on_websocket_connect()`: Open live event stream to client
- `validate_quota()`: Check daily/monthly spend limits before execution

**Data Flow:**

```
Request → Validation → Job Queue → Runner picks up → Pipeline execution
                                         ↓
                                   Event Engine broadcast
                                         ↓
                                   WebSocket → Client UI
```

### 2. Orchestrator (orchestrator.py - 387 lines)

**Responsibility**: Agent identity management, message routing, workflow state transitions

**Core Classes:**

- `AgentRole`: Enum of agent types (PM, DEVELOPER, SECURITY, SYSTEM)
- `AgentIdentity`: Agent name, emoji, persona, communication rules
- `Message`: Structured message with sender, recipient, audience
- `Orchestrator`: Routes messages, enforces identity rules, transitions workflow state

**Workflow States:**

```
idle → client_request → development → security_audit → {review_fix | delivery} → idle
```

**Key Methods:**

- `validate_message()`: Check if sender can talk to recipient
- `route_message()`: Determine delivery route (client/team/specific agent/system)
- `format_message_for_agent()`: Add agent signature & identity context
- `transition_workflow_state()`: Move to next valid state, emit event
- `get_agent_context()`: Return identity snippet for agent's system prompt

**Example Routing:**

```python
# CodeGen Pro tries to message client (INVALID)
❌ "CodeGen Pro cannot talk directly to clients! Route through PM."

# PM messages client (VALID)
✓ Route: client → send via Slack/email/webhook
```

### 3. Agent Router (agent_router.py - 912 lines)

**Responsibility**: Intelligent agent selection based on task complexity

**Routing Logic:**

1. **Semantic Analysis** (95%+ accuracy target)
   - Embeds query into vector space (embeddings cache)
   - Compares against skill keywords for each agent
   - Returns similarity scores

2. **Keyword Matching** (fallback if embeddings fail)
   - Scans query for security, development, database, planning, research keywords
   - Builds intent classification (e.g., 50% security, 30% dev, 20% planning)
   - Selects best-matching agent

3. **Cost Optimization**
   - Routes low-complexity to CodeGen Pro ($0.14/M) vs CodeGen Elite ($0.30/M)
   - Prefers cheaper agents when confidence > 80%
   - Escalates to premium agents (Opus: $15/M) only when necessary

4. **Performance Caching**
   - Caches routing decisions for 5 minutes
   - Reduces latency to < 50ms for repeat queries
   - Cache key: hash of query content

**RoutingDecision Output:**

```json
{
  "agentId": "coder_agent",
  "confidence": 0.92,
  "reason": "Task matches development keywords (92% confidence)",
  "intent": "implement_feature",
  "keywords": ["code", "implement", "function", "api"],
  "cost_score": 1.0,
  "cached": false
}
```

**Routing Matrix:**

| Task Type                          | Primary Agent         | Cost    | Secondary Route          |
| ---------------------------------- | --------------------- | ------- | ------------------------ |
| API endpoint, bug fix, component   | CodeGen Pro           | $0.14/M | CodeGen Elite if complex |
| Multi-file refactor, architecture  | CodeGen Elite         | $0.30/M | -                        |
| Security, vulnerability, pentest   | Pentest AI            | $0.27/M | -                        |
| SQL query, schema, data validation | SupabaseConnector     | $15/M   | -                        |
| PM duties, decomposition, QA       | Overseer              | $15/M   | -                        |
| Code review, pattern matching      | Code Reviewer         | $0.14/M | -                        |
| Testing, edge cases                | Test Generator        | $0.14/M | -                        |
| System design, scalability         | Architecture Designer | $0.30/M | -                        |
| Deep bugs, race conditions         | Debugger              | $15/M   | -                        |

### 4. Job Runner (implied, core execution loop)

**Responsibility**: Execute job pipeline, manage phase transitions, error handling

**Execution Loop:**

```python
while job.status != "completed":
    current_phase = job.current_phase

    # Phase execution
    result = execute_phase(job, current_phase)

    # Error handling
    if result.status == "failed":
        if retry_count < MAX_RETRIES:
            retry_count += 1
            continue
        else:
            job.status = "failed"
            break

    # Emit event
    emit_event("phase.completed", {"phase": current_phase, "progress": progress})

    # Broadcast to WebSocket clients
    broadcast_progress(job.id, progress)

    # Move to next phase
    job.current_phase = next_phase(current_phase)
    job.progress = get_progress_percent(current_phase)
    save_job_state(job)
```

### 5. Event Engine

**Responsibility**: Pub/sub system, event logging, real-time notifications

**Event Types:**

```
job.created         → Job added to queue
phase.started       → Phase began execution
phase.completed     → Phase finished successfully
job.completed       → All 5 phases done
job.failed          → Job execution failed
cost.alert          → Monthly/daily spend exceeded
agent.timeout       → Agent exceeded timeout
cost.logged         → Cost event for audit trail
```

**Event Flow:**

```
Event emitted → Event Engine → Subscribers (WebSocket, Slack, Audit Log)
                                    ↓
                              data/jobs/runs/{id}/execute.jsonl (append)
```

### 6. External Integrations

#### Supabase (Data Agent)

- **Barber CRM**: `djdilkhedpnlercxggby.supabase.co`
- **Delhi Palace**: `banxtacevgopeczuzycz.supabase.co`
- SupabaseConnector queries via RPC with service role key
- All queries respect RLS policies

#### Cloud Models

```
┌──────────────────────────────────────────────────────┐
│ Model Provider Integrations                         │
├──────────────────────────────────────────────────────┤
│ Anthropic (Claude Opus/Sonnet/Haiku)                │
│ Deepseek (Kimi 2.5, Kimi Reasoner)                  │
│ MiniMax (M2.5, M2.5-Lightning)                       │
│ Google Gemini (2.5 Flash, 3 Flash Preview)          │
│ OpenCode CLI (local executor)                        │
└──────────────────────────────────────────────────────┘
```

#### Communication Channels

```
┌──────────────────────────────────────────────────────┐
│ Outbound Channel Integration                         │
├──────────────────────────────────────────────────────┤
│ Slack (webhooks, DMs, threaded replies)             │
│ Discord (embeds, reactions, status updates)         │
│ Telegram (bot messages, inline keyboards)           │
│ WhatsApp (via Twilio - optional)                    │
│ SMS (via Twilio - alerts only)                      │
└──────────────────────────────────────────────────────┘
```

---

## Data Storage

### Directory Structure

```
./data/
├── jobs/
│   ├── jobs.jsonl                    # All job metadata (one per line)
│   ├── kill_flags.json               # Abort signals per job ID
│   ├── proposals.jsonl               # Approval workflow entries
│   ├── tasks.json                    # Internal task tracking
│   ├── queue/                        # (Legacy) Pending jobs
│   ├── runs/                         # Active/completed job results
│   │   └── {job-id}/
│   │       ├── progress.json         # Live progress (0-100%)
│   │       ├── execute.jsonl         # Phase execution log (events)
│   │       ├── result.json           # Final result & artifacts
│   │       ├── artifacts/            # Generated files
│   │       │   ├── code.patch
│   │       │   ├── schema.sql
│   │       │   └── deployment.log
│   │       └── audit/                # Security review logs
│   │           ├── code_review.json
│   │           ├── static_analysis.json
│   │           └── pentest_report.json
│   ├── history/                      # Archived completed jobs (90+ days old)
│   │   └── {job-id}.tar.gz
│   ├── worktrees/                    # Git worktree isolation
│   │   └── {job-id}/                 # Isolated git workspace
│   │       └── (project files)
│   └── memories.jsonl                # Persistent memory (JSONL format)
├── models/
│   └── nba_xgboost.pkl              # Sports betting model (cached)
└── config.example.json               # Example configuration
```

### Job File Format

**jobs.jsonl** (one JSON object per line):

```json
{
  "id": "job-20260304-093000-abc123",
  "type": "code_generation",
  "status": "completed",
  "priority": "P2",
  "project": "openclaw",
  "created_at": "2026-03-04T09:30:00Z",
  "completed_at": "2026-03-04T09:45:30Z",
  "duration_seconds": 930,
  "agent": "coder_agent",
  "cost_usd": 0.0042,
  "tags": ["feature", "api"],
  "summary": "Implement user authentication endpoint"
}
```

**runs/{id}/progress.json** (updated in real-time):

```json
{
  "job_id": "job-20260304-093000-abc123",
  "status": "executing",
  "progress_percent": 65,
  "current_phase": "execute",
  "phases": {
    "research": { "status": "completed", "duration_ms": 120 },
    "plan": { "status": "completed", "duration_ms": 280 },
    "execute": { "status": "in_progress", "duration_ms": 5420, "step": 3, "total_steps": 8 },
    "verify": { "status": "pending" },
    "deliver": { "status": "pending" }
  },
  "last_update": "2026-03-04T09:45:20Z"
}
```

**runs/{id}/execute.jsonl** (execution event log):

```json
{"event": "phase.started", "phase": "research", "timestamp": "2026-03-04T09:30:05Z"}
{"event": "context.loaded", "files": 12, "lines": 3847, "timestamp": "2026-03-04T09:30:10Z"}
{"event": "phase.completed", "phase": "research", "duration_ms": 120, "timestamp": "2026-03-04T09:31:05Z"}
{"event": "phase.started", "phase": "plan", "timestamp": "2026-03-04T09:31:06Z"}
```

### File Size Expectations

- `jobs.jsonl`: ~70KB per 1,000 jobs
- `runs/{id}/progress.json`: ~500 bytes (updated frequently)
- `runs/{id}/execute.jsonl`: ~2-5KB per job
- `runs/{id}/result.json`: ~10-50KB (depends on code changes)

---

## Security Model

### Authentication & Authorization

1. **Gateway Token**
   - All REST endpoints require `Authorization: Bearer {token}`
   - Token checked in `validate_request_auth()`
   - Tokens stored in environment (`GATEWAY_AUTH_TOKEN`)

2. **Webhook Signature Verification**
   - Slack: HMAC-SHA256 with signing secret
   - Discord: Bot token validation
   - Custom: Timestamp + nonce for replay protection

3. **Supabase RLS**
   - SupabaseConnector respects all Row-Level Security policies
   - Service role key used only for schema introspection
   - User-level access controlled via JWT tokens (client layer)

### Code Review & Verification

**Triple AI Code Review** (for all code changes):

1. **Code Reviewer** (Kimi 2.5)
   - Pattern matching, logic errors, missing edge cases
   - Cost: $0.14/M (cheap, fast)
   - Blocks on "critical" or "major" severity issues

2. **Static Analysis**
   - Linter results (eslint, black, clippy, etc.)
   - Type checking (typescript, mypy)
   - Coverage analysis
   - Blocks on errors (not warnings)

3. **Pentest AI** (Kimi Reasoner with extended thinking)
   - OWASP Top 10 analysis
   - RLS policy validation
   - Authentication/authorization checks
   - Threat modeling
   - Blocks on "critical" vulnerabilities only

### Kill Switch

Per-job abort mechanism:

```json
// data/jobs/kill_flags.json
{
  "job-20260304-093000-abc123": {
    "kill_requested": true,
    "reason": "Manual abort via UI",
    "requested_at": "2026-03-04T09:35:00Z"
  }
}
```

Runner checks kill flag before each phase:

```python
if is_kill_flag_set(job.id):
    job.status = "cancelled"
    emit_event("job.cancelled", reason)
    break
```

### Sensitive Data

- **API Keys**: Stored in `.env` (not in git, not in logs)
- **Supabase Keys**: Environment variables only
- **Job Secrets**: Not stored in job results
- **Audit Trail**: Stores user/timestamp, not sensitive data

---

## Routing System

### Three-Layer Decision Making

#### Layer 1: Quick Heuristics (Sub-1ms)

```python
if "security" in query.lower():
    return PENTEST_AI
elif "select" or "insert" in query.lower():
    return DATABASE_AGENT
elif "plan" or "architecture" in query.lower():
    return OVERSEER
```

#### Layer 2: Keyword Scoring (10-50ms)

```python
scores = {}
for agent, keywords in ROUTING_KEYWORDS.items():
    scores[agent] = count_matches(query, keywords) / len(keywords)

agent = max(scores, key=scores.get)
```

#### Layer 3: Semantic Analysis with Caching (50-200ms)

```python
cache_key = hash(query)
if cache_key in ROUTING_CACHE:
    return ROUTING_CACHE[cache_key]

embedding = embed_query(query)
similarity_scores = {}
for agent, skill_embeddings in AGENT_SKILLS.items():
    similarity = cosine_similarity(embedding, skill_embeddings)
    similarity_scores[agent] = similarity

agent = max(similarity_scores, key=similarity_scores.get)
ROUTING_CACHE[cache_key] = agent
return agent
```

### Cost Optimization Strategy

```
Complexity Score (0-100) → Agent Selection

0-30:   CodeGen Pro ($0.14/M)      — Safe, cheap
        Code Reviewer ($0.14/M)
        Test Generator ($0.14/M)

30-60:  CodeGen Elite ($0.30/M)    — Medium complexity
        Pentest AI ($0.27/M)
        Architecture Designer ($0.30/M)

60-100: Overseer ($15/M)           — High complexity, coordination
        SupabaseConnector ($15/M)   — Data accuracy required
        Debugger ($15/M)            — Deep reasoning needed
```

---

## Deployment

### Systemd Service

**File**: `/etc/systemd/system/openclaw-gateway.service`

```ini
[Unit]
Description=OpenClaw Gateway
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=./
ExecStart=/usr/bin/python3 ./gateway.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment="PYTHONUNBUFFERED=1"
TimeoutStopSec=300
KillMode=mixed

[Install]
WantedBy=multi-user.target
```

### Commands

```bash
# Start
sudo systemctl start openclaw-gateway

# Stop
sudo systemctl stop openclaw-gateway

# Restart (deploy changes)
sudo systemctl restart openclaw-gateway

# Logs
journalctl -u openclaw-gateway -f

# Status
sudo systemctl status openclaw-gateway
```

### Network Configuration

- **Local**: 127.0.0.1:8000
- **VPS**: <your-vps-ip>:18789
- **Public**: <your-domain> (Cloudflare proxy)
- **Dashboard**: <your-domain>

### Environment Variables

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
DEEPSEEK_API_KEY=sk-...
MINIMAX_API_KEY=...
GEMINI_API_KEY=...
GATEWAY_AUTH_TOKEN=...

# Optional
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
DISCORD_BOT_TOKEN=...
TELEGRAM_BOT_TOKEN=...
BARBER_CRM_SUPABASE_ANON_KEY=...
BARBER_CRM_SUPABASE_SERVICE_ROLE_KEY=...
DELHI_PALACE_SUPABASE_ANON_KEY=...
DELHI_PALACE_SUPABASE_SERVICE_ROLE_KEY=...
```

---

## Cost Model

### Pricing by Agent

All costs in USD per 1,000,000 input tokens (output tokens vary):

| Agent             | Model            | Input | Output | Tier     | Typical Cost per Job |
| ----------------- | ---------------- | ----- | ------ | -------- | -------------------- |
| CodeGen Pro       | Kimi 2.5         | $0.14 | $0.28  | Standard | $0.0001–$0.001       |
| Code Reviewer     | Kimi 2.5         | $0.14 | $0.28  | Standard | $0.0002–$0.001       |
| Pentest AI        | Kimi Reasoner    | $0.27 | $0.68  | Standard | $0.0005–$0.002       |
| CodeGen Elite     | MiniMax M2.5     | $0.30 | $1.20  | Standard | $0.001–$0.010        |
| Overseer          | Claude Opus 4.6  | $15   | $75    | Premium  | $0.01–$0.50          |
| SupabaseConnector | Claude Opus 4.6  | $15   | $75    | Premium  | $0.01–$0.05          |
| Debugger          | Claude Opus 4.6  | $15   | $75    | Premium  | $0.02–$0.50          |
| OpenCode          | Gemini 2.5 Flash | $0.15 | $0.60  | Budget   | $0.0001–$0.001       |

### Typical Job Costs

```
Simple bug fix:      $0.001–$0.005  (CodeGen Pro + Reviewer)
API endpoint:        $0.005–$0.020  (CodeGen Pro + Test Generator)
Multi-file refactor: $0.050–$0.200  (CodeGen Elite + Reviewer + Pentest)
Architecture design: $0.050–$0.300  (Overseer + Architecture Designer)
Security audit:      $0.020–$0.100  (Pentest AI + Code Reviewer)
Deep debug:          $0.100–$1.000  (Debugger + context reading)
```

### Cost Tracking

**File**: `cost_tracker.py`

Functions:

- `calculate_cost(model, tokens_in, tokens_out)` → float (USD)
- `log_cost_event(job_id, cost, model, context)` → None
- `get_cost_metrics()` → dict with daily/monthly totals
- `get_cost_summary()` → formatted string report

**Query endpoints:**

```bash
GET /cost/summary
GET /cost/metrics
POST /cost/export?format=csv&start=2026-03-01&end=2026-03-31
```

---

## Scalability & Performance

### Performance Targets

| Operation           | Target  | Current        |
| ------------------- | ------- | -------------- |
| Job creation        | < 100ms | ~50ms          |
| Routing decision    | < 200ms | ~80ms (cached) |
| Phase transition    | < 50ms  | ~20ms          |
| WebSocket broadcast | < 100ms | ~30ms          |
| Cost calculation    | < 10ms  | ~2ms           |

### Concurrency Model

- **Job queue**: FIFO processing
- **Agent parallelism**: Up to 5 agents concurrently (configurable)
- **WebSocket connections**: No limit (linear memory overhead per connection)
- **Database queries**: Connection pooling (10 active, unlimited queued)

### Resource Usage

- **RAM**: ~500MB idle, +100MB per concurrent job
- **CPU**: Minimal (I/O bound)
- **Disk**: ~100KB per completed job
- **Network**: ~1-5KB per WebSocket event

### Bottlenecks

1. **Model API latency** (most critical)
   - OpenCode: 5-30s per execution
   - Claude SDK: 10-60s per call
   - Deepseek/MiniMax: 5-20s per call

2. **Disk I/O**
   - Writing to `/data/jobs/runs/` for every phase
   - Mitigated by batching writes (async)

3. **Token limits**
   - Deepseek Kimi: 64K context window (upgradeable to 128K)
   - MiniMax: 205K context (sufficient for most repos)
   - Claude: 200K context (standard)

### Optimization Opportunities

- [ ] Migrate `jobs.jsonl` to SQLite (faster queries, indexing)
- [ ] Implement job result compression (gzip)
- [ ] Add read-through caching for file reads (reduce API calls)
- [ ] Parallel job execution (currently sequential)
- [ ] Embed model outputs to avoid re-analysis

---

## File Reference

### Core Files

| File                 | Lines  | Purpose                           |
| -------------------- | ------ | --------------------------------- |
| `gateway.py`         | 8,110  | FastAPI server, job orchestration |
| `orchestrator.py`    | 387    | Agent identity, message routing   |
| `agent_router.py`    | 912    | Intelligent agent selection       |
| `agent_tools.py`     | 7,000+ | Tool definitions for agents       |
| `agent_watchdog.py`  | 400+   | Agent health monitoring           |
| `approval_engine.py` | ~250   | Approval workflow                 |
| `cost_tracker.py`    | ~300   | Cost calculation & logging        |
| `config.json`        | ~900   | Agent config, routing keywords    |

### Configuration

- **`config.json`**: Agent models, skills, routing keywords, provider configs
- **`.env`**: API keys (git-ignored)
- **`.env.example`**: Template with required keys

### Data Directories

- **`data/jobs/`**: Job metadata, results, artifacts
- **`data/jobs/runs/`**: Live job state (progress, logs)
- **`data/jobs/worktrees/`**: Isolated git workspaces per job

---

## System Behavior Under Load

### Queue Processing

```
Queue size > 50 → Log warning
Queue size > 100 → Pause new job creation
Agent timeout > 5min → Escalate to Overseer
Cost exceeds daily limit → Pause P3 jobs, allow P0/P1 only
```

### Fallback Chains

When primary agent fails:

```
CodeGen Pro fails → Escalate to CodeGen Elite
CodeGen Elite fails → Escalate to Overseer (for analysis)
OpenCode fails → Try Claude SDK (Haiku → Sonnet → Opus)
Model API fails → Retry 3x with exponential backoff, then fail job
```

### Graceful Shutdown

```
SIGTERM received → Finish current jobs, reject new requests
Wait 5 minutes → Force kill long-running agents
Persist all state → Resume on restart
```

---

## Monitoring & Observability

### Health Checks

```bash
GET /health
{
  "status": "healthy",
  "uptime_seconds": 86400,
  "jobs_processed": 523,
  "current_queue_size": 3,
  "agents_online": 8,
  "last_event": "2026-03-04T09:45:30Z"
}
```

### Metrics Tracked

- Jobs processed per hour
- Average job duration by phase
- Cost per project
- Agent utilization rates
- Error rates by agent
- WebSocket connection count

### Logging

- **Level**: INFO (configurable)
- **File**: `./logs/openclaw.log`
- **Rotation**: 10MB files, keep 5 backups
- **Format**: JSON (structured logging)

---

## Next Steps & Future Improvements

1. **Multi-region deployment** - Gateway replicas in US/EU/APAC
2. **Job scheduling** - Cron-like recurring jobs
3. **Advanced analytics** - Cost attribution per project/agent
4. **Agent fine-tuning** - Custom models for specific skill areas
5. **Collaborative workflows** - Multi-agent teams for large projects
6. **Real-time code merge** - Conflict resolution without human intervention

---

**For questions or contributions, see CONTRIBUTING.md**
