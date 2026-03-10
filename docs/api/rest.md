# REST API

Core OpenClaw HTTP APIs for chat, jobs, routing, and task operations.

## Base URL

`http://localhost:18789`

## Common Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/chat` | POST | chat completion |
| `/api/chat/stream` | POST | streaming chat completion |
| `/api/vision` | POST | vision-enabled chat |
| `/api/route` | POST | intelligent routing decision |
| `/api/route/models` | GET | available routing models |
| `/api/tasks` | GET/POST | list/create agency tasks |
| `/api/tasks/{task_id}` | PATCH | update task status |
| `/api/jobs` | GET | list jobs |
| `/api/jobs/{job_id}/detail` | GET | job details |

## Request Example

```bash
curl -X POST http://localhost:18789/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Summarize this repo architecture."}'
```

## Response Example

```json
{
  "ok": true,
  "response": "OpenClaw is a modular FastAPI gateway with multi-agent orchestration..."
}
```
