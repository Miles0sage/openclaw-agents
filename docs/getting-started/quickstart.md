# Quick Start

## 1. Start Gateway

```bash
cd ./
python gateway.py
```

Default gateway endpoint: `http://localhost:18789`

## 2. Submit a Job

```bash
curl -X POST http://localhost:18789/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Create a Python email validator with tests",
    "department": "engineering",
    "priority": "normal"
  }'
```

## 3. Stream Live Progress

```bash
curl -N http://localhost:18789/api/analytics/stream/<job_id>
```

## 4. Inspect Quality Score

```bash
curl http://localhost:18789/api/analytics/quality/<job_id>
```

## 5. Pull Trace Data

```bash
curl "http://localhost:18789/api/analytics/traces/recent?limit=10"
```

## 6. Get KG Recommendations

```bash
curl "http://localhost:18789/api/analytics/kg/recommend?agent=coder_agent&task_type=bug_fix&limit=5"
```
