#!/usr/bin/env python3
"""
Daily Automated Scanner — Daily betting system scan runner.

Runs at 4:30 PM ET (21:30 UTC) every day via cron. Scans:
  1. money_engine("dashboard") — quick opportunity summary
  2. betting_brain("find_value", {"sport": "nba"}) — NBA value plays
  3. money_engine("crypto") — crypto fear/greed signals

Sends results via Slack (full) and SMS (concise summary <500 chars).
Saves full report to data/betting/daily_reports/YYYY-MM-DD.json
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

# Load environment variables
try:
    from dotenv import load_dotenv
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    load_dotenv(env_file)
except Exception:
    pass

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("./data/betting/scan.log", mode="a"),
    ],
)
logger = logging.getLogger("daily_scan")


def ensure_directories():
    """Ensure data directories exist."""
    Path("./data/betting").mkdir(parents=True, exist_ok=True)
    Path("./data/betting/daily_reports").mkdir(parents=True, exist_ok=True)


def run_dashboard_scan() -> dict:
    """Run quick opportunity scan."""
    try:
        from money_engine import money_engine
        result_json = money_engine("dashboard")
        return json.loads(result_json)
    except Exception as e:
        logger.error(f"Dashboard scan failed: {e}")
        return {"error": str(e), "type": "dashboard"}


def run_nba_value_scan() -> dict:
    """Run NBA value analysis."""
    try:
        from betting_brain import betting_brain
        result_json = betting_brain("find_value", {"sport": "nba"})
        return json.loads(result_json)
    except Exception as e:
        logger.error(f"NBA value scan failed: {e}")
        return {"error": str(e), "type": "nba_value"}


def run_crypto_scan() -> dict:
    """Run crypto signals scan."""
    try:
        from money_engine import money_engine
        result_json = money_engine("crypto")
        return json.loads(result_json)
    except Exception as e:
        logger.error(f"Crypto scan failed: {e}")
        return {"error": str(e), "type": "crypto"}


def format_sms_summary(dashboard: dict, nba: dict, crypto: dict) -> str:
    """Format concise SMS summary (<500 chars)."""
    lines = []

    # Dashboard picks
    picks = dashboard.get("picks", [])
    if picks:
        lines.append(f"Daily Scan: {len(picks)} signals")
        for pick in picks[:2]:
            signal = pick.get("signal", "UNKNOWN")
            detail = pick.get("detail", "")[:50]
            lines.append(f"  • {signal}: {detail}")

    # NBA value
    if not nba.get("error"):
        picks = nba.get("top_picks", [])
        if picks:
            lines.append(f"NBA: {len(picks)} value plays")

    # Crypto
    if not crypto.get("error"):
        fg = crypto.get("fear_greed", {})
        signal = fg.get("signal", "HOLD")
        index = fg.get("index", "?")
        lines.append(f"Crypto: Fear/Greed {signal} ({index})")

    summary = "\n".join(lines)
    if len(summary) > 450:
        summary = summary[:447] + "..."
    return summary


def format_slack_summary(dashboard: dict, nba: dict, crypto: dict) -> str:
    """Format detailed Slack message."""
    blocks = []

    blocks.append("*Daily Betting Scan Report*")
    blocks.append(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    blocks.append("")

    # Dashboard section
    if not dashboard.get("error"):
        picks = dashboard.get("picks", [])
        blocks.append(f"*Dashboard Summary*: {len(picks)} signals found")
        for pick in picks[:5]:
            signal = pick.get("signal", "?")
            detail = pick.get("detail", "")
            action = pick.get("action", "")
            blocks.append(f"  • {signal}: {detail}")
            if action:
                blocks.append(f"    Action: {action}")
    else:
        blocks.append(f"Dashboard Error: {dashboard.get('error')}")

    blocks.append("")

    # NBA section
    if not nba.get("error"):
        picks = nba.get("top_picks", [])
        blocks.append(f"*NBA Value Plays*: {len(picks)} plays identified")
        for pick in picks[:3]:
            game = pick.get("game", "?")
            pick_type = pick.get("pick_type", "?")
            ev = pick.get("expected_value", 0)
            blocks.append(f"  • {game}: {pick_type} (EV: {ev}%)")
    else:
        blocks.append(f"NBA Error: {nba.get('error')}")

    blocks.append("")

    # Crypto section
    if not crypto.get("error"):
        fg = crypto.get("fear_greed", {})
        signal = fg.get("signal", "HOLD")
        index = fg.get("index", "?")
        classification = fg.get("classification", "?")
        reasoning = fg.get("reasoning", "")
        blocks.append(f"*Crypto Signals*")
        blocks.append(f"  Fear/Greed Index: {index} ({classification})")
        blocks.append(f"  Signal: {signal}")
        if reasoning:
            blocks.append(f"  Action: {reasoning}")
    else:
        blocks.append(f"Crypto Error: {crypto.get('error')}")

    blocks.append("")
    blocks.append("Run `money_engine('scan')` for full detailed report.")

    return "\n".join(blocks)


def send_sms_result(summary: str):
    """Send SMS via agent_tools._send_sms"""
    try:
        from agent_tools import _send_sms

        phone = os.getenv("MILES_PHONE_NUMBER")
        if not phone:
            logger.warning("MILES_PHONE_NUMBER not set in .env — skipping SMS")
            return

        result = _send_sms(phone, summary)
        logger.info(f"SMS sent: {result}")
    except Exception as e:
        logger.error(f"Failed to send SMS: {e}")


def send_slack_result(summary: str):
    """Send Slack message via agent_tools._send_slack_message"""
    try:
        from agent_tools import _send_slack_message

        result = _send_slack_message(summary)
        logger.info(f"Slack sent: {result}")
    except Exception as e:
        logger.error(f"Failed to send Slack: {e}")


def save_report(dashboard: dict, nba: dict, crypto: dict):
    """Save full report to data/betting/daily_reports/YYYY-MM-DD.json"""
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        report_path = f"./data/betting/daily_reports/{today}.json"

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "date": today,
            "dashboard": dashboard,
            "nba_value": nba,
            "crypto": crypto,
        }

        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        logger.info(f"Report saved: {report_path}")
    except Exception as e:
        logger.error(f"Failed to save report: {e}")


def main():
    """Run all scans and send results."""
    logger.info("=" * 70)
    logger.info("Daily Betting Scan Starting")
    logger.info("=" * 70)

    ensure_directories()

    # Run all scans (each handles its own errors)
    logger.info("Running dashboard scan...")
    dashboard = run_dashboard_scan()

    logger.info("Running NBA value scan...")
    nba = run_nba_value_scan()

    logger.info("Running crypto scan...")
    crypto = run_crypto_scan()

    # Save full report
    logger.info("Saving report...")
    save_report(dashboard, nba, crypto)

    # Format and send results
    logger.info("Formatting and sending results...")
    sms_summary = format_sms_summary(dashboard, nba, crypto)
    slack_summary = format_slack_summary(dashboard, nba, crypto)

    logger.info(f"SMS Summary:\n{sms_summary}")
    logger.info(f"Slack Summary:\n{slack_summary}")

    # Send via Slack (always)
    send_slack_result(slack_summary)

    # Send via SMS (if phone number is configured)
    if os.getenv("MILES_PHONE_NUMBER"):
        send_sms_result(sms_summary)
    else:
        logger.info("SMS disabled — set MILES_PHONE_NUMBER in .env to enable")

    logger.info("=" * 70)
    logger.info("Daily Scan Complete")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
