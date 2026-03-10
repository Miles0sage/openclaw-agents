import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow running as a script: `python3 load_tests/run_all.py`
if __package__ is None or __package__ == "":
  import sys
  sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from load_tests.common import DEFAULT_GATEWAY, TestResult
from load_tests.test_concurrent_submissions import run_concurrent_submissions
from load_tests.test_lease_race_condition import run_lease_race_condition
from load_tests.test_crash_recovery_under_load import run_crash_recovery_under_load
from load_tests.test_rate_limits import run_rate_limit_enforcement
from load_tests.test_provider_failover import run_provider_failover_simulation
from load_tests.test_memory_cost_leak import run_memory_cost_leak_checks
from load_tests.test_health_rps import run_health_rps


def emoji(passed: bool, skipped: bool = False) -> str:
  if skipped:
    return "⏭️"
  return "✅" if passed else "❌"


def is_skipped(tr: TestResult) -> bool:
  return bool(tr.metrics.get("skipped"))


def severity_findings(results: list[TestResult]) -> list[dict[str, str]]:
  findings: list[dict[str, str]] = []
  for r in results:
    if is_skipped(r):
      continue
    if r.name == "Job lease race condition" and not r.passed:
      findings.append({
        "sev": "CRITICAL",
        "desc": "Job lease race allows double execution",
        "evidence": str(r.metrics),
        "fix": "Investigate Supabase lease update filters in `job_lease.acquire_lease` and add API-level idempotency + 409 on duplicate acquisition.",
      })
    if r.name == "Concurrent job submission" and not r.passed:
      findings.append({
        "sev": "HIGH",
        "desc": "Concurrent submissions show errors/timeouts",
        "evidence": str(r.metrics),
        "fix": "Add request timeouts/backpressure, tune worker concurrency, and ensure `/api/job/create` is lightweight.",
      })
    if r.name == "Raw request handling (/health)" and not r.passed:
      findings.append({
        "sev": "MEDIUM",
        "desc": "Gateway p99 latency or error rate under raw load is high",
        "evidence": str(r.metrics),
        "fix": "Profile gateway middleware, enable caching, and scale instances / add rate limiting.",
      })
    if r.name == "Memory + cost leak checks" and not r.passed:
      findings.append({
        "sev": "HIGH",
        "desc": "Orphaned running jobs / expired leases detected",
        "evidence": str(r.metrics),
        "fix": "Run `reclaim_stale_leases` on startup/cron and ensure lease heartbeat is reliable; add monitoring alerts.",
      })
  if not findings:
    # Per task: if it's perfect, re-check assumptions.
    findings.append({
      "sev": "MEDIUM",
      "desc": "No issues detected — verify assumptions and increase realism",
      "evidence": "All executed tests passed or were skipped. This may indicate the tests were too shallow or ran against mocks.",
      "fix": "Increase N, run with real Supabase + workers, and enable crash recovery + provider failover tests.",
    })
  return findings


def readiness_label(findings: list[dict[str, str]]) -> str:
  if any(f["sev"] == "CRITICAL" for f in findings):
    return "FAIL"
  if any(f["sev"] in ("HIGH", "MEDIUM") for f in findings):
    return "CONDITIONAL"
  return "PASS"


def md_escape(s: str) -> str:
  return s.replace("\n", " ").replace("|", "\\|")


