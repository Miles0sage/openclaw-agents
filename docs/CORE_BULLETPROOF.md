# OpenClaw Core Bulletproof Plan

**Based on:** Web research (2024–2026) on how people use autonomous AI coding agents and what makes them reliable in production.  
**Goal:** Harden OpenClaw’s core so the runner, gateway, and job lifecycle are fault-tolerant, observable, and predictable.

---

## 1. How People Use These Systems (Research Summary)

### Usage patterns

- **Single job, long run:** One task (e.g. “fix this bug”) runs for minutes to hours with many tool calls. Failure at step 9 of 10 should not mean “start over.”
- **Scheduled / batch:** Cron-style jobs (e.g. daily refactors, report generation). Failures must be detectable and resumable.
- **Human-in-the-loop:** Agent pauses for approval (e.g. deploy, spend). State must survive restarts and long idle periods.
- **Multi-step with side effects:** Emails sent, DB writes, API calls. Retries must be safe; some actions need compensation or explicit “no retry.”

### What actually works in production

| Finding | Source / pattern |
|--------|-------------------|
| **~85–90% task completion** is a typical ceiling for non-trivial agent workflows; the rest is edge cases and subtle bugs. | Gremlin, Viqus, CoderCops |
| **Deterministic scaffolding + LLM decision points** beats “full autonomy.” Use a fixed pipeline (e.g. research → plan → execute → verify → deliver) and let the model decide *what* to do at each step, not *whether* to run the step. | Building AI Agents That Actually Work |
| **Layered validation:** Schema validation on every tool call (catches ~60% of malformed output) plus optional semantic check (e.g. small model: “does this make sense?”). | Production lessons 2025–2026 |
| **Graceful degradation > retry loops.** When a step fails, prefer fallback paths or human escalation instead of retrying with the same context. | Multiple sources |
| **~70% of “multi-agent” ideas** are better solved by one well-designed agent with good tools and instructions. Multi-agent adds coordination cost and failure modes. | CoderCops, Multi-Agent vs Single-Agent |
| **Durable execution** is baseline: every important step persisted, resume from last checkpoint on crash. Temporal, LangGraph, DBOS, Inngest all push this. | Zylos, Temporal, LangGraph |
| **Three health signals:** (1) **Liveness** — process alive, (2) **Progress** — advancing toward goal, (3) **Quality** — output correctness. Stuck agents = “high activity, zero progress” (Loopers, Wanderers, Repeaters). | Zylos Self-Healing |
| **Circuit breakers** stop cascading failures (e.g. repeated calls to a failing API). States: CLOSED → OPEN → HALF-OPEN. | Error recovery / resilience guides |
| **Context overflow** is the “OOM of agents.” Track token/context usage; at 70% warn, at 85% compact/summarize, at 95% checkpoint and restart with compacted context. | Zylos, LangGraph |

---

## 2. How OpenClaw Maps Today

| Research pattern | OpenClaw today | Gap / action |
|-----------------|----------------|--------------|
| **Durable execution / checkpointing** | `checkpoint.py`: phase + step_index + state; Supabase or SQLite. Resume from latest checkpoint. | ✅ Strong. Ensure every phase boundary and “expensive” step writes a checkpoint; document recovery semantics. |
| **Deterministic pipeline** | 5-phase pipeline (research → plan → execute → verify → deliver) with fixed order. | ✅ Aligned. Keep phases; avoid “agent chooses next phase” in core path. |
| **Circuit breaker** | `error_recovery.py`: CircuitBreaker per agent, state file, retry policies. | ✅ Present. Wire it into every LLM/tool call path and expose state in dashboard. |
| **Retry policy** | RetryPolicy with exponential backoff, per ErrorType. | ✅ Present. Add “max retries then escalate” and optional fallback model. |
| **Progress / liveness** | Heartbeat monitor, progress in JobProgress. | ⚠️ Add **progress metric** (e.g. “last step completed at T”) and **stuck detection** (same action N times, or no progress for M minutes). |
| **Layered validation** | Phase schema validation (`validate_phase_output`). | ⚠️ Add **tool-call schema validation** (args shape + types) before execution; optional semantic check for high-risk tools. |
| **Context overflow** | IDE session, compact, token-ish limits in guardrails. | ⚠️ Make **context budget** explicit (e.g. tokens or message count), with thresholds (70/85/95%) and auto-compact or checkpoint+restart. |
| **Quality signal** | LLM Judge after verify/deliver, quality_score stored. | ✅ Good. Add “quality gate” option: fail job or escalate if score &lt; threshold. |
| **Self-healing / recovery** | CrashRecovery in error_recovery, job status updates. | ⚠️ Add **stuck detection** (Looper/Wanderer/Repeater) and **corrective injection** (e.g. “You appear to be repeating; try a different approach”) or escalate. |
| **Single-agent-first** | One runner, one “agent” per job (agent_key), phases are stages. | ✅ Good. Avoid adding extra agents unless a clear case (e.g. parallel subtasks, context overflow). |

