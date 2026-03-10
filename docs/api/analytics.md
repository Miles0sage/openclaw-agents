# Analytics API

All analytics endpoints are under `/api/analytics`.

## Endpoint Matrix (11)

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/analytics/agents` | GET | agent performance stats |
| `/api/analytics/costs` | GET | cost breakdown |
| `/api/analytics/jobs` | GET | recent jobs with filters |
| `/api/analytics/stream/{job_id}` | GET | live SSE stream |
| `/api/analytics/traces/recent?limit=` | GET | recent traces |
| `/api/analytics/traces/{trace_id}` | GET | full trace |
| `/api/analytics/kg/summary` | GET | knowledge graph summary |
| `/api/analytics/kg/recommend?agent=&task_type=&limit=` | GET | recommended tool chains |
| `/api/analytics/kg/tools?limit=` | GET | tool usage stats |
| `/api/analytics/kg/agent/{agent_key}?task_type=` | GET | agent performance |
| `/api/analytics/quality/{job_id}` | GET | quality score |

## Example Queries

```bash
curl "http://localhost:18789/api/analytics/traces/recent?limit=20"
curl "http://localhost:18789/api/analytics/kg/recommend?agent=coder_agent&task_type=bug_fix&limit=5"
curl "http://localhost:18789/api/analytics/quality/job-abc123"
```

## Example Responses

```json
{
  "agent_stats": {
    "coder_agent": {
      "jobs": 41,
      "success": 37,
      "failed": 4,
      "total_cost": 2.1492,
      "total_duration": 1843.6,
      "success_rate": 90.2,
      "avg_duration": 44.97,
      "avg_cost": 0.0524
    }
  },
  "timestamp": "2026-03-08T23:40:12.000000+00:00"
}
```

```json
{
  "job_id": "job-abc123",
  "overall_score": 0.87,
  "passed": true,
  "dimensions": [
    {
      "dimension": "correctness",
      "score": 0.95,
      "weight": 3.0
    }
  ]
}
```

## Python Example

```python
import requests

base = "http://localhost:18789/api/analytics"
print(requests.get(f"{base}/agents").json())
print(requests.get(f"{base}/costs").json())
print(requests.get(f"{base}/jobs", params={"limit": 50}).json())
```
