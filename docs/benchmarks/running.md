# Running Benchmarks

Use the local benchmark task definitions under `tasks/` and evaluation routes to compare model and agent strategies.

## Typical Flow

```bash
# Trigger benchmark/eval run
curl -X POST http://localhost:18789/api/eval/run \
  -H "Content-Type: application/json" \
  -d '{"suite": "coding-core", "model": "kimi-2.5"}'

# Fetch run results
curl http://localhost:18789/api/eval/results
```

## Recommendations

- Keep deterministic prompts for comparable runs
- Record model, temperature, and tool profile per run
- Compare easy/medium/hard partitions separately
