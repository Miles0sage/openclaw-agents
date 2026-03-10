# Benchmark Results

Document result snapshots with cost, latency, and pass-rate by difficulty.

## Suggested Result Schema

| Field | Type | Description |
|---|---|---|
| `run_id` | string | unique evaluation run id |
| `suite` | string | benchmark suite name |
| `model` | string | evaluated model |
| `pass_rate` | number | percent solved |
| `avg_duration_s` | number | average runtime |
| `total_cost_usd` | number | total spend |

## Reporting Template

```json
{
  "run_id": "eval-20260308-001",
  "suite": "coding-core",
  "model": "kimi-2.5",
  "pass_rate": 0.82,
  "avg_duration_s": 31.4,
  "total_cost_usd": 1.27
}
```
