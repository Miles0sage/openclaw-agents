Claude Flow treats memory as the backbone and MCP tools as the hands. You get concurrent agents that coordinate cleanly, keep context tight, and ship durable artifacts without dragging long text through prompts. It feels like an ops layer for intelligence.

The stack is simple. Claude Code as the client. Claude Flow as the MCP server. SQLite memory at .swarm/memory.db for state, events, patterns, workflow checkpoints, and consensus. Artifacts hold the big payloads. Manifests in memory link everything with ids, tags, and checksums.

Coordination is explicit. Agents write hints to a shared blackboard, gate risky steps behind consensus, and record every transition as an event. Hooks inject minimal context before tools run and persist verified outcomes after. Small bundles in, durable facts out.

Planning keeps runs stable. Use GOAP to sequence actions with clear preconditions. Use OODA to shorten loops.

Observe metrics, orient with patterns, decide through votes, act with orchestration. Topology adapts from hierarchical to mesh when parallelism rises.

Long horizon work becomes repeatable. Sessions resume, workflows checkpoint, and telemetry trims context as load grows. The result is a pragmatic way to scale judgment, not just tokens. Start small, wire hooks, enforce namespaces, and let swarms do the heavy lifting.

## Summary

**Title**: Architecting swarms that think before they act
**Body**:
“I am running multi‑agent swarms on Claude Flow where memory is the API.

Agents coordinate through a shared blackboard, checkpoint long horizon workflows, and gate releases with consensus.

MCP tools wire Claude Code to orchestration and analytics, while Artifacts keep the heavy payloads out of the prompt and in a durable manifest. This is how we scale judgment, not just tokens.”
References: Claude Flow memory and MCP, Claude Artifacts. ([GitHub][2])

---

## 1) Introduction

Claude Flow combines a **hive‑mind swarm architecture**, a **SQLite memory system** at `.swarm/memory.db`, and an **MCP tool suite** to coordinate many agents in parallel while keeping context compact, durable, and auditable. It integrates natively with **Claude Code** hooks and the **Model Context Protocol**. ([GitHub][1])

**What you get**

- Concurrent agents that coordinate via shared state, events, and consensus records
- Memory that persists sessions, workflows, and patterns across runs
- MCP tools that expose orchestration, analytics, and system utilities to Claude Code
- Hookable pre and post stages for context injection, verification, and cleanup ([GitHub][2])

---

## 2) Core features you will use

- **Swarm and Hive‑Mind modes**: quick ad‑hoc swarms vs persistent multi‑agent projects with resume and long horizon memory. The README clarifies when to choose each. ([GitHub][1])
- **Memory schema**: 12 tables including `shared_state`, `events`, `workflow_state`, `patterns`, `consensus_state`, and `performance_metrics` for coordination, audit, checkpoints, learning, and telemetry. ([GitHub][2])
- **87 MCP tools**: orchestration, memory, topology optimization, performance reporting, and more under the `mcp__claude-flow__*` namespace. ([GitHub][3])
- **Hooks in Claude Code**: `PreToolUse`, `PostToolUse`, `SessionStart`, `SessionEnd` for deterministic context engineering and compliance controls. ([Claude Docs][4])
- **Artifacts**: large outputs live as Claude Artifacts; Flow stores manifests in memory so agents reference by id instead of rehydrating long text. ([Anthropic][5])
- **Performance upgrades**: session forking, hook matchers, and an in‑process MCP server that reduce latency in the latest alphas. ([GitHub][1])

---

## 3) Architecture overview

```
Claude Code  ──(MCP client)──>  Claude Flow MCP tools
   |                                     |
   | hooks + policies                    | orchestration API
   v                                     v
 pre/post scripts  <── events ──>  memory.db (SQLite)
      ^                               ├─ shared_state  (blackboard)
      |                               ├─ events        (audit)
      |                               ├─ workflow_state(checkpoints)
  artifacts panel                      ├─ consensus_state(votes)
                                        └─ performance_metrics(telemetry)
```

- **Blackboard pattern**: agents write hints to `shared_state` and append actions to `events`.
- **Consensus gating**: critical transitions record votes in `consensus_state`.
- **Resilience**: `workflow_state` and `sessions` restore long‑lived work.
- **Observability**: `performance_metrics` and `swarm_status` guide concurrency and context size. ([GitHub][2])

---

## 4) Step‑by‑step setup and sanity checks

### Step 1. Install and initialize

```bash
npm install -g @anthropic-ai/claude-code
npx claude-flow@alpha init --force
npx claude-flow@alpha --help
```

