# LLM-as-Judge Evaluation

OpenClaw can score completed jobs against weighted rubric dimensions and persist quality artifacts per run.

## Data Flow

```mermaid
flowchart LR
    A[Completed Job] --> B[Judge Input Builder]
    B --> C[Model Evaluation]
    C --> D[Weighted Scoring]
    D --> E[quality_score.json]
    E --> F[/api/analytics/quality/{job_id}]
```

## API Reference

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/analytics/quality/{job_id}` | GET | fetch quality score |

## Python Client

```python
import requests

score = requests.get("http://localhost:18789/api/analytics/quality/job-123").json()
print(score)
```

## Architecture Notes

- Judge initialized during gateway startup
- Score file stored under `data/jobs/runs/<job_id>/quality_score.json`
- Supports confidence-aware pass/fail gating
