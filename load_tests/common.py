import os
import time
import statistics
from dataclasses import dataclass
from typing import Any

import httpx


DEFAULT_GATEWAY = os.getenv("OPENCLAW_GATEWAY", "http://localhost:18789").rstrip("/")
DEFAULT_TOKEN = os.getenv("GATEWAY_AUTH_TOKEN", "")


def headers(token: str | None = None) -> dict[str, str]:
  t = token if token is not None else DEFAULT_TOKEN
  h: dict[str, str] = {"Content-Type": "application/json"}
  if t:
    h["X-Auth-Token"] = t
    h["Authorization"] = f"Bearer {t}"
  return h


def now_ms() -> float:
  return time.perf_counter() * 1000.0


def pct(values: list[float], p: float) -> float | None:
  if not values:
    return None
  v = sorted(values)
  idx = int(round(p * (len(v) - 1)))
  idx = max(0, min(idx, len(v) - 1))
  return v[idx]


def summarize_latencies_ms(lat_ms: list[float]) -> dict[str, Any]:
  if not lat_ms:
    return {"count": 0, "p50_ms": None, "p95_ms": None, "p99_ms": None, "mean_ms": None}
  return {
    "count": len(lat_ms),
    "p50_ms": pct(lat_ms, 0.50),
    "p95_ms": pct(lat_ms, 0.95),
    "p99_ms": pct(lat_ms, 0.99),
    "mean_ms": statistics.mean(lat_ms),
  }


@dataclass
class TestResult:
  name: str
  passed: bool
  notes: str
  metrics: dict[str, Any]


def gateway_reachable(gateway: str = DEFAULT_GATEWAY, timeout_s: float = 2.5, retries: int = 8) -> bool:
  import time
  for _ in range(retries):
    try:
      r = httpx.get(f"{gateway}/health", timeout=timeout_s)
      if r.status_code == 200:
        return True
    except Exception:
      pass
    time.sleep(1)
  return False

