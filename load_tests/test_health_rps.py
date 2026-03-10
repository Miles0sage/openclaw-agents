import asyncio
import time

import httpx

from .common import DEFAULT_GATEWAY, TestResult, now_ms, summarize_latencies_ms, gateway_reachable


async def run_health_rps(gateway: str = DEFAULT_GATEWAY, rps: int = 100, seconds: int = 10) -> TestResult:
  """
  Fallback load test when API-key rate limits are not active yet.
  Sends ~rps GETs to /health for `seconds` seconds and reports latency percentiles + error rate.
  """
  if not gateway_reachable(gateway):
    return TestResult(
      name="Raw request handling (/health)",
      passed=False,
      notes=f"Gateway not reachable at {gateway} (skipped).",
      metrics={"gateway": gateway, "skipped": True},
    )

  lat_ms: list[float] = []
  statuses: list[int | None] = []
  end_at = time.time() + seconds

  async with httpx.AsyncClient() as client:
    while time.time() < end_at:
      # Fire a batch each second.
      batch = []
      for _ in range(rps):
        batch.append(client.get(f"{gateway}/health", timeout=5))
      t0 = now_ms()
      res = await asyncio.gather(*batch, return_exceptions=True)
      dt = now_ms() - t0
      per_req = dt / max(1, len(res))
      for r in res:
        if isinstance(r, Exception):
          statuses.append(None)
        else:
          statuses.append(r.status_code)
          lat_ms.append(per_req)
      await asyncio.sleep(1)

  ok = sum(1 for s in statuses if s == 200)
  bad = sum(1 for s in statuses if s not in (None, 200))
  err = sum(1 for s in statuses if s is None)
  total = len(statuses)
  err_rate = (bad + err) / total if total else 1.0

  metrics = {
    "gateway": gateway,
    "rps_target": rps,
    "seconds": seconds,
    "requests": total,
    "ok": ok,
    "bad": bad,
    "transport_err": err,
    "error_rate": err_rate,
    "latency": summarize_latencies_ms(lat_ms),
  }

  passed = err_rate < 0.01 and (metrics["latency"]["p99_ms"] is None or metrics["latency"]["p99_ms"] < 2000)
  notes = "OK" if passed else "High error rate or p99 latency; see metrics."
  return TestResult(name="Raw request handling (/health)", passed=passed, notes=notes, metrics=metrics)

