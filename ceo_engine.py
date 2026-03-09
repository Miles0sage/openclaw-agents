"""
AI CEO Engine for OpenClaw
==========================
Autonomous decision-making layer that sits above the PA and agency.

Runs scheduled loops on the gateway:
  - Agency Health Check (every hour): success rates, stuck jobs, budget
  - AI Research Scout (daily 8am MST): scan for new tools, trends, propose integrations
  - Business Pipeline (daily 9am MST): lead follow-up, opportunity detection
  - Strategic Review (weekly Monday): goal tracking, spend analysis, priority adjustment

Each loop can:
  1. Create jobs in the agency (via job_manager)
  2. Emit events (via event_engine)
  3. Log decisions (to data/ceo/decisions.jsonl)
  4. Update strategic goals (data/ceo/goals.json)
"""

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ceo_engine")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "os.environ.get("OPENCLAW_DATA_DIR", "./data")")
CEO_DIR = os.path.join(DATA_DIR, "ceo")
GOALS_PATH = os.path.join(CEO_DIR, "goals.json")
DECISIONS_PATH = os.path.join(CEO_DIR, "decisions.jsonl")
SCHEDULE_PATH = os.path.join(CEO_DIR, "schedule.json")

os.makedirs(CEO_DIR, exist_ok=True)

# MST = UTC-7
MST_OFFSET = timedelta(hours=-7)

# ---------------------------------------------------------------------------
# Schedule config (hour in MST)
# ---------------------------------------------------------------------------