The init seeds `.claude/settings.json`, MCP wiring, and memory structures. Use `hive-mind` for persistent work or `swarm` for quick jobs. ([GitHub][1])

### Step 2. Add the Flow MCP server to Claude Code

```bash
claude mcp add claude-flow -- npx claude-flow@alpha mcp start
claude mcp list
```

Claude Code natively supports MCP servers and discovery. ([Claude Docs][6])

### Step 3. Verify memory and hooks

```bash
npx claude-flow@alpha memory stats
# Hooks live in .claude/settings.json and support PreToolUse, PostToolUse, SessionStart, SessionEnd
```

Hook fields and events are documented in Claude Code. ([Claude Docs][4])

### Step 4. Minimal smoke test

```bash
# Ad‑hoc swarm and resume later with hive‑mind
npx claude-flow@alpha swarm "build a REST API"
npx claude-flow@alpha hive-mind status
```

The README includes the swarm vs hive‑mind decision table. ([GitHub][1])

---

## 5) Context engineering patterns

### A) Minimal context bundles at PreToolUse

Build a small bundle from prior artifacts and events, then inject it before tools run.

```ts
// Claude Code conversation calling MCP
const hits =
  (await mcp__claude) -
  flow__memory_usage({
    action: "search",
    namespace: "artifacts",
    query: "auth service",
  });
const artifactIds = (hits?.items || []).slice(0, 5).map((x) => x.key.replace("artifact:", ""));
const bundle = { summary: "RBAC auth context", rules: ["prefer small diffs"], artifactIds };
```

Use this bundle in `PreToolUse` to bound input. ([GitHub][3])

### B) Durable outcomes at PostToolUse

Persist decisions and checkpoints after tools run.

```ts
(await mcp__claude) -
  flow__memory_usage({
    action: "store",
    key: "pattern:auth:validation",
    value: JSON.stringify({ regexes: ["email", "password"], confidence: 0.9 }),
    namespace: "patterns",
  });
(await mcp__claude) -
  flow__memory_usage({
    action: "store",
    key: "workflow:auth:v1",
    value: JSON.stringify({ step: "tests_passed", sha: "abc123" }),
    namespace: "workflow_state",
  });
```

Tables `patterns` and `workflow_state` support learning and resumability. ([GitHub][2])

### C) Artifact‑first outputs

Create or edit in an Artifact, store a manifest in `artifacts` namespace with checksum and tags, then reference by id across agents. ([Anthropic][5])

---

## 6) Advanced coordination for concurrent agents

### A) Start a coordinated swarm

```ts
(await mcp__claude) - flow__swarm_init({ topology: "hierarchical", maxAgents: 8 });
await Promise.all([
  mcp__claude - flow__agent_spawn({ type: "coordinator", name: "Lead" }),
  mcp__claude - flow__agent_spawn({ type: "researcher", name: "Analyst" }),
  mcp__claude - flow__agent_spawn({ type: "coder", name: "Impl" }),
  mcp__claude - flow__agent_spawn({ type: "tester", name: "QA" }),
]);
(await mcp__claude) -
  flow__task_orchestrate({
    task: "Design → Scaffold → Tests",
    strategy: "adaptive",
    priority: "high",
  });
```

Swarm tools and parameters are documented in the MCP Tools reference. ([GitHub][3])

### B) Blackboard hints and TTLs

```ts
(await mcp__claude) -
  flow__memory_usage({
    action: "store",
    key: "coord/hints",
    value: JSON.stringify({ next: "PRD then routes then tests" }),
    namespace: "shared",
    ttl: 1800,
  });
```

`shared_state` and `events` are the blackboard and audit trail. ([GitHub][2])

### C) Light consensus for critical merges

```ts
(await mcp__claude) -
  flow__memory_usage({
    action: "store",
    key: "consensus:auth_api:v3",
    value: JSON.stringify({ decision: "merge", votes: ["Lead", "Impl", "QA"] }),
    namespace: "consensus",
  });
```

`consensus_state` records versions, proposers, and acceptors. ([GitHub][2])

### D) Monitor and adjust

```ts
(await mcp__claude) - flow__performance_report({ format: "summary", timeframe: "24h" });
(await mcp__claude) - flow__topology_optimize({});
```

Use telemetry to trim bundles, rebalance agents, or change topology. ([GitHub][3])

---

## 7) Concurrency and performance design

- **Session forking** to spawn many agents fast.
- **Hook matchers** to run only the smallest necessary hooks.
- **In‑process MCP** for near zero IPC overhead on local tools.
  The README details speedups from these features. Enable WAL mode if you see SQLite lock contention. ([GitHub][1])

