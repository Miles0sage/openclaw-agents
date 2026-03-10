# Knowledge Graph

The knowledge graph records tool usage, agent outcomes, and task-type performance for recommendation and optimization.

## Data Flow

```mermaid
flowchart TD
    A[Job Events] --> B[KG Engine]
    B --> C[(SQLite)]
    C --> D[/api/analytics/kg/summary]
    C --> E[/api/analytics/kg/tools]
    C --> F[/api/analytics/kg/recommend]
```

## API Reference

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/analytics/kg/summary` | GET | graph statistics |
| `/api/analytics/kg/tools?limit=` | GET | tool usage stats |
| `/api/analytics/kg/recommend?agent=&task_type=&limit=` | GET | recommended tool chains |
| `/api/analytics/kg/agent/{agent_key}?task_type=` | GET | agent performance profile |

## Python Client

```python
import requests

summary = requests.get("http://localhost:18789/api/analytics/kg/summary").json()
recs = requests.get(
    "http://localhost:18789/api/analytics/kg/recommend",
    params={"agent": "coder_agent", "task_type": "bug_fix", "limit": 5},
).json()
print(summary)
print(recs)
```

## Architecture Notes

- Initialized in `gateway.py` lifecycle
- Drives adaptive tool-chain selection
- Uses local storage, no external graph database required