SCHEDULES = {
    "agency_health": {"interval_seconds": 3600, "type": "interval"},
    "ai_scout": {"hour_mst": 8, "type": "daily"},
    "business_pipeline": {"hour_mst": 9, "type": "daily"},
    "strategic_review": {"weekday": 0, "hour_mst": 10, "type": "weekly"},  # Monday
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_mst() -> datetime:
    return datetime.now(timezone(MST_OFFSET))


def _load_json(path: str, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default if default is not None else {}


def _save_json(path: str, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _append_jsonl(path: str, record: dict):
    with open(path, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


# ---------------------------------------------------------------------------
# CEO Engine
# ---------------------------------------------------------------------------

class CEOEngine:
    """Autonomous AI CEO — proactive decision-making for the agency."""

    def __init__(self):
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._schedule_state = _load_json(SCHEDULE_PATH, {})
        self.goals = self._load_goals()
        self.stats = {
            "decisions_made": 0,
            "jobs_created": 0,
            "started_at": None,
            "last_health_check": None,
            "last_ai_scout": None,
            "last_business_pipeline": None,
            "last_strategic_review": None,
        }

    # -- Goal management --

    def _load_goals(self) -> list:
        data = _load_json(GOALS_PATH, {"goals": []})
        return data.get("goals", [])

    def _save_goals(self):
        _save_json(GOALS_PATH, {"goals": self.goals, "updated_at": _now_utc().isoformat()})

    def add_goal(self, title: str, priority: str = "P1", metrics: list = None) -> dict:
        goal = {
            "id": f"g{len(self.goals) + 1}",
            "title": title,
            "priority": priority,
            "status": "active",
            "metrics": metrics or [],
            "progress_pct": 0,
            "created_at": _now_utc().isoformat(),
        }
        self.goals.append(goal)
        self._save_goals()
        self._log_decision("goal_created", f"New goal: {title}", {"goal": goal})
        return goal

    def update_goal(self, goal_id: str, **kwargs) -> Optional[dict]:
        for g in self.goals:
            if g["id"] == goal_id:
                g.update(kwargs)
                g["updated_at"] = _now_utc().isoformat()
                self._save_goals()
                return g
        return None

    def get_active_goals(self) -> list:
        return [g for g in self.goals if g.get("status") == "active"]

    # -- Decision logging --

    def _log_decision(self, decision_type: str, summary: str, details: dict = None):
        record = {
            "id": str(uuid.uuid4())[:8],
            "type": decision_type,
            "summary": summary,
            "details": details or {},
            "timestamp": _now_utc().isoformat(),
        }
        _append_jsonl(DECISIONS_PATH, record)
        self.stats["decisions_made"] += 1
        logger.info(f"[CEO] Decision: {decision_type} — {summary}")
        return record

    # -- Schedule state --

    def _save_schedule(self):
        _save_json(SCHEDULE_PATH, self._schedule_state)

    def _last_run(self, task_name: str) -> Optional[float]:
        return self._schedule_state.get(task_name, {}).get("last_run_ts")

    def _mark_run(self, task_name: str):
        self._schedule_state[task_name] = {
            "last_run_ts": time.time(),
            "last_run_at": _now_utc().isoformat(),
        }
        self._save_schedule()
        self.stats[f"last_{task_name}"] = _now_utc().isoformat()

    # -- Job creation helper --

    def _create_agency_job(self, project: str, task: str, priority: str = "P2",
                           source: str = "ceo_engine") -> Optional[dict]:
        """Create a job in the agency queue via job_manager."""
        try:
            from job_manager import create_job
            job = create_job(project, task, priority)
            job_dict = job.to_dict() if hasattr(job, 'to_dict') else job
            self.stats["jobs_created"] += 1

            # Emit event
            self._emit_event("ceo.job_created", {
                "job_id": job_dict.get("job_id"),
                "project": project,
                "task": task,
                "source": source,
            })

            # Notify runner
            try:
                from autonomous_runner import get_runner
                r = get_runner()
                if r:
                    r.notify_new_job()
            except Exception:
                pass

            return job_dict
        except Exception as e:
            logger.error(f"[CEO] Failed to create job: {e}")
            return None

    def _emit_event(self, event_type: str, data: dict):
        try:
            from event_engine import get_event_engine
            engine = get_event_engine()
            if engine:
                engine.emit(event_type, data)
        except Exception:
            pass

    def _notify_slack(self, message: str):
        """Send a Slack notification via gateway's send_slack_message."""
        try:
            from gateway import send_slack_message, SLACK_REPORT_CHANNEL
            asyncio.ensure_future(send_slack_message(SLACK_REPORT_CHANNEL, f"[CEO] {message}"))
        except Exception as e:
            logger.warning(f"[CEO] Slack notify failed: {e}")

    def _update_goal_progress(self, goal_id: str, progress_pct: int):
        """Update a goal's progress percentage."""
        self.update_goal(goal_id, progress_pct=min(progress_pct, 100))

    # -- Lifecycle --

    async def start(self):
        """Start CEO background loops."""
        self._running = True
        self.stats["started_at"] = _now_utc().isoformat()
        self._tasks = [
            asyncio.create_task(self._tick_loop()),
        ]
        logger.info("[CEO] AI CEO Engine started — autonomous loops active")
        self._emit_event("ceo.started", {"goals": len(self.get_active_goals())})

    async def stop(self):
        """Stop all CEO loops."""
        self._running = False
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()
        logger.info("[CEO] AI CEO Engine stopped")

    async def _tick_loop(self):
        """Main tick — runs every 60s, checks what tasks are due."""
        # Small initial delay to let gateway fully start
        await asyncio.sleep(10)

        while self._running:
            try:
                now = time.time()
                mst_now = _now_mst()

                # --- Agency Health Check (hourly) ---
                last = self._last_run("agency_health")
                if last is None or (now - last) >= 3600:
                    await self._run_agency_health()

                # --- AI Research Scout (daily at 8am MST) ---
                last = self._last_run("ai_scout")
                if self._is_daily_due(last, target_hour=8):
                    await self._run_ai_scout()

                # --- Business Pipeline (daily at 9am MST) ---
                last = self._last_run("business_pipeline")
                if self._is_daily_due(last, target_hour=9):
                    await self._run_business_pipeline()

                # --- Strategic Review (weekly Monday 10am MST) ---
                last = self._last_run("strategic_review")
                if self._is_weekly_due(last, target_weekday=0, target_hour=10):
                    await self._run_strategic_review()

            except Exception as e:
                logger.error(f"[CEO] Tick error: {e}", exc_info=True)

            await asyncio.sleep(60)

    def _is_daily_due(self, last_ts: Optional[float], target_hour: int) -> bool:
        """Check if a daily task at target_hour MST is due."""
        mst_now = _now_mst()
        if mst_now.hour < target_hour:
            return False
        if last_ts is None:
            return True
        # Check if last run was before today's target time
        today_target = mst_now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        last_dt = datetime.fromtimestamp(last_ts, tz=timezone(MST_OFFSET))
        return last_dt < today_target

    def _is_weekly_due(self, last_ts: Optional[float], target_weekday: int, target_hour: int) -> bool:
        """Check if a weekly task is due (weekday 0=Monday)."""
        mst_now = _now_mst()
        if mst_now.weekday() != target_weekday:
            return False
        return self._is_daily_due(last_ts, target_hour)

    # ======================================================================
    # AUTONOMOUS LOOPS
    # ======================================================================

    async def _run_agency_health(self):
        """Hourly: Check agency health — success rates, stuck jobs, budget."""
        try:
            self._mark_run("agency_health")
            from job_manager import list_jobs as get_jobs

            all_jobs = get_jobs()
            now = time.time()

            # Count recent job stats (last 24h)
            recent = []
            for j in all_jobs:
                created = j.get("created_at", "")
                if created:
                    try:
                        ct = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        if (now - ct.timestamp()) < 86400:
                            recent.append(j)
                    except (ValueError, TypeError):
                        pass

            total = len(recent)
            done = sum(1 for j in recent if j.get("status") == "done")
            failed = sum(1 for j in recent if j.get("status") == "failed")
            pending = sum(1 for j in recent if j.get("status") == "pending")
            running = sum(1 for j in recent if j.get("status") in ("analyzing", "code_generated"))
            success_rate = (done / total * 100) if total > 0 else 0

            # Check for stuck jobs (running > 30 min)
            stuck_jobs = []
            for j in all_jobs:
                if j.get("status") in ("analyzing", "code_generated"):
                    created = j.get("created_at", "")
                    if created:
                        try:
                            ct = datetime.fromisoformat(created.replace("Z", "+00:00"))
                            if (now - ct.timestamp()) > 1800:
                                stuck_jobs.append(j.get("job_id"))
                        except (ValueError, TypeError):
                            pass

            # Total cost (from completed runs)
            total_cost = 0.0
            runs_dir = os.path.join(DATA_DIR, "jobs", "runs")
            if os.path.isdir(runs_dir):
                for run_id in os.listdir(runs_dir):
                    result_path = os.path.join(runs_dir, run_id, "result.json")
                    if os.path.exists(result_path):
                        try:
                            with open(result_path) as f:
                                result = json.load(f)
                            cost = result.get("cost_usd", 0)
                            if isinstance(cost, (int, float)):
                                total_cost += cost
                        except (json.JSONDecodeError, IOError):
                            pass

            health = {
                "jobs_24h": total,
                "done": done,
                "failed": failed,
                "pending": pending,
                "running": running,
                "success_rate_pct": round(success_rate, 1),
                "stuck_jobs": stuck_jobs,
                "total_cost_usd": round(total_cost, 4),
            }

            self._log_decision("health_check",
                f"24h: {done}/{total} done ({success_rate:.0f}%), {len(stuck_jobs)} stuck, ${total_cost:.4f} total",
                health)

            # Auto-remediation: cancel stuck jobs
            if stuck_jobs:
                for job_id in stuck_jobs[:3]:  # Max 3 at a time
                    try:
                        from autonomous_runner import get_runner
                        r = get_runner()
                        if r:
                            r.cancel_job(job_id)
                            self._log_decision("auto_cancel", f"Cancelled stuck job {job_id}")
                    except Exception:
                        pass

            # Alert if success rate drops below 70%
            if total >= 3 and success_rate < 70:
                self._emit_event("ceo.alert", {
                    "type": "low_success_rate",
                    "rate": success_rate,
                    "message": f"Agency success rate dropped to {success_rate:.0f}% ({done}/{total} in 24h)",
                })

            return health

        except Exception as e:
            logger.error(f"[CEO] Health check failed: {e}", exc_info=True)
            return None

    async def _run_ai_scout(self):
        """Daily: Scan for AI developments and propose integrations."""
        try:
            self._mark_run("ai_scout")

            # Use the gateway's model to generate a research brief
            research_topics = [
                "new AI coding agents and tools released this week",
                "latest model releases (Claude, GPT, Gemini, open-source)",
                "AI automation framework updates",
                "MCP server ecosystem new tools",
            ]

            # Create a research job for the agency to handle
            task_desc = (
                "AI Research Scout (CEO auto-generated): "
                "Research the latest AI developments from the past 24 hours. Focus on: "
                "1) New AI coding agents or automation tools, "
                "2) Model releases or significant updates, "
                "3) MCP server ecosystem changes, "
                "4) Anything relevant to OpenClaw's multi-agent architecture. "
                "Summarize findings with actionable integration recommendations."
            )

            job = self._create_agency_job(
                project="openclaw",
                task=task_desc,
                priority="P3",
                source="ceo_ai_scout",
            )

            self._log_decision("ai_scout_dispatched",
                "Created daily AI research job",
                {"job": job})

            return {"status": "dispatched", "job": job}

        except Exception as e:
            logger.error(f"[CEO] AI scout failed: {e}", exc_info=True)
            return None

    async def _run_business_pipeline(self):
        """Daily: Run structured lead pipeline — discovery, outreach, proposals."""
        try:
            self._mark_run("business_pipeline")

            from pipeline_orchestrator import PipelineOrchestrator
            orch = PipelineOrchestrator()

            jobs_created = []

            # Phase 1: Discovery (if any business type is due for search)
            if orch.should_run_discovery():
                task = orch.build_discovery_job()
                job = self._create_agency_job(
                    project="openclaw", task=task,
                    priority="P2", source="ceo_pipeline_discovery",
                )
                if job:
                    jobs_created.append(("discovery", job))

            # Phase 2: Outreach (qualified uncalled leads)
            qualified = orch.qualify_leads()
            if qualified:
                task = orch.build_outreach_job(qualified[:5])
                job = self._create_agency_job(
                    project="openclaw", task=task,
                    priority="P1", source="ceo_pipeline_outreach",
                )
                if job:
                    jobs_created.append(("outreach", job))

            # Phase 3: Proposals (leads marked "interested")
            interested = orch.get_interested_leads()
            if interested:
                task = orch.build_proposal_job(interested)
                job = self._create_agency_job(
                    project="openclaw", task=task,
                    priority="P2", source="ceo_pipeline_proposals",
                )
                if job:
                    jobs_created.append(("proposals", job))

            # Record metrics + update g5 progress
            orch.record_run({"phases": [p[0] for p in jobs_created]})
            progress = orch.get_g5_progress()
            self._update_goal_progress("g5", progress)

            # Slack notification
            if jobs_created:
                phases = ", ".join(p[0] for p in jobs_created)
                self._notify_slack(
                    f"Business pipeline: {len(jobs_created)} jobs — {phases} "
                    f"(g5 progress: {progress}%)"
                )

            self._log_decision("business_pipeline_dispatched",
                f"Pipeline ran: {len(jobs_created)} jobs, g5 at {progress}%",
                {"jobs": [p[0] for p in jobs_created], "qualified_leads": len(qualified),
                 "interested_leads": len(interested), "g5_progress": progress})

            return {
                "status": "dispatched",
                "jobs_created": len(jobs_created),
                "phases": [p[0] for p in jobs_created],
                "g5_progress": progress,
            }

        except Exception as e:
            logger.error(f"[CEO] Business pipeline failed: {e}", exc_info=True)
            return None

    async def _run_strategic_review(self):
        """Weekly: Review goals, analyze performance, adjust priorities."""
        try:
            self._mark_run("strategic_review")

            # Gather data for review
            from job_manager import list_jobs as get_jobs
            all_jobs = get_jobs()

            # Last 7 days stats
            now = time.time()
            week_jobs = []
            for j in all_jobs:
                created = j.get("created_at", "")
                if created:
                    try:
                        ct = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        if (now - ct.timestamp()) < 604800:
                            week_jobs.append(j)
                    except (ValueError, TypeError):
                        pass

            total = len(week_jobs)
            done = sum(1 for j in week_jobs if j.get("status") == "done")
            failed = sum(1 for j in week_jobs if j.get("status") == "failed")

            # Cost for the week
            week_cost = 0.0
            runs_dir = os.path.join(DATA_DIR, "jobs", "runs")
            if os.path.isdir(runs_dir):
                for run_id in os.listdir(runs_dir):
                    result_path = os.path.join(runs_dir, run_id, "result.json")
                    if os.path.exists(result_path):
                        try:
                            with open(result_path) as f:
                                result = json.load(f)
                            ts = result.get("started_at", "")
                            cost = result.get("cost_usd", 0)
                            if ts:
                                st = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                                if (now - st.timestamp()) < 604800 and isinstance(cost, (int, float)):
                                    week_cost += cost
                        except (json.JSONDecodeError, IOError, ValueError):
                            pass

            # By-project breakdown
            project_stats = {}
            for j in week_jobs:
                p = j.get("project_name", j.get("project", "unknown"))
                if p not in project_stats:
                    project_stats[p] = {"total": 0, "done": 0, "failed": 0}
                project_stats[p]["total"] += 1
                if j.get("status") == "done":
                    project_stats[p]["done"] += 1
                elif j.get("status") == "failed":
                    project_stats[p]["failed"] += 1

            review = {
                "period": "7d",
                "total_jobs": total,
                "done": done,
                "failed": failed,
                "success_rate_pct": round(done / total * 100, 1) if total > 0 else 0,
                "week_cost_usd": round(week_cost, 4),
                "by_project": project_stats,
                "active_goals": len(self.get_active_goals()),
                "goals": self.get_active_goals(),
            }

            self._log_decision("strategic_review",
                f"Weekly: {done}/{total} done ({review['success_rate_pct']}%), ${week_cost:.4f} spent",
                review)

            # Create strategic planning job
            task_desc = (
                "Strategic Weekly Review (CEO auto-generated): "
                f"Last 7 days: {done}/{total} jobs done ({review['success_rate_pct']}% success), "
                f"${week_cost:.4f} spent. "
                f"Active goals: {len(self.get_active_goals())}. "
                "Analyze: 1) What went well and what failed, "
                "2) Cost efficiency — are we over/under budget, "
                "3) Goal progress — update percentage, "
                "4) Priorities for next week — what should the agency focus on."
            )

            job = self._create_agency_job(
                project="openclaw",
                task=task_desc,
                priority="P2",
                source="ceo_strategic_review",
            )

            review["job"] = job
            return review

        except Exception as e:
            logger.error(f"[CEO] Strategic review failed: {e}", exc_info=True)
            return None

    # ======================================================================
    # API-facing methods
    # ======================================================================

    def get_status(self) -> dict:
        """Get CEO engine status for API."""
        return {
            "running": self._running,
            "stats": self.stats,
            "active_goals": len(self.get_active_goals()),
            "goals": self.get_active_goals(),
            "schedule": {
                name: {
                    "last_run": self._schedule_state.get(name, {}).get("last_run_at", "never"),
                    "config": conf,
                }
                for name, conf in SCHEDULES.items()
            },
        }

    def get_decisions(self, limit: int = 50) -> list:
        """Get recent decisions from the log."""
        if not os.path.exists(DECISIONS_PATH):
            return []
        decisions = []
        try:
            with open(DECISIONS_PATH) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            decisions.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except IOError:
            pass
        return decisions[-limit:]

    async def trigger_task(self, task_name: str) -> dict:
        """Manually trigger a CEO task (for API/testing)."""
        handlers = {
            "agency_health": self._run_agency_health,
            "ai_scout": self._run_ai_scout,
            "business_pipeline": self._run_business_pipeline,
            "strategic_review": self._run_strategic_review,
        }
        handler = handlers.get(task_name)
        if not handler:
            return {"error": f"Unknown task: {task_name}", "valid": list(handlers.keys())}
        result = await handler()
        return {"task": task_name, "result": result}


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_ceo_instance: Optional[CEOEngine] = None


def init_ceo_engine() -> CEOEngine:
    """Initialize and return the global CEO engine instance."""
    global _ceo_instance
    _ceo_instance = CEOEngine()
    return _ceo_instance


def get_ceo_engine() -> Optional[CEOEngine]:
    """Get the global CEO engine instance."""
    return _ceo_instance