**Hot path checklist**

1. Keep PreToolUse bundles under a few kilobytes and top‑5 artifacts only
2. Use TTL on `shared` hints and sweep expired keys in maintenance jobs
3. Batch writes in transactions during heavy phases
4. Emit `events` for every state transition to make replays deterministic ([GitHub][2])

---

## 8) Swarm vs Hive‑Mind for long horizon work

- **Swarm**: quick tasks, minimal setup.
- **Hive‑Mind**: persistent sessions, resume capability, project namespaces.
  The README includes a decision table for both modes and commands for resume. ([GitHub][1])

**Long horizon pattern**

- Checkpoint each stage to `workflow_state`
- Summarize and persist on `SessionEnd`
- On `SessionStart`, rehydrate from session id, then curate a minimal bundle for the next stage. ([GitHub][2])

---

## 9) Planning loops: GOAP and OODA for agent strategy

**GOAP**: express goals, actions, and preconditions, then let a planner sequence actions. Claude Flow exposes a Goal Module and A\* planning in its docs. ([GitHub][7])

**OODA**: Observe, Orient, Decide, Act. Map to Flow like this:

- Observe: query `events`, `performance_metrics`, and recent artifacts
- Orient: reduce to a bundle and compare to `patterns`
- Decide: write a candidate record into `consensus_state` and gate on votes
- Act: `task_orchestrate` and record an `event`

For background on GOAP and OODA, see Orkin’s FEAR paper and standard OODA references. ([GameDevs][8])

---

## 10) Memory engineering details

**Tables that matter most**

- `memory_store` for KV with namespaces and TTL
- `shared_state` and `events` for coordination
- `patterns` for reusable rules and tactics
- `workflow_state` and `sessions` for crash‑safe resumes
- `consensus_state` for approvals and quorum checkpoints ([GitHub][2])

**Maintenance**

- Enable WAL for concurrent reads then run periodic `optimize`, `reindex`, and `VACUUM`. The wiki shows WAL PRAGMA and optimization snippets. ([GitHub][2])

**Safety**

- Do not store raw secrets in memory. Prefer references to a vault and mask values in hooks.
- Use namespaces: `artifacts`, `shared`, `patterns`, `events`, `consensus`, `metrics`. ([GitHub][2])

---

## 11) Artifact‑centric workflow

1. Generate or open an Artifact in Claude
2. Store a manifest in `artifacts` namespace with `id`, `kind`, `tags`, `sha256`
3. Agents reference the manifest id rather than copying large text
   Artifacts live in a dedicated panel and are built to hold substantial content. ([Anthropic][5])

**Manifest example**

```ts
(await mcp__claude) -
  flow__memory_usage({
    action: "store",
    key: "artifact:prd-auth-v3",
    value: JSON.stringify({
      kind: "doc",
      path: "/docs/prd-auth-v3.md",
      sha256: "...",
      tags: ["auth", "prd"],
    }),
    namespace: "artifacts",
  });
```

([GitHub][3])

---

## 12) Automation and hooks

**Project hooks** in `.claude/settings.json`:

- `PreToolUse`: assemble context bundle, deny risky commands, enforce TTL rules
- `PostToolUse`: persist decisions to `events`, learn `patterns`, checkpoint `workflow_state`
- `SessionStart` and `SessionEnd`: resume and summarize

Hook configuration and examples are in Claude Code docs. ([Claude Docs][4])

---

## 13) End‑to‑end recipe: parallel implementation with consensus

```ts
// 1) Start and staff swarm
(await mcp__claude) - flow__swarm_init({ topology: "mesh", maxAgents: 10 });
const [lead, impl, qa] = await Promise.all([
  mcp__claude - flow__agent_spawn({ type: "coordinator", name: "Lead" }),
  mcp__claude - flow__agent_spawn({ type: "coder", name: "Impl" }),
  mcp__claude - flow__agent_spawn({ type: "tester", name: "QA" }),
]);

// 2) PreToolUse hook builds small bundle from artifacts
// 3) Publish hints to shared blackboard
(await mcp__claude) -
  flow__memory_usage({
    action: "store",
    key: "coord/current",
    value: "PRD → routes → tests",
    namespace: "shared",
    ttl: 1800,
  });

// 4) Orchestrate parallel tasks
(await mcp__claude) -
  flow__task_orchestrate({
    task: "Design routes, implement handlers, write tests",
    strategy: "parallel",
    priority: "high",
  });

// 5) Gate release behind consensus vote
(await mcp__claude) -
  flow__memory_usage({
    action: "store",
    key: "consensus:release:v3",
    value: JSON.stringify({ decision: "approve", votes: ["Lead", "Impl", "QA"] }),
    namespace: "consensus",
  });

// 6) PostToolUse: record outcome, learn pattern, checkpoint
(await mcp__claude) -
  flow__memory_usage({
    action: "store",
    key: "events:last",
    value: JSON.stringify({ task: "auth", status: "complete" }),
    namespace: "events",
  });
(await mcp__claude) -
  flow__memory_usage({
    action: "store",
    key: "pattern:scaffold:auth",
    value: JSON.stringify({ steps: ["routes", "handlers", "tests"], confidence: 0.92 }),
    namespace: "patterns",
  });
(await mcp__claude) -
  flow__memory_usage({
    action: "store",
    key: "workflow:auth:v3",
    value: JSON.stringify({ step: "done", sha: "abc123" }),
    namespace: "workflow_state",
  });
```