---

## 3. Core Bulletproof Plan (Concrete)

### Tier 1: Already in place — document and harden

1. **Checkpoints**
   - Ensure every phase transition and after every “expensive” step (e.g. after every tool batch in execute) calls `save_checkpoint`.
   - Document: “On restart, runner loads `get_latest_checkpoint(job_id)` and resumes from that phase/step; no re-execution of completed work.”
   - Add a test: start job, kill process mid-phase, restart, assert job resumes from checkpoint.

2. **Circuit breaker**
   - Ensure every LLM call and every external API call (e.g. model provider) goes through the circuit breaker (or an equivalent “is this agent/provider available?” check).
   - Expose circuit state in System dashboard (e.g. per-agent OPEN/HALF-OPEN/CLOSED).
   - On OPEN: fail fast, don’t retry; optionally notify (Slack/Telegram).

3. **Error classification**
   - Keep using `ErrorType` (rate_limit, timeout, server_error, etc.).
   - Map “transient” (retry with backoff) vs “permanent” (fail fast, no retry). e.g. 429 → transient; 402 billing → permanent.
   - After N transient retries, escalate (mark job failed, alert) instead of infinite retry.

### Tier 2: Add in the next sprint

4. **Progress metric + stuck detection**
   - Define one **progress metric** per job: e.g. “last phase + last step index” or “last tool call timestamp.”
   - **Stuck detector:** If, for the same job, the progress metric is unchanged for M minutes (e.g. 5–10) *or* the last K actions (e.g. 5) are identical (same tool + same args hash), mark “stuck.”
   - On stuck: (a) inject a corrective system message (“You appear to be repeating. Reassess the goal and try a different approach.”), (b) if still stuck after one more attempt, mark job failed and alert.
   - Store “recent action hashes” in memory or in checkpoint (e.g. last 10) for repetition detection.

5. **Tool-call validation layer**
   - Before every `execute_tool`, validate tool name (must be in allowlist for agent) and argument schema (required keys, types).
   - Reject invalid calls with a clear error to the agent (no execution); optionally log for analytics.
   - Reduces “malformed output” failures and improves safety.

6. **Context budget and auto-compact**
   - Add an explicit **context budget** (e.g. max messages or token estimate) per job.
   - At 70%: log warning, optionally trigger light compact (summarize oldest messages).
   - At 85%: force compact or summarize; if already compacted, consider “checkpoint and restart with summary.”
   - At 95%: checkpoint, build summary of conversation + state, restart runner for this job with summary as new context (no re-execution of completed steps).
   - Reuse or extend existing IDE session / compact logic so it’s shared and consistent.

### Tier 3: Longer-term (durable execution and ops)

7. **Journal-style step logging (optional)**
   - Log every “durable step” (e.g. phase completion, tool batch) to an append-only log (e.g. `data/traces/spans.jsonl` or a dedicated job journal).
   - On crash, recovery can replay “what was done” and resume from last logged step. Complements checkpoints with an audit trail.

8. **Quality gate**
   - After LLM Judge runs, if `overall_score < threshold` (e.g. 0.5): optionally mark job as “completed but low quality,” notify, and/or trigger human review.
   - Configurable per job or per agent.

9. **Runbook and alerts**
   - Document: “If job is stuck, check X. If circuit is OPEN, check Y. If context overflow, do Z.”
   - Wire critical failures (job failed after retries, circuit opened, stuck detected) into existing Slack/Telegram alerts.

---

## 4. Principles to Keep

- **Single-agent-first:** Prefer one agent with good tools and phases; add more “agents” only when context or parallelism truly require it.
- **Deterministic shell, LLM decisions:** Pipeline and step order are fixed; the model decides *content* (what to research, what to plan, what to run).
- **Fail fast where it matters:** Circuit breaker and “permanent” errors should stop retries and surface immediately.
- **Progress over activity:** Measure “steps completed” or “phase advanced,” not “number of API calls.”
- **Checkpoint every expensive step:** So that “resume” never re-runs expensive LLM or tool work.

---

## 5. References (from research)

- Gremlin, Augment, Viqus, CoderCops: reliability best practices for AI coding agents.
- Zylos Research: Durable Execution (journal/replay, DB checkpointing, Saga), Self-Healing (liveness/progress/quality, Loopers/Wanderers/Repeaters).
- Temporal, LangGraph, DBOS, Inngest: durable execution patterns.
- Multi-Agent vs Single-Agent (Towards AI, CoderCops): single agent with good tools often beats multi-agent; use multi-agent only when necessary.
- Microsoft / Cloudflare: durable task extensions and workflows for agents.

---

*This doc is the “core bulletproof” plan: align OpenClaw with how people use these systems and with production resilience patterns, and close the gaps above in order of tier.*
