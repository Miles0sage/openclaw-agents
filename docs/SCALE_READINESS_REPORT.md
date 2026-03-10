# OpenClaw Scale Readiness Report
Date: 2026-03-09T08:51:38.487643+00:00
Gateway: http://localhost:18789

## Executive Summary
**CONDITIONAL** — Ready for external API traffic?

## Test Results

| Test | Passed | Notes |
|---|---|---|
| Concurrent job submission | ✅ | All levels accepted without 5xx/timeouts. |
| Raw request handling (/health) | ✅ | OK |
| Job lease race condition | ✅ | Exactly one lease acquired. |
| Crash recovery under load | ⏭️ | Opt-in only (set OPENCLAW_ENABLE_CRASH_RECOVERY_TEST=1). Requires systemctl access. |
| API rate limit enforcement | ⏭️ | Opt-in only (set OPENCLAW_ENABLE_RATE_LIMIT_TEST=1) once API keys are enforced. |
| LLM provider outage simulation | ⏭️ | Opt-in only (set OPENCLAW_ENABLE_PROVIDER_FAILOVER_TEST=1). |
| Memory + cost leak checks | ✅ | No expired leases and no running jobs missing execution_id. |

## Bottlenecks Found

1. **MEDIUM** — No issues detected — verify assumptions and increase realism  
   - Evidence: `All executed tests passed or were skipped. This may indicate the tests were too shallow or ran against mocks.`  
   - Recommended fix: Increase N, run with real Supabase + workers, and enable crash recovery + provider failover tests.

## Recommended Fixes Before Launch (Priority Order)

1. No CRITICAL/HIGH findings from executed tests; enable opt-in tests and increase realism.

## What Can Wait Until After Launch

1. Provider failover simulation (once safe noop job can exercise provider chain)
2. Full crash-recovery under load automation (requires systemctl in CI / staging)

## Load Numbers

- Max safe concurrent jobs (observed): 50
- p50 job submission latency: 1676.6ms
- p99 job submission latency: 3013.5ms

## Raw JSON (per-test metrics)

```json
[
  {
    "name": "Concurrent job submission",
    "passed": true,
    "notes": "All levels accepted without 5xx/timeouts.",
    "metrics": {
      "gateway": "http://localhost:18789",
      "levels": [
        {
          "n": 5,
          "accepted": 5,
          "rejected": 0,
          "server_err": 0,
          "transport_err": 0,
          "duplicate_job_ids": 0,
          "latency": {
            "count": 5,
            "p50_ms": 750.0302562713623,
            "p95_ms": 800.5038418769836,
            "p99_ms": 800.5038418769836,
            "mean_ms": 753.839960861206
          }
        },
        {
          "n": 10,
          "accepted": 10,
          "rejected": 0,
          "server_err": 0,
          "transport_err": 0,
          "duplicate_job_ids": 0,
          "latency": {
            "count": 10,
            "p50_ms": 781.2189321517944,
            "p95_ms": 835.1570949554443,
            "p99_ms": 835.1570949554443,
            "mean_ms": 785.920238494873
          }
        },
        {
          "n": 25,
          "accepted": 25,
          "rejected": 0,
          "server_err": 0,
          "transport_err": 0,
          "duplicate_job_ids": 0,
          "latency": {
            "count": 25,
            "p50_ms": 986.0656628608704,
            "p95_ms": 1544.4876890182495,
            "p99_ms": 1667.800769329071,
            "mean_ms": 1093.3453370666505
          }
        },
        {
          "n": 50,
          "accepted": 50,
          "rejected": 0,
          "server_err": 0,
          "transport_err": 0,
          "duplicate_job_ids": 0,
          "latency": {
            "count": 50,
            "p50_ms": 1676.5612359046936,
            "p95_ms": 2602.206814289093,
            "p99_ms": 3013.5294103622437,
            "mean_ms": 1760.953134355545
          }
        }
      ]
    }
  },
  {
    "name": "Raw request handling (/health)",
    "passed": true,
    "notes": "OK",
    "metrics": {
      "gateway": "http://localhost:18789",
      "rps_target": 100,
      "seconds": 10,
      "requests": 900,
      "ok": 900,
      "bad": 0,
      "transport_err": 0,
      "error_rate": 0.0,
      "latency": {
        "count": 900,
        "p50_ms": 1.626471333503723,
        "p95_ms": 3.5626751661300657,
        "p99_ms": 3.5626751661300657,
        "mean_ms": 1.8202992301517062
      }
    }
  },
  {
    "name": "Job lease race condition",
    "passed": true,
    "notes": "Exactly one lease acquired.",
    "metrics": {
      "job_id": "job-20260309-085136-5d042828",
      "winners": 1
    }
  },
  {
    "name": "Crash recovery under load",
    "passed": false,
    "notes": "Opt-in only (set OPENCLAW_ENABLE_CRASH_RECOVERY_TEST=1). Requires systemctl access.",
    "metrics": {
      "skipped": true
    }
  },
  {
    "name": "API rate limit enforcement",
    "passed": false,
    "notes": "Opt-in only (set OPENCLAW_ENABLE_RATE_LIMIT_TEST=1) once API keys are enforced.",
    "metrics": {
      "skipped": true
    }
  },
  {
    "name": "LLM provider outage simulation",
    "passed": false,
    "notes": "Opt-in only (set OPENCLAW_ENABLE_PROVIDER_FAILOVER_TEST=1).",
    "metrics": {
      "skipped": true
    }
  },
  {
    "name": "Memory + cost leak checks",
    "passed": true,
    "notes": "No expired leases and no running jobs missing execution_id.",
    "metrics": {
      "expired_running_jobs_sample": [],
      "running_missing_execution_id_sample": [],
      "dlq_unresolved_count": 1
    }
  }
]
```
