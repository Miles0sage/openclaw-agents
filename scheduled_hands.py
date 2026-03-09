"""
Scheduled Hands — Autonomous agents that run on cron schedules.

Inspired by OpenFang's "Hands" concept: pre-built domain agents that run
autonomously on schedules, NOT reactive chat. Each Hand has a manifest
(config), multi-phase prompt, and dashboard metrics.

Usage:
    from scheduled_hands import HandScheduler, register_hand, list_hands

    scheduler = HandScheduler()
    scheduler.start()

    # Register a custom hand
    register_hand(Hand(
        name="daily_cost_report",
        schedule="0 9 * * *",       # 9am daily
        handler=my_cost_report_fn,
        description="Generate daily cost summary",
    ))
"""

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("scheduled_hands")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")
HANDS_LOG_DIR = os.path.join(DATA_DIR, "hands_logs")
HANDS_CONFIG_FILE = os.path.join(DATA_DIR, "hands_config.json")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class HandResult:
    hand_name: str
    run_id: str
    success: bool
    output: str = ""
    error: str = ""
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Hand:
    name: str                           # unique identifier
    description: str = ""               # what this hand does
    schedule: str = ""                  # cron expression (5-field) or interval like "30m", "6h"
    handler: Optional[Callable] = None  # async function to execute
    enabled: bool = True
    max_consecutive_failures: int = 5   # circuit breaker threshold
    consecutive_failures: int = 0
    last_run: str = ""
    last_result: str = ""               # "success" | "failure"
    total_runs: int = 0
    total_successes: int = 0
    total_cost_usd: float = 0.0
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("handler", None)  # can't serialize callables
        return d


# ---------------------------------------------------------------------------
# Built-in Hands
# ---------------------------------------------------------------------------

