import os
import time

from .common import DEFAULT_GATEWAY, TestResult, gateway_reachable


def run_crash_recovery_under_load(gateway: str = DEFAULT_GATEWAY) -> TestResult:
  """
  This test involves systemctl stop/start, so it's opt-in.
  """
  if not gateway_reachable(gateway):
    return TestResult(
      name="Crash recovery under load",
      passed=False,
      notes=f"Gateway not reachable at {gateway} (skipped).",
      metrics={"gateway": gateway, "skipped": True},
    )

  if os.getenv("OPENCLAW_ENABLE_CRASH_RECOVERY_TEST") != "1":
    return TestResult(
      name="Crash recovery under load",
      passed=False,
      notes="Opt-in only (set OPENCLAW_ENABLE_CRASH_RECOVERY_TEST=1). Requires systemctl access.",
      metrics={"skipped": True},
    )

  # We avoid running systemctl automatically in this environment.
  instructions = [
    "1) Submit 5 jobs and wait until they are running",
    "2) Stop gateway: systemctl stop openclaw-gateway",
    "3) Start gateway: systemctl start openclaw-gateway",
    "4) Verify those jobs resume and no duplicates appear",
  ]
  time.sleep(0.1)
  return TestResult(
    name="Crash recovery under load",
    passed=False,
    notes="Manual steps required; see metrics.instructions.",
    metrics={"instructions": instructions, "skipped": True},
  )

