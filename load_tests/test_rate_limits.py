import os

from .common import DEFAULT_GATEWAY, TestResult, gateway_reachable


def run_rate_limit_enforcement(gateway: str = DEFAULT_GATEWAY) -> TestResult:
  """
  Placeholder for per-key rate-limit tests.
  This becomes meaningful once the API key system is deployed and enforced for job creation.
  """
  if not gateway_reachable(gateway):
    return TestResult(
      name="API rate limit enforcement",
      passed=False,
      notes=f"Gateway not reachable at {gateway} (skipped).",
      metrics={"gateway": gateway, "skipped": True},
    )

  if os.getenv("OPENCLAW_ENABLE_RATE_LIMIT_TEST") != "1":
    return TestResult(
      name="API rate limit enforcement",
      passed=False,
      notes="Opt-in only (set OPENCLAW_ENABLE_RATE_LIMIT_TEST=1) once API keys are enforced.",
      metrics={"skipped": True},
    )

  return TestResult(
    name="API rate limit enforcement",
    passed=False,
    notes="Not implemented yet: requires two keys + a known limit configured.",
    metrics={"skipped": True},
  )

