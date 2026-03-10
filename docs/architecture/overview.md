# Architecture Overview

OpenClaw is a FastAPI-based orchestration gateway with modular routers, a multi-phase execution pipeline, real-time stream events, tracing, and quality evaluation.

```mermaid
graph TD
    A[Client] --> B[FastAPI Gateway]
    B --> C[Routers]
    C --> D[Autonomous Runner]
    D --> E[Phase Pipeline]
    E --> F[Tool Calls]
    E --> G[Judge]
    E --> H[Knowledge Graph]
    E --> I[Tracing]
    E --> J[Streaming]
```

## Main Components

- Gateway shell: `gateway.py`
- Routers: `routers/*.py`
- Event engine: `event_engine.py`
- Streaming: `streaming.py`
- Tracing: `otel_tracer.py`
- Quality judge: `llm_judge.py`
- Knowledge graph: `kg_engine.py`