async def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--gateway", default=DEFAULT_GATEWAY)
  ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "docs" / "SCALE_READINESS_REPORT.md"))
  args = ap.parse_args()

  gateway = args.gateway.rstrip("/")

  results: list[TestResult] = []
  results.append(await run_concurrent_submissions(gateway=gateway))
  results.append(await run_health_rps(gateway=gateway, rps=100, seconds=10))
  results.append(await run_lease_race_condition())
  results.append(run_crash_recovery_under_load(gateway=gateway))
  results.append(run_rate_limit_enforcement(gateway=gateway))
  results.append(run_provider_failover_simulation())
  results.append(run_memory_cost_leak_checks())

  findings = severity_findings(results)
  ready = readiness_label(findings)

  # Load numbers: try to extract from concurrent submissions if present.
  max_safe = None
  p50_submit = None
  p99_submit = None
  conc = next((r for r in results if r.name == "Concurrent job submission"), None)
  if conc and isinstance(conc.metrics, dict):
    levels = conc.metrics.get("levels") or []
    try:
      # "max safe" is the highest N where we saw no 5xx/transport errs and >=90% accepted.
      safe_ns = []
      for l in levels:
        if l.get("server_err") == 0 and l.get("transport_err") == 0 and l.get("accepted", 0) >= int(l.get("n", 0) * 0.9):
          safe_ns.append(l.get("n"))
      if safe_ns:
        max_safe = max(safe_ns)
      # Use the largest level for latency summary.
      if levels:
        largest = sorted(levels, key=lambda x: x.get("n", 0))[-1]
        p50_submit = (largest.get("latency") or {}).get("p50_ms")
        p99_submit = (largest.get("latency") or {}).get("p99_ms")
    except Exception:
      pass

  out_path = Path(args.out)
  out_path.parent.mkdir(parents=True, exist_ok=True)

  lines: list[str] = []
  lines.append("# OpenClaw Scale Readiness Report")
  lines.append(f"Date: {datetime.now(timezone.utc).isoformat()}")
  lines.append(f"Gateway: {gateway}")
  lines.append("")
  lines.append("## Executive Summary")
  lines.append(f"**{ready}** — Ready for external API traffic?")
  lines.append("")
  lines.append("## Test Results")
  lines.append("")
  lines.append("| Test | Passed | Notes |")
  lines.append("|---|---|---|")
  for r in results:
    lines.append(f"| {md_escape(r.name)} | {emoji(r.passed, is_skipped(r))} | {md_escape(r.notes)} |")
  lines.append("")
  lines.append("## Bottlenecks Found")
  lines.append("")
  for i, f in enumerate(findings, 1):
    lines.append(f"{i}. **{f['sev']}** — {f['desc']}  ")
    lines.append(f"   - Evidence: `{md_escape(f['evidence'])}`  ")
    lines.append(f"   - Recommended fix: {f['fix']}")
  lines.append("")
  lines.append("## Recommended Fixes Before Launch (Priority Order)")
  lines.append("")
  for f in findings:
    if f["sev"] in ("CRITICAL", "HIGH"):
      lines.append(f"1. [{f['sev']}] {f['desc']} — {f['fix']}")
  if not any(f["sev"] in ("CRITICAL", "HIGH") for f in findings):
    lines.append("1. No CRITICAL/HIGH findings from executed tests; enable opt-in tests and increase realism.")
  lines.append("")
  lines.append("## What Can Wait Until After Launch")
  lines.append("")
  lines.append("1. Provider failover simulation (once safe noop job can exercise provider chain)")
  lines.append("2. Full crash-recovery under load automation (requires systemctl in CI / staging)")
  lines.append("")
  lines.append("## Load Numbers")
  lines.append("")
  lines.append(f"- Max safe concurrent jobs (observed): {max_safe if max_safe is not None else '—'}")
  lines.append(f"- p50 job submission latency: {f'{p50_submit:.1f}ms' if isinstance(p50_submit, (int, float)) else '—'}")
  lines.append(f"- p99 job submission latency: {f'{p99_submit:.1f}ms' if isinstance(p99_submit, (int, float)) else '—'}")
  lines.append("")
  lines.append("## Raw JSON (per-test metrics)")
  lines.append("")
  lines.append("```json")
  import json  # inline to keep top imports clean
  lines.append(json.dumps([r.__dict__ for r in results], indent=2))
  lines.append("```")
  lines.append("")

  out_path.write_text("\n".join(lines), encoding="utf-8")
  print(f"[OK] Wrote {out_path}")


if __name__ == "__main__":
  import asyncio
  asyncio.run(main())

