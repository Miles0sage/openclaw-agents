import asyncio
from typing import Any

import httpx

from .common import DEFAULT_GATEWAY, TestResult, headers, now_ms, summarize_latencies_ms, gateway_reachable


async def _submit_one(client: httpx.AsyncClient, gateway: str, payload: dict[str, Any]) -> tuple[int | None, float | None, str | None, dict[str, Any] | None]:
  t0 = now_ms()
  try:
    resp = await client.post(f"{gateway}/api/job/create", json=payload, headers=headers(), timeout=10)
    dt = now_ms() - t0
    try:
      body = resp.json()
    except Exception:
      body = None
    job_id = body.get("job_id") if isinstance(body, dict) else None
    return resp.status_code, dt, job_id, body
  except Exception as e:
    return None, None, None, {"error": str(e)}


async def run_concurrent_submissions(levels: list[int] = [5, 10, 25, 50], gateway: str = DEFAULT_GATEWAY) -> TestResult:
  if not gateway_reachable(gateway):
    return TestResult(
      name="Concurrent job submission",
      passed=False,
      notes=f"Gateway not reachable at {gateway} (skipped).",
      metrics={"gateway": gateway, "skipped": True},
    )

  results: dict[str, Any] = {"gateway": gateway, "levels": []}
  overall_ok = True

  async with httpx.AsyncClient() as client:
    for n in levels:
      payloads = [
        {
          "project": "openclaw",
          "task": f"antigravity noop load test {n}-{i}",
          "priority": "P2",
          "pool": "p2",
          "task_type": "test_noop",
        }
        for i in range(n)
      ]
      tasks = [_submit_one(client, gateway, p) for p in payloads]
      res = await asyncio.gather(*tasks, return_exceptions=False)

      statuses = [r[0] for r in res]
      lat_ms = [r[1] for r in res if r[1] is not None]
      job_ids = [r[2] for r in res if r[2]]

      accepted = sum(1 for s in statuses if s in (200, 201))
      rejected = sum(1 for s in statuses if s in (429, 409, 400, 401, 422))
      server_err = sum(1 for s in statuses if s is not None and s >= 500)
      transport_err = sum(1 for s in statuses if s is None)
      dup = len(job_ids) - len(set(job_ids))

      level_metrics = {
        "n": n,
        "accepted": accepted,
        "rejected": rejected,
        "server_err": server_err,
        "transport_err": transport_err,
        "duplicate_job_ids": dup,
        "latency": summarize_latencies_ms(lat_ms),
      }
      results["levels"].append(level_metrics)

      # Conservative pass criteria: no transport errors, no 5xx, no duplicate IDs.
      level_ok = transport_err == 0 and server_err == 0 and dup == 0 and accepted >= max(1, int(n * 0.9))
      overall_ok = overall_ok and level_ok

  notes = "All levels accepted without 5xx/timeouts." if overall_ok else "Some levels had errors/timeouts/rejections; see metrics."
  return TestResult(name="Concurrent job submission", passed=overall_ok, notes=notes, metrics=results)

