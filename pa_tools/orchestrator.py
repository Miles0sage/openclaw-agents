"""
PA Automation Orchestrator — Coordinates all Week 1 automation tasks

Manages:
- Daily health checks (7am)
- Daily finance reviews (6pm)
- Daily news digest (7am)
- Travel planning (on-demand)
- Event logging
- Notion integration

TODO: Integrate with openclaw event_engine and cron system
"""

import os
import json
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, List
from enum import Enum

from .finance import FinanceAdvisor, run_finance_check
from .health import HealthCheck, run_health_check
from .news import NewsAggregator, run_news_digest
from .travel import TravelAgent, run_travel_planning

logger = logging.getLogger(__name__)


class CronSchedule(str, Enum):
    """Standard cron schedules for PA automation"""
    MORNING_7AM = "0 7 * * *"  # 7am daily
    EVENING_6PM = "0 18 * * *"  # 6pm daily
    MONDAY_6PM = "0 18 * * 1"  # Monday 6pm
    THURSDAY_8PM = "0 20 * * 4"  # Thursday 8pm
    SUNDAY_5PM = "0 17 * * 0"  # Sunday 5pm


class PAOrchestrator:
    """
    Coordinates all PA automation tasks across domains.
    """

    def __init__(self):
        self.finance = FinanceAdvisor()
        self.health = HealthCheck()
        self.news = NewsAggregator()
        self.travel = TravelAgent()

        self.log = []

    def log_event(self, event: Dict[str, Any]):
        """Log an event for debugging and auditing"""
        self.log.append({
            "timestamp": datetime.now().isoformat(),
            **event,
        })
        logger.info(f"Event logged: {event}")

    async def morning_briefing(self) -> Dict[str, Any]:
        """
        7am MST: Daily morning briefing
        - Health score (sleep, activity)
        - News digest (top stories)
        - Weather (stub)
        - Day overview from calendar (stub)
        """
        start = datetime.now()
        results = {}

        try:
            # Health
            logger.info("Fetching health data for morning briefing...")
            health_data = await self.health.fetch_health_data(days=1)
            results["health"] = health_data["summary"]

            # News
            logger.info("Fetching news for morning briefing...")
            news_data = await self.news.fetch_feeds(hours=24)
            results["news"] = {
                "topics": list(news_data["by_topic"].keys()),
                "article_count": len(news_data["articles"]),
            }

            self.log_event({
                "task": "morning_briefing",
                "status": "success",
                "duration_ms": int((datetime.now() - start).total_seconds() * 1000),
            })

        except Exception as e:
            logger.error(f"Morning briefing failed: {e}")
            self.log_event({
                "task": "morning_briefing",
                "status": "error",
                "error": str(e),
            })

        return results

    async def evening_finance_review(self) -> Dict[str, Any]:
        """
        6pm MST: Daily evening finance review
        - Transactions from last 24 hours
        - Spending alerts
        - Weekly budget status
        """
        start = datetime.now()
        results = {}

        try:
            logger.info("Running evening finance review...")
            result = await run_finance_check()
            results = result

            self.log_event({
                "task": "evening_finance_review",
                "status": "success",
                "alerts": len(result.get("alerts", [])),
                "duration_ms": int((datetime.now() - start).total_seconds() * 1000),
            })

        except Exception as e:
            logger.error(f"Evening finance review failed: {e}")
            self.log_event({
                "task": "evening_finance_review",
                "status": "error",
                "error": str(e),
            })

        return results

    async def thursday_soccer_prep(self) -> Dict[str, Any]:
        """
        Thursday 8pm: Soccer game prep
        - Route to soccer field (optimize if errands first)
        - Pre-game nutrition recommendations
        - Recovery plan post-game
        """
        logger.info("Thursday soccer prep (stub - requires location data)")
        return {
            "status": "stub",
            "message": "Need Miles' current location and soccer field address",
        }

    async def sunday_weekly_summary(self) -> Dict[str, Any]:
        """
        Sunday 5pm: Weekly summary
        - Weekly spending review
        - Health trends (sleep, activity)
        - Goals progress
        - Week ahead preview
        """
        logger.info("Sunday weekly summary (stub - requires goal tracking)")
        return {
            "status": "stub",
            "message": "Need to set up goal tracking first",
        }

    async def run_all_daily(self) -> Dict[str, Any]:
        """
        Run all daily automation tasks in parallel.
        Called once per day (recommend 7am or during off-hours).
        """
        logger.info("Running all daily PA automation tasks...")

        results = await asyncio.gather(
            self.morning_briefing(),
            self.evening_finance_review(),
            return_exceptions=True,
        )

        morning = results[0] if isinstance(results[0], dict) else {"error": str(results[0])}
        evening = results[1] if isinstance(results[1], dict) else {"error": str(results[1])}

        return {
            "timestamp": datetime.now().isoformat(),
            "morning_briefing": morning,
            "evening_finance": evening,
            "log_entries": len(self.log),
        }

    def get_cron_config(self) -> Dict[str, Dict[str, Any]]:
        """
        Return recommended cron configuration for OpenClaw.
        Can be imported into gateway.py for scheduling.
        """
        return {
            "morning_briefing": {
                "schedule": CronSchedule.MORNING_7AM.value,
                "description": "7am: Health + News briefing",
                "handler": "pa_tools.orchestrator:morning_briefing",
            },
            "evening_finance": {
                "schedule": CronSchedule.EVENING_6PM.value,
                "description": "6pm: Finance review",
                "handler": "pa_tools.orchestrator:evening_finance_review",
            },
            "thursday_soccer": {
                "schedule": CronSchedule.THURSDAY_8PM.value,
                "description": "Thursday 8pm: Soccer prep",
                "handler": "pa_tools.orchestrator:thursday_soccer_prep",
            },
            "sunday_summary": {
                "schedule": CronSchedule.SUNDAY_5PM.value,
                "description": "Sunday 5pm: Weekly summary",
                "handler": "pa_tools.orchestrator:sunday_weekly_summary",
            },
        }


async def main():
    """Example usage"""
    orchestrator = PAOrchestrator()

    # Run morning briefing
    morning = await orchestrator.morning_briefing()
    print("\n=== MORNING BRIEFING ===")
    print(json.dumps(morning, indent=2, default=str))

    # Run evening finance
    evening = await orchestrator.evening_finance_review()
    print("\n=== EVENING FINANCE ===")
    print(json.dumps(evening, indent=2, default=str))

    # Show log
    print("\n=== EVENT LOG ===")
    for entry in orchestrator.log:
        print(f"  [{entry['timestamp']}] {entry['task']}: {entry['status']}")

    # Show recommended cron config
    print("\n=== RECOMMENDED CRON CONFIG ===")
    config = orchestrator.get_cron_config()
    for task, cfg in config.items():
        print(f"  {task}: {cfg['schedule']} - {cfg['description']}")


if __name__ == "__main__":
    asyncio.run(main())
