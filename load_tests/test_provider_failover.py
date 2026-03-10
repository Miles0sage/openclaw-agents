import os

from .common import TestResult


def run_provider_failover_simulation() -> TestResult:
  """
  Placeholder for the "fake API key -> breaker -> fallback" test.

  This is intentionally opt-in because it mutates provider config and can burn credits.
  Set OPENCLAW_ENABLE_PROVIDER_FAILOVER_TEST=1 to run once you have a safe noop job type.
  """
  if os.getenv("OPENCLAW_ENABLE_PROVIDER_FAILOVER_TEST") != "1":
    return TestResult(
      name="LLM provider outage simulation",
      passed=False,
      notes="Opt-in only (set OPENCLAW_ENABLE_PROVIDER_FAILOVER_TEST=1).",
      metrics={"skipped": True},
    )

  return TestResult(
    name="LLM provider outage simulation",
    passed=False,
    notes="Not implemented yet: needs safe provider toggle + noop job that exercises provider selection.",
    metrics={"skipped": True},
  )

