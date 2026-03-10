"""
Health Check Tool — Sleep tracking, activity analysis, recovery monitoring

Week 1 MVP:
- Fetch sleep data from Fitbit/Google Fit API (or mock)
- Fetch activity data
- Calculate health scores
- Alert on anomalies (poor sleep, low activity)
- Export to Notion Health database
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import httpx

logger = logging.getLogger(__name__)

# Configuration
FITBIT_ACCESS_TOKEN = os.getenv("FITBIT_ACCESS_TOKEN", "")
OURA_TOKEN = os.getenv("OURA_TOKEN", "")
GOOGLE_FIT_TOKEN = os.getenv("GOOGLE_FIT_TOKEN", "")

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_HEALTH_DB = os.getenv("NOTION_HEALTH_DB_ID", "")


class HealthCheck:
    """
    Monitor Miles' health: sleep, activity, recovery metrics
    """

    def __init__(self):
        self.has_fitbit = bool(FITBIT_ACCESS_TOKEN)
        self.has_oura = bool(OURA_TOKEN)
        self.has_google = bool(GOOGLE_FIT_TOKEN)
        self.has_notion = bool(NOTION_TOKEN and NOTION_HEALTH_DB)

        # Health thresholds (Miles' baseline from user preferences)
        self.sleep_target = 7.0  # hours
        self.activity_target = 10000  # steps
        self.hrv_baseline = 50  # Heart Rate Variability (ms)

    async def fetch_health_data(self, days: int = 7) -> Dict[str, Any]:
        """
        Fetch health data from Fitbit/Oura.
        Falls back to mock data if APIs not available.

        Returns:
            {
                "sleep": [...],
                "activity": [...],
                "summary": {...},
                "alerts": [...],
            }
        """
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)

        # Try Oura first (more accurate for sleep), then Fitbit
        if self.has_oura:
            try:
                return await self._fetch_oura_data(start_date, end_date)
            except Exception as e:
                logger.warning(f"Oura fetch failed: {e}")

        if self.has_fitbit:
            try:
                return await self._fetch_fitbit_data(start_date, end_date)
            except Exception as e:
                logger.warning(f"Fitbit fetch failed: {e}")

        logger.warning("No health API configured. Using mock data.")
        return await self._mock_health_data(start_date, end_date)

    async def _fetch_oura_data(self, start_date, end_date) -> Dict[str, Any]:
        """Fetch from Oura Ring API (primary for sleep)"""
        headers = {
            "Authorization": f"Bearer {OURA_TOKEN}",
        }

        # Sleep data
        sleep_url = "https://api.ouraring.com/v2/usercollection/sleep"
        sleep_params = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }

        # Readiness data
        readiness_url = "https://api.ouraring.com/v2/usercollection/readiness"
        readiness_params = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }

        async with httpx.AsyncClient() as client:
            sleep_resp = await client.get(
                sleep_url,
                params=sleep_params,
                headers=headers,
                timeout=15
            )
            readiness_resp = await client.get(
                readiness_url,
                params=readiness_params,
                headers=headers,
                timeout=15
            )

            sleep_resp.raise_for_status()
            readiness_resp.raise_for_status()

            sleep_data = sleep_resp.json().get("data", [])
            readiness_data = readiness_resp.json().get("data", [])

        return {
            "sleep": sleep_data,
            "readiness": readiness_data,
            "activity": [],  # Oura doesn't track steps well
            "summary": self._summarize_health(sleep_data, []),
            "alerts": self._check_health_alerts(sleep_data, []),
        }

    async def _fetch_fitbit_data(self, start_date, end_date) -> Dict[str, Any]:
        """Fetch from Fitbit API"""
        headers = {
            "Authorization": f"Bearer {FITBIT_ACCESS_TOKEN}",
        }

        base_url = "https://api.fitbit.com/1.2/user/-"

        # Sleep
        sleep_url = f"{base_url}/sleep/date/{start_date.isoformat()}/{end_date.isoformat()}.json"

        # Activity (steps)
        activity_url = f"{base_url}/activities/date/{start_date.isoformat()}/{end_date.isoformat()}.json"

        async with httpx.AsyncClient() as client:
            sleep_resp = await client.get(sleep_url, headers=headers, timeout=15)
            activity_resp = await client.get(activity_url, headers=headers, timeout=15)

            sleep_resp.raise_for_status()
            activity_resp.raise_for_status()

            sleep_data = sleep_resp.json().get("sleep", [])
            activity_data = activity_resp.json().get("activities-steps", [])

        return {
            "sleep": sleep_data,
            "activity": activity_data,
            "readiness": [],
            "summary": self._summarize_health(sleep_data, activity_data),
            "alerts": self._check_health_alerts(sleep_data, activity_data),
        }

    async def _mock_health_data(self, start_date, end_date) -> Dict[str, Any]:
        """Return mock health data for testing"""
        sleep_data = []
        activity_data = []

        for i in range(7):
            date = start_date + timedelta(days=i)

            # Mock sleep (6-8 hours)
            sleep_hours = 6.5 + (i % 3) * 0.5
            sleep_data.append({
                "date": date.isoformat(),
                "duration": int(sleep_hours * 3600),  # seconds
                "sleep_score": int(75 + (i % 2) * 10),
                "deep_sleep": int(sleep_hours * 0.2),  # 20% of sleep
                "hrv": 50 + (i % 2) * 10,
            })

            # Mock activity (8000-12000 steps)
            steps = 8000 + (i * 500) % 4000
            activity_data.append({
                "dateTime": date.isoformat(),
                "value": str(steps),
            })

        return {
            "sleep": sleep_data,
            "activity": activity_data,
            "readiness": [],
            "summary": self._summarize_health(sleep_data, activity_data),
            "alerts": self._check_health_alerts(sleep_data, activity_data),
        }

    def _summarize_health(
        self, sleep_data: List[Dict], activity_data: List[Dict]
    ) -> Dict[str, Any]:
        """Summarize health metrics"""
        # Sleep summary
        sleep_hours = []
        for s in sleep_data:
            if isinstance(s, dict):
                if "duration" in s:  # Fitbit format
                    duration_hours = s["duration"] / 3600
                elif "sleep_score" in s:  # Oura format
                    duration_hours = s.get("deep_sleep", 0) / 3600 + 6  # Estimate
                else:
                    continue
                sleep_hours.append(duration_hours)

        avg_sleep = sum(sleep_hours) / len(sleep_hours) if sleep_hours else 0

        # Activity summary
        total_steps = 0
        for a in activity_data:
            if isinstance(a, dict):
                value = a.get("value", 0)
                total_steps += int(value) if isinstance(value, str) else value

        avg_daily_steps = total_steps / len(activity_data) if activity_data else 0

        return {
            "days_tracked": len(sleep_data),
            "avg_sleep_hours": round(avg_sleep, 1),
            "avg_daily_steps": int(avg_daily_steps),
            "sleep_quality": "good" if avg_sleep >= 7 else "fair" if avg_sleep >= 6.5 else "poor",
            "activity_level": "high" if avg_daily_steps >= 10000 else "moderate" if avg_daily_steps >= 7000 else "low",
        }

    def _check_health_alerts(
        self, sleep_data: List[Dict], activity_data: List[Dict]
    ) -> List[Dict]:
        """Flag health concerns"""
        alerts = []
        summary = self._summarize_health(sleep_data, activity_data)

        # Sleep alert
        if summary["avg_sleep_hours"] < 6:
            alerts.append({
                "type": "LOW_SLEEP",
                "value": summary["avg_sleep_hours"],
                "target": self.sleep_target,
                "message": f"Low sleep average: {summary['avg_sleep_hours']:.1f}h (target: {self.sleep_target}h)",
            })

        # Activity alert
        if summary["avg_daily_steps"] < 5000:
            alerts.append({
                "type": "LOW_ACTIVITY",
                "value": summary["avg_daily_steps"],
                "target": self.activity_target,
                "message": f"Low activity: {summary['avg_daily_steps']:.0f} steps/day (target: {self.activity_target})",
            })

        # Single bad night
        if sleep_data and len(sleep_data) > 0:
            last_sleep = sleep_data[-1]
            if isinstance(last_sleep, dict):
                last_hours = last_sleep.get("duration", 0) / 3600 if "duration" in last_sleep else 6
                if last_hours < 5:
                    alerts.append({
                        "type": "POOR_SLEEP_NIGHT",
                        "value": last_hours,
                        "message": f"Poor sleep last night: {last_hours:.1f} hours",
                    })

        return alerts

    async def export_to_notion(self, data: Dict[str, Any]) -> bool:
        """Export health summary to Notion"""
        if not self.has_notion:
            logger.warning("Notion not configured. Skipping export.")
            return False

        try:
            url = "https://api.notion.com/v1/pages"
            headers = {
                "Authorization": f"Bearer {NOTION_TOKEN}",
                "Notion-Version": "2024-06-15",
            }

            properties = {
                "Date": {
                    "type": "date",
                    "date": {
                        "start": datetime.now().date().isoformat(),
                    }
                },
                "Sleep (hrs)": {
                    "type": "number",
                    "number": data["summary"]["avg_sleep_hours"],
                },
                "Activity": {
                    "type": "number",
                    "number": data["summary"]["avg_daily_steps"],
                },
                "Status": {
                    "type": "select",
                    "select": {
                        "name": "Healthy" if not data["alerts"] else "Alert"
                    }
                }
            }

            payload = {
                "parent": {
                    "type": "database_id",
                    "database_id": NOTION_HEALTH_DB,
                },
                "properties": properties,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=15
                )
                response.raise_for_status()

            logger.info("Health data exported to Notion")
            return True

        except Exception as e:
            logger.error(f"Failed to export to Notion: {e}")
            return False


async def run_health_check() -> Dict[str, Any]:
    """
    Main entry point for health check cron.
    Called daily at 7am MST.
    """
    checker = HealthCheck()

    # Fetch last 7 days
    result = await checker.fetch_health_data(days=7)

    # Export to Notion
    await checker.export_to_notion(result)

    return {
        "status": "complete",
        "summary": result["summary"],
        "alerts": result["alerts"],
    }


if __name__ == "__main__":
    import asyncio
    result = asyncio.run(run_health_check())
    print(json.dumps(result, indent=2, default=str))
