"""
Self-Improvement Loop for OpenClaw
====================================
Tracks session outcomes, detects patterns, adjusts guardrails,
and generates weekly retrospectives.

Data stored in:
- data/metrics/agent_performance.jsonl  (per-job metrics)
- data/retrospectives/                   (weekly summaries)
"""

import json
import os
import time
import threading
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, asdict

logger = logging.getLogger("self_improve")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")
METRICS_FILE = os.path.join(DATA_DIR, "metrics", "agent_performance.jsonl")
RETRO_DIR = os.path.join(DATA_DIR, "retrospectives")


@dataclass
class JobMetric:
    """Single job performance record."""
    job_id: str
    project: str
    task: str
    agent: str
    success: bool
    iterations: int
    cost_usd: float
    ci_failures: int = 0
    time_seconds: float = 0.0
    phases_completed: int = 0
    total_phases: int = 5
    error_type: str = ""  # "budget", "guardrail", "timeout", "code_error", ""
    timestamp: str = ""

    def to_dict(self):
        return asdict(self)


class SelfImproveEngine:
    """Tracks performance and generates insights."""

    def __init__(self):
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(METRICS_FILE), exist_ok=True)
        os.makedirs(RETRO_DIR, exist_ok=True)

    def log_job_outcome(self, job_id: str, project: str, task: str, agent: str,
                        success: bool, iterations: int, cost_usd: float,
                        time_seconds: float = 0, ci_failures: int = 0,
                        phases_completed: int = 0, error_type: str = ""):
        """Log a job outcome to the metrics file. Called at end of each job in autonomous_runner.py."""
        metric = JobMetric(
            job_id=job_id, project=project, task=task[:200], agent=agent,
            success=success, iterations=iterations, cost_usd=cost_usd,
            ci_failures=ci_failures, time_seconds=time_seconds,
            phases_completed=phases_completed, error_type=error_type,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        with self._lock:
            with open(METRICS_FILE, "a") as f:
                f.write(json.dumps(metric.to_dict()) + "\n")
        logger.info(f"Logged metric for job {job_id}: success={success}, cost=${cost_usd:.4f}")

    def get_metrics(self, days: int = 7, project: str = None) -> list[dict]:
        """Read metrics from the last N days, optionally filtered by project."""
        metrics = []
        if not os.path.exists(METRICS_FILE):
            return metrics
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with open(METRICS_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    m = json.loads(line)
                    if m.get("timestamp", "") >= cutoff:
                        if project is None or m.get("project") == project:
                            metrics.append(m)
                except json.JSONDecodeError:
                    continue
        return metrics

    def get_summary(self, days: int = 7) -> dict:
        """Get aggregate performance summary for the last N days."""
        metrics = self.get_metrics(days=days)
        if not metrics:
            return {"total_jobs": 0, "period_days": days, "message": "No data yet"}

        total = len(metrics)
        successes = sum(1 for m in metrics if m["success"])
        total_cost = sum(m["cost_usd"] for m in metrics)
        avg_cost = total_cost / total if total else 0
        total_time = sum(m.get("time_seconds", 0) for m in metrics)
        avg_time = total_time / total if total else 0
        avg_iterations = sum(m.get("iterations", 0) for m in metrics) / total if total else 0

        # Per-project breakdown
        by_project = defaultdict(lambda: {"total": 0, "success": 0, "cost": 0.0})
        for m in metrics:
            p = m.get("project", "unknown")
            by_project[p]["total"] += 1
            if m["success"]:
                by_project[p]["success"] += 1
            by_project[p]["cost"] += m["cost_usd"]

        # Per-agent breakdown
        by_agent = defaultdict(lambda: {"total": 0, "success": 0, "cost": 0.0})
        for m in metrics:
            a = m.get("agent", "unknown")
            by_agent[a]["total"] += 1
            if m["success"]:
                by_agent[a]["success"] += 1
            by_agent[a]["cost"] += m["cost_usd"]

        # Error type distribution
        error_types = defaultdict(int)
        for m in metrics:
            if not m["success"] and m.get("error_type"):
                error_types[m["error_type"]] += 1

        return {
            "period_days": days,
            "total_jobs": total,
            "successes": successes,
            "failures": total - successes,
            "success_rate": round(successes / total * 100, 1) if total else 0,
            "total_cost_usd": round(total_cost, 4),
            "avg_cost_usd": round(avg_cost, 4),
            "avg_time_seconds": round(avg_time, 1),
            "avg_iterations": round(avg_iterations, 1),
            "by_project": dict(by_project),
            "by_agent": dict(by_agent),
            "error_types": dict(error_types),
        }

    def get_guardrail_recommendations(self) -> dict:
        """Analyze recent metrics and suggest guardrail adjustments."""
        metrics = self.get_metrics(days=14)
        if len(metrics) < 5:
            return {"message": "Need at least 5 jobs for recommendations", "recommendations": []}

        recommendations = []

        # Per-project analysis
        by_project = defaultdict(list)
        for m in metrics:
            by_project[m.get("project", "unknown")].append(m)

        for project, jobs in by_project.items():
            success_rate = sum(1 for j in jobs if j["success"]) / len(jobs)
            avg_cost = sum(j["cost_usd"] for j in jobs) / len(jobs)
            avg_iters = sum(j.get("iterations", 0) for j in jobs) / len(jobs)

            if success_rate < 0.5 and len(jobs) >= 3:
                recommendations.append({
                    "project": project,
                    "type": "tighten",
                    "reason": f"Low success rate ({success_rate:.0%}) — consider tightening iteration limit or reviewing task complexity",
                    "suggested_max_iterations": max(10, int(avg_iters * 0.8)),
                })
            elif success_rate > 0.9 and avg_iters < 15 and len(jobs) >= 3:
                recommendations.append({
                    "project": project,
                    "type": "loosen",
                    "reason": f"High success rate ({success_rate:.0%}) with low iterations ({avg_iters:.0f} avg) — can safely increase budget",
                    "suggested_max_cost_usd": round(avg_cost * 2, 2),
                })

            # Check for budget-killed jobs
            budget_kills = [j for j in jobs if j.get("error_type") == "budget"]
            if len(budget_kills) >= 2:
                recommendations.append({
                    "project": project,
                    "type": "increase_budget",
                    "reason": f"{len(budget_kills)} jobs killed by budget cap — consider increasing per-job budget",
                })

        return {"recommendations": recommendations, "analyzed_jobs": len(metrics)}

    def generate_retrospective(self) -> dict:
        """Generate a weekly retrospective summary. Saved to data/retrospectives/."""
        summary = self.get_summary(days=7)
        recommendations = self.get_guardrail_recommendations()

        # Auto-apply guardrail recommendations
        applied_changes = []
        try:
            from guardrail_auto_apply import apply_recommendations
            applied_changes = apply_recommendations(recommendations.get("recommendations", []))
            logger.info(f"Auto-applied {len(applied_changes)} guardrail recommendations")
        except ImportError:
            logger.warning("guardrail_auto_apply not available; skipping auto-apply")
        except Exception as e:
            logger.error(f"Error auto-applying recommendations: {e}")

        retro = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "period": "7 days",
            "summary": summary,
            "recommendations": recommendations.get("recommendations", []),
            "applied_changes": [c.to_dict() if hasattr(c, 'to_dict') else c for c in applied_changes],
            "highlights": [],
            "concerns": [],
        }

        # Add highlights and concerns
        if summary.get("success_rate", 0) >= 90:
            retro["highlights"].append(f"Excellent success rate: {summary['success_rate']}%")
        if summary.get("total_cost_usd", 0) < 5.0 and summary.get("total_jobs", 0) > 0:
            retro["highlights"].append(f"Cost-efficient: ${summary['total_cost_usd']:.2f} for {summary['total_jobs']} jobs")

        if summary.get("success_rate", 100) < 50:
            retro["concerns"].append(f"Low success rate: {summary.get('success_rate', 0)}%")
        error_types = summary.get("error_types", {})
        if error_types.get("budget", 0) >= 3:
            retro["concerns"].append(f"Frequent budget kills ({error_types['budget']}x) — review budget caps")
        if error_types.get("timeout", 0) >= 3:
            retro["concerns"].append(f"Frequent timeouts ({error_types['timeout']}x) — review timeout settings")

        # Save to file
        filename = f"retro_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
        filepath = os.path.join(RETRO_DIR, filename)
        with open(filepath, "w") as f:
            json.dump(retro, f, indent=2)

        logger.info(f"Retrospective saved to {filepath}")
        return retro

    def get_daily_sparkline_data(self, days: int = 7) -> list[dict]:
        """Return per-day success rate for sparkline chart on dashboard."""
        metrics = self.get_metrics(days=days)
        by_day = defaultdict(lambda: {"total": 0, "success": 0})
        for m in metrics:
            day = m.get("timestamp", "")[:10]  # YYYY-MM-DD
            by_day[day]["total"] += 1
            if m["success"]:
                by_day[day]["success"] += 1

        result = []
        for i in range(days):
            day = (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
            data = by_day.get(day, {"total": 0, "success": 0})
            rate = (data["success"] / data["total"] * 100) if data["total"] > 0 else None
            result.append({"date": day, "total": data["total"], "success": data["success"], "rate": rate})
        return result


# Singleton
_engine = None
_lock = threading.Lock()


def get_self_improve_engine() -> SelfImproveEngine:
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                _engine = SelfImproveEngine()
    return _engine
