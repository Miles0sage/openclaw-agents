# PA Tools Integration Guide

## Overview

The PA Tools package provides **Week 1 automation** for Miles' personal assistant:
- **Finance Advisor**: Transaction tracking, spending alerts, budget management
- **Health Check**: Sleep/activity monitoring, health trends
- **News Aggregator**: AI news digests on AI/crypto/tech topics
- **Travel Agent**: Route optimization, flight/hotel search, itinerary management
- **Orchestrator**: Coordinates all tasks, manages scheduling

## Architecture

```
┌─ OpenClaw Gateway ────────────────────┐
│  gateway.py (FastAPI)                  │
│                                        │
│  ┌─ Cron Scheduler ────────────────┐   │
│  │ 7am:  morning_briefing          │   │
│  │ 6pm:  evening_finance_review    │   │
│  │ Thu8: thursday_soccer_prep      │   │
│  │ Sun5: sunday_weekly_summary     │   │
│  └──────────────────────────────────┘   │
│         ↓                                 │
│  ┌─ pa_tools.orchestrator ──────────┐   │
│  │ Coordinates all tasks             │   │
│  └──────────────────────────────────┘   │
│         ↓ (parallel async)              │
│  ┌─ Finance ─ Health ─ News ─ Travel ┐   │
│  │ Fetch → Analyze → Export → Alert  │   │
│  └──────────────────────────────────┘   │
│         ↓                                 │
│  Notion Databases (Finance, Health, etc) │
│  Email/Slack notifications              │
│  Event Engine logs                      │
└────────────────────────────────────────┘
```

## Installation

### 1. Install Dependencies

```bash
cd /root/openclaw
pip install httpx --break-system-packages  # Already installed likely
pip install notion-client --break-system-packages  # Optional, for Notion SDK
```

### 2. Configure Environment Variables

Create or update `.env` with these keys:

```bash
# Finance (optional - falls back to mock data)
PLAID_CLIENT_ID=your_plaid_client_id
PLAID_SECRET=your_plaid_secret
PLAID_ACCESS_TOKEN=your_plaid_access_token
PLAID_ENV=sandbox  # or production

# Health (optional)
FITBIT_ACCESS_TOKEN=your_fitbit_token
OURA_TOKEN=your_oura_token
GOOGLE_FIT_TOKEN=your_google_fit_token

# News (optional)
FEEDLY_TOKEN=your_feedly_token
READWISE_TOKEN=your_readwise_token

# Travel (optional)
GOOGLE_MAPS_API_KEY=your_google_maps_key
EXPEDIA_API_KEY=your_expedia_key

# Notion (required for export)
NOTION_TOKEN=your_notion_integration_token
NOTION_FINANCE_DB_ID=your_finance_db_uuid
NOTION_HEALTH_DB_ID=your_health_db_uuid
NOTION_TRAVEL_DB_ID=your_travel_db_uuid
```

**Important**: All APIs are **optional**. Tools fall back to mock data if not configured.

### 3. Set Up Notion Databases

Create 3 databases in your Notion workspace:

#### Finance Database
```
Columns:
- Date (date)
- Total Spent (number)
- Transactions (number)
- Status (select: "On Budget" / "Alert")
```

#### Health Database
```
Columns:
- Date (date)
- Sleep (hrs) (number)
- Activity (number - steps)
- Status (select: "Healthy" / "Alert")
```

#### Travel Database
```
Columns:
- Trip Name (title)
- Start Date (date)
- End Date (date)
- Activities (number)
```

**Get DB IDs**: Open Notion database → Copy URL → Extract UUID
Example: `https://www.notion.so/workspace/12345678-abcd-1234-...` → ID is `12345678abcd1234...`

### 4. Integrate with OpenClaw Gateway

The PA Tools crons are registered via a dedicated integration module. To enable:

Edit `./gateway.py` in the lifespan startup section (around line 119):

```python
# Add import at top
from pa_tools_cron import register_pa_tools_crons

# In lifespan startup, after initializing cron scheduler (around line 122)
try:
    cron = init_cron_scheduler()
    cron.start()
    logger.info(f"Cron scheduler initialized ({len(cron.list_jobs())} jobs)")

    # Register PA Tools crons
    await register_pa_tools_crons(cron)

except Exception as err:
    logger.error(f"Failed to initialize cron scheduler: {err}")
```

The `register_pa_tools_crons()` function handles all scheduling:
- 7am MST: Health + News briefing
- 6pm MST: Evening finance review
- Thursday 8pm MST: Soccer prep (requires location data)
- Sunday 5pm MST: Weekly summary (requires goal tracking)

