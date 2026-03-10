"""
Finance Advisor Tool — Transaction analysis, categorization, anomaly detection

Week 1 MVP:
- Fetch transactions from Plaid API (or mock data)
- Categorize by spending pattern
- Alert on unusual spending
- Export to Notion Finance database
- Calculate weekly/monthly trends
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import httpx

logger = logging.getLogger(__name__)

# Configuration
PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID", "")
PLAID_SECRET = os.getenv("PLAID_SECRET", "")
PLAID_ENV = os.getenv("PLAID_ENV", "sandbox")  # sandbox or production
ACCESS_TOKEN = os.getenv("PLAID_ACCESS_TOKEN", "")

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_FINANCE_DB = os.getenv("NOTION_FINANCE_DB_ID", "")


class FinanceAdvisor:
    """
    Manage Miles' finances: track spending, categorize, alert on anomalies
    """

    def __init__(self):
        self.plaid_url = f"https://sandbox.plaid.com" if PLAID_ENV == "sandbox" else "https://production.plaid.com"
        self.has_plaid = bool(PLAID_CLIENT_ID and PLAID_SECRET and ACCESS_TOKEN)
        self.has_notion = bool(NOTION_TOKEN and NOTION_FINANCE_DB)

        # Spending thresholds (alert if exceeded in a week)
        self.weekly_budget = 500  # Miles' estimated weekly spend
        self.category_budgets = {
            "FOOD_AND_DRINK": 100,
            "TRANSPORTATION": 50,
            "SHOPPING": 150,
            "ENTERTAINMENT": 75,
            "UTILITIES": 30,
        }

    async def fetch_transactions(
        self, days: int = 7
    ) -> Dict[str, Any]:
        """
        Fetch transactions from Plaid for last N days.
        Falls back to mock data if Plaid not available.

        Returns:
            {
                "transactions": [...],
                "summary": {...},
                "alerts": [...],
            }
        """
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)

        if not self.has_plaid:
            logger.warning("Plaid not configured. Using mock data.")
            return await self._mock_transactions(start_date, end_date)

        try:
            return await self._fetch_plaid_transactions(
                start_date, end_date
            )
        except Exception as e:
            logger.error(f"Failed to fetch Plaid transactions: {e}")
            return await self._mock_transactions(start_date, end_date)

    async def _fetch_plaid_transactions(
        self, start_date, end_date
    ) -> Dict[str, Any]:
        """Fetch from Plaid API"""
        url = f"{self.plaid_url}/transactions/get"

        payload = {
            "client_id": PLAID_CLIENT_ID,
            "secret": PLAID_SECRET,
            "access_token": ACCESS_TOKEN,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "options": {
                "include_personal_finance_category": True,
                "sort_by": "datetime",
            }
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=15)
            response.raise_for_status()
            data = response.json()

        transactions = data.get("transactions", [])

        return {
            "transactions": transactions,
            "summary": self._summarize_transactions(transactions),
            "alerts": self._check_spending_alerts(transactions),
        }

    async def _mock_transactions(self, start_date, end_date) -> Dict[str, Any]:
        """Return mock spending data for testing"""
        mock_data = [
            {
                "transaction_id": "txn_001",
                "amount": 12.50,
                "merchant_name": "Whole Foods",
                "personal_finance_category": {"primary": "FOOD_AND_DRINK"},
                "date": (start_date + timedelta(days=1)).isoformat(),
                "iso_currency_code": "USD",
            },
            {
                "transaction_id": "txn_002",
                "amount": 85.00,
                "merchant_name": "Lyft",
                "personal_finance_category": {"primary": "TRANSPORTATION"},
                "date": (start_date + timedelta(days=2)).isoformat(),
                "iso_currency_code": "USD",
            },
            {
                "transaction_id": "txn_003",
                "amount": 45.99,
                "merchant_name": "Nike Store",
                "personal_finance_category": {"primary": "SHOPPING"},
                "date": (start_date + timedelta(days=3)).isoformat(),
                "iso_currency_code": "USD",
            },
            {
                "transaction_id": "txn_004",
                "amount": 156.00,
                "merchant_name": "Amazon",
                "personal_finance_category": {"primary": "SHOPPING"},
                "date": (start_date + timedelta(days=4)).isoformat(),
                "iso_currency_code": "USD",
            },
            {
                "transaction_id": "txn_005",
                "amount": 22.00,
                "merchant_name": "Regal Cinemas",
                "personal_finance_category": {"primary": "ENTERTAINMENT"},
                "date": (start_date + timedelta(days=5)).isoformat(),
                "iso_currency_code": "USD",
            },
        ]

        return {
            "transactions": mock_data,
            "summary": self._summarize_transactions(mock_data),
            "alerts": self._check_spending_alerts(mock_data),
        }

    def _summarize_transactions(self, transactions: List[Dict]) -> Dict[str, Any]:
        """Summarize spending by category"""
        categories = {}
        total = 0

        for txn in transactions:
            amount = txn.get("amount", 0)
            total += amount

            cat = txn.get("personal_finance_category", {}).get("primary", "OTHER")
            if cat not in categories:
                categories[cat] = {"count": 0, "total": 0}

            categories[cat]["count"] += 1
            categories[cat]["total"] += amount

        # Sort by spending
        sorted_cats = sorted(
            categories.items(),
            key=lambda x: x[1]["total"],
            reverse=True
        )

        return {
            "total_transactions": len(transactions),
            "total_spent": round(total, 2),
            "by_category": dict(sorted_cats),
            "avg_transaction": round(total / len(transactions), 2) if transactions else 0,
        }

    def _check_spending_alerts(self, transactions: List[Dict]) -> List[Dict]:
        """Flag unusual spending"""
        alerts = []

        # Check for high single transactions
        for txn in transactions:
            amount = txn.get("amount", 0)
            if amount > 150:
                alerts.append({
                    "type": "HIGH_TRANSACTION",
                    "amount": amount,
                    "merchant": txn.get("merchant_name", "Unknown"),
                    "message": f"High transaction: ${amount:.2f} at {txn.get('merchant_name')}",
                })

        # Check weekly budget
        summary = self._summarize_transactions(transactions)
        if summary["total_spent"] > self.weekly_budget:
            alerts.append({
                "type": "OVER_BUDGET",
                "amount": summary["total_spent"],
                "budget": self.weekly_budget,
                "message": f"Weekly spending ${summary['total_spent']:.2f} exceeds budget ${self.weekly_budget}",
            })

        return alerts

    async def export_to_notion(self, data: Dict[str, Any]) -> bool:
        """
        Export transaction summary to Notion database.
        Requires NOTION_TOKEN and NOTION_FINANCE_DB_ID
        """
        if not self.has_notion:
            logger.warning("Notion not configured. Skipping export.")
            return False

        try:
            # Create a page in the Notion database
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
                "Total Spent": {
                    "type": "number",
                    "number": data["summary"]["total_spent"],
                },
                "Transactions": {
                    "type": "number",
                    "number": data["summary"]["total_transactions"],
                },
                "Status": {
                    "type": "select",
                    "select": {
                        "name": "On Budget" if not data["alerts"] else "Alert"
                    }
                }
            }

            # Build content with alerts
            content = []
            if data["alerts"]:
                content.append({
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": "⚠️ Alerts"
                                }
                            }
                        ]
                    }
                })
                for alert in data["alerts"]:
                    content.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {
                                        "content": alert.get("message", "")
                                    }
                                }
                            ]
                        }
                    })

            payload = {
                "parent": {
                    "type": "database_id",
                    "database_id": NOTION_FINANCE_DB,
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

            logger.info("Finance data exported to Notion")
            return True

        except Exception as e:
            logger.error(f"Failed to export to Notion: {e}")
            return False


async def run_finance_check() -> Dict[str, Any]:
    """
    Main entry point for finance check cron.
    Called daily at 6pm MST (1am UTC+1).
    """
    advisor = FinanceAdvisor()

    # Fetch last 7 days
    result = await advisor.fetch_transactions(days=7)

    # Export to Notion
    await advisor.export_to_notion(result)

    # Log to event engine (if available)
    return {
        "status": "complete",
        "summary": result["summary"],
        "alerts": result["alerts"],
    }


if __name__ == "__main__":
    import asyncio
    result = asyncio.run(run_finance_check())
    print(json.dumps(result, indent=2, default=str))
