# PA Tools Deployment Guide

## Status: Week 1 MVP Ready

All four PA automation tools are complete and tested with mock data. Ready for production deployment.

**Files created**:
- `./pa_tools/finance/__init__.py` — Finance tracking + alerts
- `./pa_tools/health/__init__.py` — Sleep/activity monitoring
- `./pa_tools/news/__init__.py` — News digest aggregation
- `./pa_tools/travel/__init__.py` — Route optimization + booking stubs
- `./pa_tools/orchestrator.py` — Coordinates all tasks
- `./pa_tools_cron.py` — Gateway integration module

## Quick Start (5 minutes)

### 1. Test with Mock Data (No API Keys Needed)

```bash
# Test individual tools
cd ./
python3 -m pa_tools.finance
python3 -m pa_tools.health
python3 -m pa_tools.news
python3 -m pa_tools.travel

# Test all tools in parallel
python3 -m pa_tools

# Test cron integration (standalone)
python3 pa_tools_cron.py
```

All tools work with mock data by default. No API keys required to see it working.

### 2. Enable Gateway Integration

Edit `./gateway.py`:

**Find** (around line 20):
```python
from routers.shared import (
    CONFIG, metrics, logger,
    init_memory_manager, get_memory_manager,
    init_cron_scheduler, get_cron_scheduler,
```

**Add after** (still in the imports section):
```python
from pa_tools_cron import register_pa_tools_crons
```

**Find** (around line 119-125, in the lifespan function):
```python
    # Cron scheduler
    try:
        cron = init_cron_scheduler()
        cron.start()
        logger.info(f"Cron scheduler initialized ({len(cron.list_jobs())} jobs)")
```

**Change to**:
```python
    # Cron scheduler + PA Tools
    try:
        cron = init_cron_scheduler()
        cron.start()
        logger.info(f"Cron scheduler initialized ({len(cron.list_jobs())} jobs)")

        # Register PA Tools crons (7am briefing, 6pm finance, Thu 8pm soccer, Sun 5pm summary)
        await register_pa_tools_crons(cron)
```

### 3. Deploy & Verify

```bash
# Restart gateway (auto-reloads from systemd)
systemctl restart openclaw-gateway

# Check logs for PA crons
journalctl -u openclaw-gateway -f | grep "PA:"
```

You should see:
```
Scheduled: PA morning_briefing at 7am MST
Scheduled: PA evening_finance_review at 6pm MST
Scheduled: PA thursday_soccer_prep at Thursday 8pm MST
Scheduled: PA sunday_weekly_summary at Sunday 5pm MST
```

## Production Setup (30 minutes)

### 1. Create Notion Databases

Open your Notion workspace and create 3 databases:

**Finance Database**
- Name: Finance Tracker
- Columns:
  - Date (date)
  - Total Spent (number)
  - Transactions (number)
  - Status (select: "On Budget" / "Alert")
- Copy the database ID from the URL

**Health Database**
- Name: Health Tracker
- Columns:
  - Date (date)
  - Sleep (hrs) (number)
  - Activity (number — steps)
  - Status (select: "Healthy" / "Alert")

**Travel Database**
- Name: Travel Planner
- Columns:
  - Trip Name (title)
  - Start Date (date)
  - End Date (date)
  - Activities (number)

### 2. Set Up Environment Variables

Add to `./.env`:

```bash
# Notion (REQUIRED for data export)
NOTION_TOKEN=ntn_...
NOTION_FINANCE_DB_ID=xxxxxxxxxxxxx
NOTION_HEALTH_DB_ID=xxxxxxxxxxxxx
NOTION_TRAVEL_DB_ID=xxxxxxxxxxxxx

# Finance (optional — falls back to mock data)
PLAID_CLIENT_ID=your_plaid_client_id
PLAID_SECRET=your_plaid_secret
PLAID_ACCESS_TOKEN=your_plaid_access_token
PLAID_ENV=sandbox

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
SKYSCANNER_API_KEY=your_skyscanner_key
```

### 3. Test with Real API Keys

Once you've added API keys to `.env`, restart the gateway:

```bash
systemctl restart openclaw-gateway
```

The tools will now:
1. Try to fetch real data from APIs
2. Fall back to mock data if API fails or key is invalid
3. Export to Notion databases
4. Log all activity to the event engine

## API Key Setup (Optional)