All tool names and parameters are from the MCP Tools wiki. ([GitHub][3])

---

## 14) Long‑horizon processes

- **Rolling checkpoints**: write compact diffs into `workflow_state` after each stage
- **Session resume**: use `hive-mind resume` to continue exactly where you left off
- **Periodic groom**: sweep expired `shared` keys, archive cold `events` to files, and run `optimize`
- **Weekly verification**: run evaluators and write results to `performance_metrics` then prune patterns with low confidence ([GitHub][1])

---

## 15) Advanced designs and call‑outs

**Design 1: Coordinator with bounded context**

- Coordinator reads only a top‑K bundle and delegates specialized sub‑tasks
- Sub‑agents attach micro‑summaries to `events` and update `patterns`
- Coordinator composes a final Artifact and requests consensus before merge ([GitHub][3])

**Design 2: Adaptive topology**

- Start hierarchical for clarity
- Switch to mesh under high parallelism using `topology_optimize`
- Fall back to ring or star if lock contention appears in memory ([GitHub][3])

**Pitfalls**

- Oversized context slows everything. Use bundles and artifacts.
- Namespace collisions create confusing reads. Adopt a naming policy and a deny‑list in hooks.
- Cleartext secrets in SQLite. Use a secret manager and store only references. ([GitHub][2])

---

## 16) Metrics and benchmarking

- **Live ops**: `performance_report`, `agent_metrics`, `swarm_status`
- **Bench**: `swarm-bench` including SWE‑bench integration for reproducible evals in CI
- Track P50 and P99 memory ops, session resume success rate, and consensus latency. ([GitHub][3])

---

## 17) Templates you can drop in

**Namespace policy**

```
artifacts: manifests only, TTL=0
shared: coordination hints, TTL=1800
patterns: reusable tactics, TTL=604800
events: audit trail, TTL=2592000
workflow_state: checkpoints, TTL=0
consensus: approvals and votes, TTL=604800
```

Aligns with defined tables and usage. ([GitHub][2])

**Hook skeleton**

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "command": "node",
        "args": ["scripts/build_bundle.js"],
        "alwaysRun": true
      }
    ],
    "PostToolUse": [
      {
        "command": "node",
        "args": ["scripts/persist_outcomes.js"],
        "alwaysRun": true
      }
    ],
    "SessionStart": [{ "command": "node", "args": ["scripts/session_start.js"] }],
    "SessionEnd": [{ "command": "node", "args": ["scripts/session_end.js"] }]
  }
}
```

Hook event names and configuration are per Claude Code docs. ([Claude Docs][4])

**GOAP micro‑domain**

```ts
const goals = [{ id: "ship_auth", cost: 1 }];
const actions = [
  { id: "write_prd", pre: [], add: ["prd_ready"] },
  { id: "scaffold_routes", pre: ["prd_ready"], add: ["routes_ready"] },
  { id: "write_tests", pre: ["routes_ready"], add: ["tests_ready"] },
  { id: "merge", pre: ["tests_ready"], add: ["shipped"] },
];
```

Use the Goal Module for initialization and planning. ([GitHub][7])

**OODA mapping**

```
Observe: query events + metrics
Orient: build bundle + lookup patterns
Decide: write consensus_state entry and wait for quorum
Act: orchestrate task and record event
```

Background references on OODA provided. ([Wikipedia][9])

---

## 18) Governance and enterprise posture

- Use **Claude Code managed policy settings** to control tool access and MCP servers at enterprise scope. ([TechRadar][10])
- Keep `.swarm/` and `.hive-mind/` restricted and encrypted at the OS level.
- Treat `credentials` namespace as references only.
- Enforce TTLs and retention in hooks. Audit with `events` and scheduled exports. ([GitHub][2])

---

## 19) Quick reference commands

```bash
# Choose a mode
npx claude-flow@alpha swarm "build REST API"
npx claude-flow@alpha hive-mind spawn "auth-system" --namespace auth

