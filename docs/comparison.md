# How OpenClaw Compares

## Feature Matrix

| Capability | OpenClaw | Devin | Cursor | Windsurf | Manus | OpenHands | CrewAI |
|---|---|---|---|---|---|---|---|
| Multi-agent routing | Yes | No | No | No | Partial | No | Yes |
| Phase-gated pipeline | Yes | Partial | No | No | Yes | No | No |
| LLM-as-Judge | Yes | No | No | No | No | No | No |
| Knowledge graph | Yes | No | No | No | No | No | No |
| Streaming (SSE) | Yes | Yes | No | Partial | Yes | No | No |
| OTEL-style tracing | Yes | No | No | No | No | No | No |
| DAG parallel execution | Yes | No | No | No | No | No | No |
| Self-hosted | Yes | No | No | No | No | Yes | Yes |
| Open source | Yes | No | No | No | No | Yes | Yes |

## Design Takeaways

- From Devin: phase-oriented execution
- From Cursor: fast code editing ergonomics
- From Windsurf: live execution feedback loops
- From Manus: planner + executor separation
- From OpenHands: self-repair patterns

## Cost Framing

OpenClaw emphasizes model-tier routing so simple tasks run on cheaper models while complex work escalates automatically.