### Plaid (Finance)
1. Go to https://plaid.com
2. Create a free account
3. Link your bank account
4. Copy CLIENT_ID, SECRET, ACCESS_TOKEN
5. Cost: $100/mo after trial (included in PA budget)

### Fitbit (Health)
1. Go to https://fitbit.com/setup
2. Create account and link tracker
3. Go to https://dev.fitbit.com/build/reference/web-api/
4. Create OAuth app
5. Cost: FREE

### Oura Ring (Health — Sleep)
1. Buy ring (~$300)
2. Generate token at https://cloud.ouraring.com
3. Cost: $6/mo subscription

### Feedly (News)
1. Go to https://feedly.com
2. Subscribe to feeds on AI, Crypto, Tech
3. Generate API token
4. Cost: $10/mo (or free with ads)

### Google Maps (Travel)
1. Create GCP project
2. Enable Distance Matrix API
3. Create API key
4. Cost: ~$5/1000 requests

## Architecture

```
OpenClaw Gateway (FastAPI)
    ↓ (startup)
Cron Scheduler (APScheduler)
    ↓ (async jobs)
PA Tools Orchestrator
    ├─ 7am: morning_briefing()
    │   ├─ Health → Sleep/Activity analysis
    │   └─ News → Daily digest
    │
    ├─ 6pm: evening_finance_review()
    │   └─ Finance → Spending alerts + budget status
    │
    ├─ Thu 8pm: thursday_soccer_prep()
    │   └─ Travel → Route optimization
    │
    └─ Sun 5pm: sunday_weekly_summary()
        └─ Aggregated weekly review
            ↓
        Notion Databases (export)
        Event Engine (logging)
```

## Monitoring

### View Live Crons
```bash
# SSH into gateway
ssh root@<your-vps-ip> -p 18789

# Check scheduler status
journalctl -u openclaw-gateway -f | grep PA

# View all scheduled jobs
curl http://localhost:8000/admin/crons
```

### Debug a Tool
```bash
# Test finance with real Plaid key (if configured)
NOTION_TOKEN=xxx NOTION_FINANCE_DB_ID=yyy python3 -m pa_tools.finance

# See what APIs are actually being used
python3 -c "
from pa_tools.finance import FinanceAdvisor
fa = FinanceAdvisor()
print(f'Plaid configured: {fa.has_plaid}')
print(f'Notion configured: {fa.has_notion}')
"
```

## Troubleshooting

### "ModuleNotFoundError: No module named 'pa_tools'"
**Fix**: Make sure you're running from `./`:
```bash
cd ./
python3 -m pa_tools.finance
```

### "Notion not configured" warning
**Fix**: Set `NOTION_TOKEN` and database IDs in `.env`
```bash
echo "NOTION_TOKEN=ntn_xxxxx" >> ./.env
systemctl restart openclaw-gateway
```

### Mock data instead of real data
**Fix**: Verify API tokens are in `.env` and valid:
```bash
source ./.env
echo "Plaid token: $PLAID_ACCESS_TOKEN"
echo "Notion token: $NOTION_TOKEN"
```

### Crons not running at scheduled times
**Fix**: Check timezone in gateway (defaults to MST):
```bash
journalctl -u openclaw-gateway -f | grep "scheduler"
```

## What's Next

### Week 2-3: Advanced Features
- Email notifications (Gmail MCP)
- Slack alerts
- Smart home integration
- Calendar sync
- Goal tracking

### Week 4: Self-Improvement
- Reflexion: Learn from past alerts
- A/B test alert thresholds
- Anomaly detection ML
- Auto-adjust budgets based on behavior

## Cost Summary

**Recurring Monthly**:
- Plaid: $100
- Oura Ring: $6
- Feedly: $10
- Google Maps: ~$5 (variable)
- **Total: ~$121/mo**

**One-Time**:
- Oura Ring: $300

**Alternative** (all-free stack):
- Replace Plaid with bank manual export ($0)
- Use Google Fit instead of Fitbit ($0)
- Use Feedly free tier with ads ($0)
- **Total: $0/mo (except Oura if wanted)**

## Support

For issues:
1. Test with mock data first: `python3 -m pa_tools.finance`
2. Check environment: `echo $NOTION_TOKEN`
3. Review logs: `journalctl -u openclaw-gateway -f`
4. Run standalone test: `python3 pa_tools_cron.py`

