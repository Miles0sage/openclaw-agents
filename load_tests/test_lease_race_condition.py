import asyncio

from .common import TestResult


async def run_lease_race_condition() -> TestResult:
  """
  Acquire the same lease twice concurrently.
  Expected: exactly one succeeds.
  """
  try:
    from supabase_client import get_client
    from job_manager import create_job
    from job_lease import acquire_lease
  except Exception as e:
    return TestResult(
      name="Job lease race condition",
      passed=False,
      notes=f"Imports failed (skipped): {e}",
      metrics={"skipped": True},
    )

  sb = get_client()
  if sb is None:
    return TestResult(
      name="Job lease race condition",
      passed=False,
      notes="Supabase client unavailable (skipped).",
      metrics={"skipped": True},
    )

  job = create_job("openclaw", "antigravity lease race test", "P2")
  job_id = getattr(job, "id", None)
  if not job_id:
    return TestResult(
      name="Job lease race condition",
      passed=False,
      notes="Failed to create job_id",
      metrics={},
    )

  l1, l2 = await asyncio.gather(acquire_lease(job_id, sb), acquire_lease(job_id, sb))
  wins = sum(1 for x in (l1, l2) if x is not None)

  # Clean up heartbeat tasks.
  for lease in (l1, l2):
    if lease is not None:
      try:
        await lease.release()
      except Exception:
        pass

  passed = wins == 1
  notes = "Exactly one lease acquired." if passed else f"Expected 1 winner, got {wins}."
  return TestResult(
    name="Job lease race condition",
    passed=passed,
    notes=notes,
    metrics={"job_id": job_id, "winners": wins},
  )

