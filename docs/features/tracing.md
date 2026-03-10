# Observability and Tracing

OpenClaw records hierarchical spans for jobs, phases, and tool calls using an OTEL-inspired local tracer implementation.

## Data Flow

```mermaid
flowchart LR
    A[Job Start] --> B[Root Span]
    B --> C[Phase Span]
    C --> D[Tool Span]
    D --> E[Trace Store]
    E --> F[/api/analytics/traces/*]
```

## API Reference

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/analytics/traces/recent?limit=` | GET | recent trace summaries |
| `/api/analytics/traces/{trace_id}` | GET | full span graph |

## Python Client

```python
import requests

summaries = requests.get("http://localhost:18789/api/analytics/traces/recent", params={"limit": 10}).json()
trace_id = summaries["traces"][0]["trace_id"]
trace = requests.get(f"http://localhost:18789/api/analytics/traces/{trace_id}").json()
print(trace["summary"])
```

## Architecture Notes

- Tracer initialized in `gateway.py` lifecycle
- Spans include status, duration, parent id, and attributes
- Useful for latency and failure diagnosis
