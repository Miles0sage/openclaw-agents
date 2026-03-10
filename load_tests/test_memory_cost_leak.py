from .common import TestResult


def run_memory_cost_leak_checks() -> TestResult:
  """
  Lightweight DB invariants:
  - no running jobs with expired leases
  - no running jobs without execution_id
  - DLQ unresolved count is readable
  """
  try:
    from supabase_client import table_select, table_count
  except Exception as e:
    return TestResult(
      name="Memory + cost leak checks",
      passed=False,
      notes=f"Supabase client unavailable (skipped): {e}",
      metrics={"skipped": True},
    )

  expired = table_select(
    "jobs",
    "status=eq.running&lease_expires_at=lt.now()&select=id,lease_expires_at,execution_id",
    limit=50,
  )
  running_no_exec = table_select(
    "jobs",
    "status=eq.running&execution_id=is.null&select=id,lease_expires_at,execution_id",
    limit=50,
  )
  dlq_unresolved = table_count("dead_letter_queue", "resolved=is.false")

  passed = len(expired) == 0 and len(running_no_exec) == 0
  notes = "No expired leases and no running jobs missing execution_id." if passed else "Found suspicious running jobs; see metrics."
  return TestResult(
    name="Memory + cost leak checks",
    passed=passed,
    notes=notes,
    metrics={
      "expired_running_jobs_sample": expired,
      "running_missing_execution_id_sample": running_no_exec,
      "dlq_unresolved_count": dlq_unresolved,
    },
  )