### 5. Test Individual Tools

```bash
# Test finance tool
python3 -m pa_tools.finance

# Test health tool
python3 -m pa_tools.health

# Test news tool
python3 -m pa_tools.news

# Test travel tool
python3 -m pa_tools.travel

# Test orchestrator (all tools)
python3 -m pa_tools.orchestrator
```

## API Keys & Setup

### Plaid (Finance)
1. Go to https://plaid.com
2. Sign up for free tier
3. Link bank account in dashboard
4. Copy `CLIENT_ID`, `SECRET`, and `ACCESS_TOKEN`
5. Cost: $100/mo after trial

### Fitbit/Google Fit (Health)
1. Create Google Cloud project
2. Enable Google Fit API
3. Create OAuth2 credentials
4. Use `gws` CLI or `google-fit-mcp` to sync
5. Cost: FREE

### Oura Ring (Health - Sleep)
1. Buy Oura Ring Gen 3 (~$300 one-time)
2. Sync with app
3. Generate API token at https://cloud.ouraring.com
4. Cost: $6/mo subscription

### Feedly (News)
1. Go to https://feedly.com
2. Subscribe to feeds on topics Miles cares about
3. Generate API token
4. Cost: $10/mo (or free with ads)

### Google Maps (Travel)
1. Create Google Cloud project
2. Enable Distance Matrix API
3. Create API key
4. Cost: ~$5/1000 requests

## Usage Examples

### Run Morning Briefing

```python
import asyncio
from pa_tools.orchestrator import PAOrchestrator

async def main():
    orchestrator = PAOrchestrator()
    result = await orchestrator.morning_briefing()
    print(result)

asyncio.run(main())
```

### Fetch Finance Data Only

```python
import asyncio
from pa_tools.finance import FinanceAdvisor

async def main():
    advisor = FinanceAdvisor()
    data = await advisor.fetch_transactions(days=7)
    print(data["summary"])
    print(f"Alerts: {data['alerts']}")

asyncio.run(main())
```

### Optimize Travel Route

```python
import asyncio
from pa_tools.travel import TravelAgent

async def main():
    agent = TravelAgent()
    route = await agent.optimize_route(
        origin="123 Main St",
        stops=["Whole Foods Market", "Soccer Field", "Home"]
    )
    print(f"Distance: {route['distance_km']} km")
    print(f"Duration: {route['duration_hours']} hours")
    print(f"Maps: {route['maps_url']}")

asyncio.run(main())
```

## Week 1 Checklist

- [ ] Install pa_tools package
- [ ] Set up Notion databases (Finance, Health, Travel)
- [ ] Configure at least one API key (Plaid recommended for finance)
- [ ] Create `.env` file with API keys
- [ ] Test individual tools with mock data
- [ ] Integrate orchestrator with OpenClaw gateway
- [ ] Deploy and test cron jobs
- [ ] Verify Notion exports working

## Week 2-3 Enhancements

- Email notifications (Gmail MCP)
- Slack notifications
- Smart home integration (Home Assistant MCP)
- Calendar sync (Google Calendar API)
- Goal tracking
- Spending categories AI classification

## Week 4 Self-Improvement

- Reflexion: Learn from past notifications (what alerts actually matter?)
- A/B test thresholds (is $500/week the right budget?)
- Auto-adjust alerts based on Miles' behavior
- Predictive alerts (anomaly detection ML)

## Troubleshooting

### "Notion not configured" warning
**Fix**: Set `NOTION_TOKEN` and `NOTION_FINANCE_DB_ID` environment variables

### No transactions showing
**Fix**:
1. Check Plaid token is valid
2. Check bank account has recent transactions
3. Remove token and try mock data: `unset PLAID_ACCESS_TOKEN`

### "Low sleep" alert every day (false positive)
**Fix**: Adjust `sleep_target` in health.py or increase threshold

### Mock data instead of real data
**Fix**: Ensure API tokens in `.env` and confirm with: `echo $PLAID_ACCESS_TOKEN`

## Support

For issues:
1. Check tool logs: `tail -f /var/log/pa_tools.log`
2. Test with mock data first
3. Run individual tools to isolate problem
4. Check API status (Plaid, Fitbit, etc.)

## Next Steps

After Week 1, prioritize:
1. **Email management** (Gmail MCP) — Filter/archive rules
2. **Smart home** (Home Assistant) — Turn lights on/off based on schedule
3. **Relationship tracking** (Monica CRM) — Birthday reminders, contact sync
4. **Learning tracking** — Readwise highlights → Spaced repetition
