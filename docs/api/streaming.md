# Streaming API

OpenClaw uses Server-Sent Events (SSE) for live job progress.

## Endpoint

| Endpoint | Method | Content-Type |
|---|---|---|
| `/api/analytics/stream/{job_id}` | GET | `text/event-stream` |

## Event Types

| Event | Description |
|---|---|
| `phase_change` | pipeline moved to a new phase |
| `tool_call` | tool invocation started |
| `tool_result` | tool invocation finished |
| `progress` | incremental progress update |
| `error` | non-fatal or fatal runtime issue |
| `complete` | job completed |

## JS Example

```javascript
const es = new EventSource("/api/analytics/stream/job-123");
es.addEventListener("phase_change", (e) => console.log(JSON.parse(e.data)));
es.addEventListener("complete", () => es.close());
```

## cURL Example

```bash
curl -N http://localhost:18789/api/analytics/stream/job-123
```
