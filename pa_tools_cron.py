"""
PA Tools Cron Integration — Register PA automation tasks with OpenClaw gateway

This module provides the integration layer between pa_tools orchestrator and
the OpenClaw cron scheduler. It handles scheduling all PA automation tasks.

Usage (in gateway.py lifespan):
    from pa_tools_cron import register_pa_tools_crons
    cron = get_cron_scheduler()
    await register_pa_tools_crons(cron)
"""

import logging
import asyncio
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


async def register_pa_tools_crons(cron_scheduler):
    """
    Register all PA Tools automation tasks with the gateway cron scheduler.

    Args:
        cron_scheduler: APScheduler-compatible scheduler instance from gateway
    """
    from pa_tools.orchestrator import PAOrchestrator

    orchestrator = PAOrchestrator()

    try:
        # 7am: Morning briefing (health + news)
        cron_scheduler.add_job(
            func=orchestrator.morning_briefing,
            trigger="cron",
            hour=7,
            minute=0,
            id="pa_morning_briefing",
            name="PA: 7am Health + News Briefing",
            replace_existing=True,
        )
        logger.info("Scheduled: PA morning_briefing at 7am MST")

        # 6pm: Evening finance review
        cron_scheduler.add_job(
            func=orchestrator.evening_finance_review,
            trigger="cron",
            hour=18,
            minute=0,
            id="pa_evening_finance",
            name="PA: 6pm Evening Finance Review",
            replace_existing=True,
        )
        logger.info("Scheduled: PA evening_finance_review at 6pm MST")

        # Thursday 8pm: Soccer prep
        cron_scheduler.add_job(
            func=orchestrator.thursday_soccer_prep,
            trigger="cron",
            day_of_week=3,  # 0=Mon, 3=Thu
            hour=20,
            minute=0,
            id="pa_thursday_soccer",
            name="PA: Thursday 8pm Soccer Prep",
            replace_existing=True,
        )
        logger.info("Scheduled: PA thursday_soccer_prep at Thursday 8pm MST")

        # Sunday 5pm: Weekly summary
        cron_scheduler.add_job(
            func=orchestrator.sunday_weekly_summary,
            trigger="cron",
            day_of_week=6,  # 0=Mon, 6=Sun
            hour=17,
            minute=0,
            id="pa_sunday_summary",
            name="PA: Sunday 5pm Weekly Summary",
            replace_existing=True,
        )
        logger.info("Scheduled: PA sunday_weekly_summary at Sunday 5pm MST")

        logger.info("✓ PA Tools crons registered successfully (4 tasks)")
        return True

    except Exception as e:
        logger.error(f"Failed to register PA Tools crons: {e}")
        return False


async def test_pa_tools_crons():
    """
    Test all PA tools tasks without scheduler (direct execution).
    Useful for debugging before scheduler integration.
    """
    from pa_tools.orchestrator import PAOrchestrator

    orchestrator = PAOrchestrator()

    print("\n" + "=" * 70)
    print("PA TOOLS CRON TEST — All tasks execute in parallel")
    print("=" * 70 + "\n")

    start = datetime.now()

    try:
        result = await orchestrator.run_all_daily()

        elapsed = (datetime.now() - start).total_seconds()
        print(f"\n✓ All PA tasks completed in {elapsed:.1f}s")
        print(f"  Morning briefing: {len(result.get('morning_briefing', {})) > 0}")
        print(f"  Evening finance: {len(result.get('evening_finance', {})) > 0}")
        print(f"  Event log entries: {result.get('log_entries', 0)}")

        return True

    except Exception as e:
        print(f"\n✗ PA tools test failed: {e}")
        logger.error(f"PA tools test error: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    # For standalone testing
    import json

    success = asyncio.run(test_pa_tools_crons())
    exit(0 if success else 1)