# Memory inspection
npx claude-flow@alpha memory stats
npx claude-flow@alpha memory list
npx claude-flow@alpha memory query "auth*"

# Orchestration and scaling
mcp__claude-flow__swarm_init({ topology:"mesh", maxAgents:12 })
mcp__claude-flow__topology_optimize({})

# Performance
mcp__claude-flow__performance_report({ format:"summary", timeframe:"24h" })
```

Commands and tools come from the README and MCP Tools reference. ([GitHub][1])

---

## 20) 10‑minute validation drill

1. Init, add MCP, and run `memory stats`
2. Spawn 3 agents, store a `shared` hint, run `task_orchestrate`
3. Write a `consensus:*` key and verify gate logic in hooks
4. Create an Artifact and persist a manifest in `artifacts`
5. Run `performance_report` and shrink the bundle until P99 drops below target ([GitHub][3])

---

## 21) Executive call‑outs

- Adopt **artifact‑first** outputs with **manifest memory**
- Keep **context small** and **state durable**
- Use **consensus gates** for deployments
- Treat **telemetry** as input to reduce context and rebalance concurrency ([Anthropic][5])

---

## 22) Review and refinement

**Score 1‑5**

1. Context bundle size and hit rate
2. Session resume success
3. Consensus latency on critical merges
4. P50 and P99 tool latency with in‑process MCP
5. Pattern reuse rate and defect escape rate

Run weekly, track in `performance_metrics`, prune low‑value patterns, and adjust topology. ([GitHub][2])

---

### References

- **Claude Flow repository**: features, swarm vs hive‑mind, session forking, hook matchers, in‑process MCP, quick start commands. ([GitHub][1])
- **Memory System wiki**: `.swarm/memory.db`, 12‑table schema, usage, performance tips. ([GitHub][2])
- **MCP Tools wiki**: tool names, parameters, examples, performance reporting, topology optimization. ([GitHub][3])
- **Claude Code docs**: MCP integration and hook events with configuration examples. ([Claude Docs][6])
- **Artifacts**: product overview and usage guidance. ([Anthropic][5])
- **Model Context Protocol**: protocol standard and client tutorial. ([Model Context Protocol][11])
- **GOAP and OODA**: Orkin’s FEAR planning paper and OODA references. ([GameDevs][8])

---

[1]: https://github.com/ruvnet/claude-flow "GitHub - ruvnet/claude-flow:  The leading agent orchestration platform for Claude. Deploy intelligent multi-agent swarms, coordinate autonomous workflows, and build conversational AI systems. Features    enterprise-grade architecture, distributed swarm intelligence, RAG integration, and native Claude Code support via MCP protocol. Ranked #1 in agent-based frameworks."
[2]: https://github.com/ruvnet/claude-flow/wiki/Memory-System "Memory System · ruvnet/claude-flow Wiki · GitHub"
[3]: https://github.com/ruvnet/claude-flow/wiki/MCP-Tools "MCP Tools · ruvnet/claude-flow Wiki · GitHub"
[4]: https://docs.claude.com/en/docs/claude-code/hooks?utm_source=chatgpt.com "Hooks reference"
[5]: https://www.anthropic.com/news/build-artifacts?utm_source=chatgpt.com "Create AI-Powered Apps with Claude Artifacts"
[6]: https://docs.claude.com/en/docs/claude-code/mcp?utm_source=chatgpt.com "Connect Claude Code to tools via MCP"
[7]: https://github.com/ruvnet/claude-flow/wiki/memory-usage "Home · ruvnet/claude-flow Wiki · GitHub"
[8]: https://www.gamedevs.org/uploads/three-states-plan-ai-of-fear.pdf?utm_source=chatgpt.com "Three States and a Plan: The A.I. of F.E.A.R."
[9]: https://en.wikipedia.org/wiki/OODA_loop?utm_source=chatgpt.com "OODA loop"
[10]: https://www.techradar.com/pro/anthropic-is-adding-claude-code-to-business-plans-so-now-all-your-workers-can-enjoy-a-major-ai-boost?utm_source=chatgpt.com "Anthropic is adding Claude Code to business plans - so now all your workers can enjoy a major AI boost"
[11]: https://modelcontextprotocol.io/?utm_source=chatgpt.com "Model Context Protocol"