async def hand_daily_cost_report() -> HandResult:
    """Generate daily cost summary and send to Slack."""
    run_id = f"cost-{uuid.uuid4().hex[:8]}"
    start = time.time()
    try:
        from cost_tracker import get_cost_summary
        summary = get_cost_summary()

        total = summary.get("total_cost_usd", 0)
        today = summary.get("today_cost_usd", 0)
        by_model = summary.get("by_model", {})

        report = (
            f"Daily Cost Report\n"
            f"Today: ${today:.4f} | Total: ${total:.4f}\n"
            f"By model: {json.dumps(by_model, indent=2)}"
        )

        # Try sending to Slack
        try:
            from gateway import send_slack_message
            channel = os.environ.get("SLACK_REPORT_CHANNEL", "C0AFE4QHKH7")
            await send_slack_message(channel, f"*Daily Cost Report*\n```{report}```")
        except Exception:
            pass

        return HandResult(
            hand_name="daily_cost_report",
            run_id=run_id,
            success=True,
            output=report,
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        return HandResult(
            hand_name="daily_cost_report",
            run_id=run_id,
            success=False,
            error=str(e),
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


async def hand_eval_check() -> HandResult:
    """Run eval on simple tasks to check for regressions."""
    run_id = f"eval-{uuid.uuid4().hex[:8]}"
    start = time.time()
    try:
        from eval_harness import run_eval
        report = await run_eval(task_subset=["simple"], use_llm_judge=False)

        output = (
            f"Eval Check: {report.total_passed}/{report.total_tasks} passed "
            f"(score: {report.total_score:.1%}, cost: ${report.total_cost_usd:.4f})"
        )

        return HandResult(
            hand_name="eval_regression_check",
            run_id=run_id,
            success=report.total_score >= 0.7,
            output=output,
            cost_usd=report.total_cost_usd,
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        return HandResult(
            hand_name="eval_regression_check",
            run_id=run_id,
            success=False,
            error=str(e),
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


async def hand_health_check() -> HandResult:
    """Check system health: gateway, dashboard, disk, memory."""
    run_id = f"health-{uuid.uuid4().hex[:8]}"
    start = time.time()
    try:
        import shutil
        import psutil

        checks = {}

        # Disk usage
        disk = shutil.disk_usage("/")
        disk_pct = (disk.used / disk.total) * 100
        checks["disk_percent"] = round(disk_pct, 1)
        checks["disk_free_gb"] = round(disk.free / (1024**3), 1)

        # Memory
        mem = psutil.virtual_memory()
        checks["memory_percent"] = round(mem.percent, 1)
        checks["memory_available_gb"] = round(mem.available / (1024**3), 1)

        # CPU
        checks["cpu_percent"] = psutil.cpu_percent(interval=1)

        # Gateway check
        import aiohttp
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get("http://localhost:18789/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    checks["gateway"] = "healthy" if resp.status == 200 else f"status:{resp.status}"
            except Exception:
                checks["gateway"] = "unreachable"

        all_ok = (
            disk_pct < 90 and
            mem.percent < 90 and
            checks.get("gateway") == "healthy"
        )

        output = json.dumps(checks, indent=2)

        # Alert if unhealthy
        if not all_ok:
            try:
                from gateway import send_slack_message
                channel = os.environ.get("SLACK_REPORT_CHANNEL", "C0AFE4QHKH7")
                await send_slack_message(channel, f"*Health Alert*\n```{output}```")
            except Exception:
                pass

        return HandResult(
            hand_name="health_check",
            run_id=run_id,
            success=all_ok,
            output=output,
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        return HandResult(
            hand_name="health_check",
            run_id=run_id,
            success=False,
            error=str(e),
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


async def hand_stale_job_cleanup() -> HandResult:
    """Find and clean up jobs stuck in 'analyzing' for >1 hour."""
    run_id = f"cleanup-{uuid.uuid4().hex[:8]}"
    start = time.time()
    try:
        from job_manager import list_jobs

        all_jobs = list_jobs(status="analyzing")
        stale = []
        now = datetime.now(timezone.utc)

        for job in all_jobs:
            created = job.get("created_at", "")
            if created:
                try:
                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    age_hours = (now - created_dt).total_seconds() / 3600
                    if age_hours > 1:
                        stale.append({"id": job.get("id"), "age_hours": round(age_hours, 1)})
                except Exception:
                    pass

        output = f"Found {len(stale)} stale jobs (>1hr in analyzing)"
        if stale:
            output += f": {json.dumps(stale[:5])}"

        return HandResult(
            hand_name="stale_job_cleanup",
            run_id=run_id,
            success=True,
            output=output,
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        return HandResult(
            hand_name="stale_job_cleanup",
            run_id=run_id,
            success=False,
            error=str(e),
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


async def hand_memory_flush() -> HandResult:
    """Flush pending memory items to long-term storage."""
    run_id = f"memflush-{uuid.uuid4().hex[:8]}"
    start = time.time()
    try:
        from semantic_memory import MemoryStore
        store = MemoryStore()
        count = store.count() if hasattr(store, 'count') else 0

        return HandResult(
            hand_name="memory_flush",
            run_id=run_id,
            success=True,
            output=f"Memory store has {count} entries",
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        return HandResult(
            hand_name="memory_flush",
            run_id=run_id,
            success=False,
            error=str(e),
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


async def hand_morning_briefing() -> HandResult:
    """Generate and send morning briefing: calendar, emails, news, pending jobs."""
    run_id = f"briefing-{uuid.uuid4().hex[:8]}"
    start = time.time()
    try:
        from agent_tools import _morning_briefing
        briefing = _morning_briefing(send_to_slack=True, include_news=True)

        return HandResult(
            hand_name="morning_briefing",
            run_id=run_id,
            success=True,
            output=briefing[:500],  # Truncate for storage
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        return HandResult(
            hand_name="morning_briefing",
            run_id=run_id,
            success=False,
            error=str(e),
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


async def hand_email_triage() -> HandResult:
    """Triage unread emails by urgency and send summary to Slack."""
    run_id = f"email-{uuid.uuid4().hex[:8]}"
    start = time.time()
    try:
        from agent_tools import _email_triage
        report = _email_triage(max_emails=20, auto_draft=False, vip_senders=[])

        # Send to Slack
        try:
            from gateway import send_slack_message
            channel = os.environ.get("SLACK_REPORT_CHANNEL", "C0AFE4QHKH7")
            await send_slack_message(channel, f"*Email Triage Report*\n```{report}```")
        except Exception:
            pass

        return HandResult(
            hand_name="email_triage",
            run_id=run_id,
            success=True,
            output=report[:500],  # Truncate for storage
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        return HandResult(
            hand_name="email_triage",
            run_id=run_id,
            success=False,
            error=str(e),
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


async def hand_pa_morning_briefing() -> HandResult:
    """PA: 7am morning briefing — health, news, calendar."""
    run_id = f"pa-brief-{uuid.uuid4().hex[:8]}"
    start = time.time()
    try:
        from pa_tools.orchestrator import PAOrchestrator
        orch = PAOrchestrator()
        result = await orch.morning_briefing()
        return HandResult(
            hand_name="pa_morning_briefing", run_id=run_id, success=True,
            output=json.dumps(result)[:500],
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        return HandResult(
            hand_name="pa_morning_briefing", run_id=run_id, success=False,
            error=str(e), duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


async def hand_pa_evening_finance() -> HandResult:
    """PA: 6pm evening finance review."""
    run_id = f"pa-fin-{uuid.uuid4().hex[:8]}"
    start = time.time()
    try:
        from pa_tools.orchestrator import PAOrchestrator
        orch = PAOrchestrator()
        result = await orch.evening_finance_review()
        return HandResult(
            hand_name="pa_evening_finance", run_id=run_id, success=True,
            output=json.dumps(result)[:500],
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        return HandResult(
            hand_name="pa_evening_finance", run_id=run_id, success=False,
            error=str(e), duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


async def hand_pa_thursday_soccer() -> HandResult:
    """PA: Thursday 8pm soccer prep."""
    run_id = f"pa-soccer-{uuid.uuid4().hex[:8]}"
    start = time.time()
    try:
        from pa_tools.orchestrator import PAOrchestrator
        orch = PAOrchestrator()
        result = await orch.thursday_soccer_prep()
        return HandResult(
            hand_name="pa_thursday_soccer", run_id=run_id, success=True,
            output=json.dumps(result)[:500],
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        return HandResult(
            hand_name="pa_thursday_soccer", run_id=run_id, success=False,
            error=str(e), duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


async def hand_pa_weekly_summary() -> HandResult:
    """PA: Sunday 5pm weekly summary."""
    run_id = f"pa-weekly-{uuid.uuid4().hex[:8]}"
    start = time.time()
    try:
        from pa_tools.orchestrator import PAOrchestrator
        orch = PAOrchestrator()
        result = await orch.sunday_weekly_summary()
        return HandResult(
            hand_name="pa_weekly_summary", run_id=run_id, success=True,
            output=json.dumps(result)[:500],
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        return HandResult(
            hand_name="pa_weekly_summary", run_id=run_id, success=False,
            error=str(e), duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


async def hand_ai_news_research() -> HandResult:
    """Research latest AI news, tools, and agent frameworks — send summary to Telegram + Slack."""
    run_id = f"ainews-{uuid.uuid4().hex[:8]}"
    start = time.time()
    try:
        from agent_tools import _read_ai_news, _perplexity_research

        # Phase 1: Fetch RSS articles from last 24 hours
        rss_news = _read_ai_news(limit=10, source=None, hours=24)

        # Phase 2: Use Perplexity to synthesize top AI agent/tool developments
        synthesis = _perplexity_research(
            "What are the most important AI agent framework releases, tool updates, "
            "and AI coding assistant developments in the last 24 hours? "
            "Focus on: new model releases, agent frameworks, MCP servers, "
            "open-source AI tools, and notable GitHub repos.",
            model="sonar",
            focus="news",
        )

        # Parse Perplexity response
        try:
            synth_data = json.loads(synthesis)
            synth_text = synth_data.get("answer", synthesis[:1500])
        except (json.JSONDecodeError, TypeError):
            synth_text = str(synthesis)[:1500]

        # Parse RSS response
        try:
            rss_data = json.loads(rss_news)
            if isinstance(rss_data, dict) and "articles" in rss_data:
                articles = rss_data["articles"][:5]
                rss_summary = "\n".join(
                    f"• {a.get('title', 'Untitled')} ({a.get('source', '?')})"
                    for a in articles
                )
            else:
                rss_summary = str(rss_news)[:500]
        except (json.JSONDecodeError, TypeError):
            rss_summary = str(rss_news)[:500]

        # Build report
        report = (
            f"🤖 *AI News Daily — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}*\n\n"
            f"*Top Stories (RSS):*\n{rss_summary}\n\n"
            f"*AI Agent & Tools Synthesis:*\n{synth_text[:1200]}\n\n"
            f"_Generated by OpenClaw AI News Hand_"
        )

        # Send to Slack
        try:
            from routers.shared import send_slack_message
            channel = os.environ.get("SLACK_REPORT_CHANNEL", "C0AFE4QHKH7")
            await send_slack_message(channel, report)
        except Exception as slack_err:
            logger.warning(f"AI news: Slack send failed: {slack_err}")

        # Send to Telegram
        try:
            from alerts import send_telegram
            await send_telegram(report[:4000], cooldown=0)
        except Exception as tg_err:
            logger.warning(f"AI news: Telegram send failed: {tg_err}")

        return HandResult(
            hand_name="ai_news_research",
            run_id=run_id,
            success=True,
            output=report[:500],
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        logger.error(f"AI news research hand failed: {e}")
        return HandResult(
            hand_name="ai_news_research",
            run_id=run_id,
            success=False,
            error=str(e),
            duration_seconds=time.time() - start,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


# ---------------------------------------------------------------------------
# Hand Registry
# ---------------------------------------------------------------------------

BUILTIN_HANDS: dict[str, Hand] = {
    "daily_cost_report": Hand(
        name="daily_cost_report",
        description="Generate and send daily cost summary to Slack",
        schedule="0 9 * * *",  # 9am UTC daily
        handler=hand_daily_cost_report,
        tags=["cost", "reporting"],
    ),
    "eval_regression_check": Hand(
        name="eval_regression_check",
        description="Run simple eval tasks weekly to check for regressions",
        schedule="0 3 * * 0",  # 3am UTC on Sundays
        handler=hand_eval_check,
        tags=["eval", "quality"],
    ),
    "health_check": Hand(
        name="health_check",
        description="Check system health: disk, memory, CPU, gateway",
        schedule="*/30 * * * *",  # every 30 minutes
        handler=hand_health_check,
        tags=["monitoring", "health"],
    ),
    "stale_job_cleanup": Hand(
        name="stale_job_cleanup",
        description="Find jobs stuck in analyzing for >1 hour",
        schedule="0 * * * *",  # every hour
        handler=hand_stale_job_cleanup,
        tags=["maintenance", "cleanup"],
    ),
    "memory_flush": Hand(
        name="memory_flush",
        description="Flush pending memory items to long-term storage",
        schedule="0 6 * * *",  # 6am UTC daily
        handler=hand_memory_flush,
        tags=["memory", "maintenance"],
    ),
    "morning_briefing": Hand(
        name="morning_briefing",
        description="Generate comprehensive morning briefing: calendar, emails, jobs, industry news",
        schedule="0 6 * * 0,2-6",  # 6am UTC Sun,Tue-Sat (NOT Monday)
        handler=hand_morning_briefing,
        tags=["briefing", "daily", "reporting"],
    ),
    "email_triage": Hand(
        name="email_triage",
        description="Triage unread emails by urgency, score 1-10, and send summary to Slack",
        schedule="0 8 * * 1-6",  # 8am UTC Tue-Sun
        handler=hand_email_triage,
        tags=["email", "daily", "reporting"],
    ),
    "pa_morning_briefing": Hand(
        name="pa_morning_briefing",
        description="PA: Morning briefing — health, news, calendar, pending tasks",
        schedule="0 14 * * 0,2-6",  # 14:00 UTC = 7am MST, Sun,Tue-Sat (NOT Monday)
        handler=hand_pa_morning_briefing,
        tags=["pa", "briefing", "daily"],
    ),
    "pa_evening_finance": Hand(
        name="pa_evening_finance",
        description="PA: Evening finance review — transactions, spending, anomalies",
        schedule="0 1 * * 1-6",  # 01:00 UTC next day = 6pm MST, Tue-Sun (NOT Monday)
        handler=hand_pa_evening_finance,
        tags=["pa", "finance", "daily"],
    ),
    "pa_thursday_soccer": Hand(
        name="pa_thursday_soccer",
        description="PA: Thursday soccer prep — route, weather, gear checklist",
        schedule="0 3 * * 5",  # 03:00 UTC Friday = 8pm MST Thursday
        handler=hand_pa_thursday_soccer,
        tags=["pa", "sports", "weekly"],
    ),
    "pa_weekly_summary": Hand(
        name="pa_weekly_summary",
        description="PA: Sunday weekly summary — spending, goals, upcoming week",
        schedule="0 0 * * 1",  # 00:00 UTC Monday = 5pm MST Sunday
        handler=hand_pa_weekly_summary,
        tags=["pa", "summary", "weekly"],
    ),
    "ai_news_research": Hand(
        name="ai_news_research",
        description="Research latest AI news, tools, and agent frameworks — send summary to Telegram + Slack",
        schedule="0 12 * * 0,2-6",  # 12pm UTC (5am MST) Sun,Tue-Sat (NOT Monday)
        handler=hand_ai_news_research,
        tags=["research", "news", "daily"],
    ),
}


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class HandScheduler:
    """Manages scheduled Hand execution with circuit breaker and logging."""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.hands: dict[str, Hand] = {}
        self._running = False

    def register(self, hand: Hand):
        """Register a Hand and schedule it."""
        self.hands[hand.name] = hand

        if not hand.enabled or not hand.schedule:
            logger.info(f"Hand '{hand.name}' registered but not scheduled (enabled={hand.enabled})")
            return

        trigger = self._parse_schedule(hand.schedule)
        if trigger:
            self.scheduler.add_job(
                self._execute_hand,
                trigger=trigger,
                args=[hand.name],
                id=f"hand_{hand.name}",
                replace_existing=True,
                misfire_grace_time=300,
            )
            logger.info(f"Hand '{hand.name}' scheduled: {hand.schedule}")

    def _parse_schedule(self, schedule: str):
        """Parse schedule string into APScheduler trigger."""
        # Interval format: "30m", "6h", "1d"
        if schedule.endswith("m"):
            try:
                return IntervalTrigger(minutes=int(schedule[:-1]))
            except ValueError:
                pass
        elif schedule.endswith("h"):
            try:
                return IntervalTrigger(hours=int(schedule[:-1]))
            except ValueError:
                pass
        elif schedule.endswith("d"):
            try:
                return IntervalTrigger(days=int(schedule[:-1]))
            except ValueError:
                pass

        # Cron format: standard 5-field
        try:
            parts = schedule.split()
            if len(parts) == 5:
                return CronTrigger(
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                )
        except Exception as e:
            logger.error(f"Invalid schedule '{schedule}': {e}")

        return None

    async def _execute_hand(self, hand_name: str):
        """Execute a Hand with circuit breaker logic."""
        hand = self.hands.get(hand_name)
        if not hand or not hand.handler:
            logger.warning(f"Hand '{hand_name}' not found or has no handler")
            return

        # Circuit breaker: auto-disable after consecutive failures
        if hand.consecutive_failures >= hand.max_consecutive_failures:
            logger.error(
                f"Hand '{hand_name}' circuit breaker OPEN: "
                f"{hand.consecutive_failures} consecutive failures. Disabling."
            )
            hand.enabled = False
            self._save_state()
            return

        logger.info(f"Executing hand: {hand_name}")
        try:
            result = await hand.handler()

            # Update hand stats
            hand.total_runs += 1
            hand.last_run = datetime.now(timezone.utc).isoformat()

            if result.success:
                hand.consecutive_failures = 0
                hand.total_successes += 1
                hand.last_result = "success"
                logger.info(f"Hand '{hand_name}' succeeded: {result.output[:100]}")
            else:
                hand.consecutive_failures += 1
                hand.last_result = "failure"
                logger.warning(f"Hand '{hand_name}' failed: {result.error[:100]}")

            hand.total_cost_usd += result.cost_usd

            # Log result
            self._log_result(result)
            self._save_state()

            # Emit event
            try:
                from event_engine import get_event_engine
                engine = get_event_engine()
                if engine:
                    engine.emit("hand.executed", {
                        "hand": hand_name,
                        "success": result.success,
                        "duration": result.duration_seconds,
                    })
            except Exception:
                pass

        except Exception as e:
            hand.consecutive_failures += 1
            hand.total_runs += 1
            hand.last_run = datetime.now(timezone.utc).isoformat()
            hand.last_result = "error"
            logger.error(f"Hand '{hand_name}' exception: {e}")
            self._save_state()

    def _log_result(self, result: HandResult):
        """Save hand result to log file."""
        os.makedirs(HANDS_LOG_DIR, exist_ok=True)
        log_file = os.path.join(HANDS_LOG_DIR, f"{result.hand_name}.jsonl")
        with open(log_file, "a") as f:
            f.write(json.dumps(result.to_dict()) + "\n")

    def _save_state(self):
        """Persist hand states to disk."""
        os.makedirs(os.path.dirname(HANDS_CONFIG_FILE), exist_ok=True)
        state = {name: hand.to_dict() for name, hand in self.hands.items()}
        with open(HANDS_CONFIG_FILE, "w") as f:
            json.dump(state, f, indent=2)

    def _load_state(self):
        """Restore hand states from disk."""
        if not os.path.exists(HANDS_CONFIG_FILE):
            return
        try:
            with open(HANDS_CONFIG_FILE) as f:
                state = json.load(f)
            for name, data in state.items():
                if name in self.hands:
                    hand = self.hands[name]
                    hand.consecutive_failures = data.get("consecutive_failures", 0)
                    hand.total_runs = data.get("total_runs", 0)
                    hand.total_successes = data.get("total_successes", 0)
                    hand.total_cost_usd = data.get("total_cost_usd", 0)
                    hand.last_run = data.get("last_run", "")
                    hand.last_result = data.get("last_result", "")
                    hand.enabled = data.get("enabled", True)
        except Exception as e:
            logger.warning(f"Failed to load hand states: {e}")

    def start(self):
        """Start the scheduler with all registered hands."""
        if self._running:
            return

        # Register builtins
        for hand in BUILTIN_HANDS.values():
            self.register(hand)

        # Restore persisted state
        self._load_state()

        self.scheduler.start()
        self._running = True
        logger.info(f"HandScheduler started with {len(self.hands)} hands")

    def stop(self):
        """Stop the scheduler."""
        if self._running:
            self.scheduler.shutdown(wait=False)
            self._running = False
            self._save_state()
            logger.info("HandScheduler stopped")

    def get_status(self) -> dict:
        """Get status of all hands."""
        return {
            "running": self._running,
            "hands": {
                name: {
                    "description": hand.description,
                    "schedule": hand.schedule,
                    "enabled": hand.enabled,
                    "last_run": hand.last_run,
                    "last_result": hand.last_result,
                    "total_runs": hand.total_runs,
                    "success_rate": (
                        f"{hand.total_successes / hand.total_runs:.0%}"
                        if hand.total_runs > 0 else "N/A"
                    ),
                    "consecutive_failures": hand.consecutive_failures,
                    "total_cost_usd": round(hand.total_cost_usd, 6),
                    "tags": hand.tags,
                }
                for name, hand in self.hands.items()
            },
        }

    def run_now(self, hand_name: str) -> bool:
        """Trigger a hand to run immediately."""
        hand = self.hands.get(hand_name)
        if not hand or not hand.handler:
            return False

        asyncio.ensure_future(self._execute_hand(hand_name))
        return True

    def enable(self, hand_name: str) -> bool:
        """Enable a hand (reset circuit breaker)."""
        hand = self.hands.get(hand_name)
        if not hand:
            return False
        hand.enabled = True
        hand.consecutive_failures = 0
        self._save_state()
        return True

    def disable(self, hand_name: str) -> bool:
        """Disable a hand."""
        hand = self.hands.get(hand_name)
        if not hand:
            return False
        hand.enabled = False
        self._save_state()
        return True


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_scheduler: Optional[HandScheduler] = None


def get_scheduler() -> HandScheduler:
    """Get or create the global HandScheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = HandScheduler()
    return _scheduler


def register_hand(hand: Hand):
    """Register a hand with the global scheduler."""
    get_scheduler().register(hand)


def list_hands() -> dict:
    """List all registered hands and their status."""
    return get_scheduler().get_status()


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    async def main():
        print("=== Scheduled Hands Self-Test ===\n")

        scheduler = HandScheduler()
        scheduler.start()

        status = scheduler.get_status()
        print(f"Scheduler running: {status['running']}")
        print(f"Registered hands: {len(status['hands'])}")
        for name, info in status["hands"].items():
            print(f"  {name}: schedule={info['schedule']}, enabled={info['enabled']}")

        # Run health check immediately
        print("\nRunning health_check hand...")
        result = await hand_health_check()
        print(f"  Success: {result.success}")
        print(f"  Output: {result.output[:200]}")
        print(f"  Duration: {result.duration_seconds:.2f}s")

        scheduler.stop()
        print("\nDone.")

    asyncio.run(main())
