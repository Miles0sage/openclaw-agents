# Configuration

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `PORT` | Gateway port | `18789` |
| `OPENCLAW_DATA_DIR` | Data root for events/jobs/traces | `./data` |
| `GATEWAY_AUTH_TOKEN` | Required auth token for protected routes | none |
| `OPENCLAW_MODEL_PROVIDER` | Model provider selector | provider-specific |
| `OPENCLAW_STREAMING` | Enable/disable streaming subsystem | enabled |
| `OPENCLAW_TRACING` | Enable/disable tracer subsystem | enabled |

## Core Config Files

- `gateway.py`: app bootstrapping, middleware, router wiring
- `routers/shared.py`: shared config and utility access
- `.env`: runtime secret and environment overrides

## Agent and Pipeline Controls

- Agent routing via `routers/intelligent_routing.py`
- Task execution controls in `autonomous_runner.py`
- DAG execution in `dag_executor.py`
- Quality gating in `llm_judge.py`

## Security Notes

- `GATEWAY_AUTH_TOKEN` is mandatory in production
- Restrict CORS origins in production
- Keep API keys in environment, not source
