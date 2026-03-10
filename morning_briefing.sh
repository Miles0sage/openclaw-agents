#!/bin/bash
# Morning Briefing — Runs daily via cron at 7am
# Checks: agency status, pending jobs, costs, health data
# Sends summary to Slack

set -euo pipefail

GATEWAY="http://localhost:18789"
AUTH="${GATEWAY_AUTH_TOKEN:?GATEWAY_AUTH_TOKEN must be set}"

echo "=== OpenClaw Morning Briefing ==="
echo "Date: $(date '+%Y-%m-%d %H:%M')"
echo ""

# 1. Agency status
echo "--- Agency Status ---"
JOBS=$(curl -s -H "X-Auth-Token: $AUTH" "$GATEWAY/api/jobs?status=all" 2>/dev/null || echo '{"jobs":[]}')
PENDING=$(echo "$JOBS" | python3 -c "import sys,json; jobs=json.load(sys.stdin).get('jobs',[]); print(len([j for j in jobs if j.get('status')=='pending']))" 2>/dev/null || echo "?")
RUNNING=$(echo "$JOBS" | python3 -c "import sys,json; jobs=json.load(sys.stdin).get('jobs',[]); print(len([j for j in jobs if j.get('status') in ('analyzing','running')]))" 2>/dev/null || echo "?")
DONE=$(echo "$JOBS" | python3 -c "import sys,json; jobs=json.load(sys.stdin).get('jobs',[]); print(len([j for j in jobs if j.get('status')=='done']))" 2>/dev/null || echo "?")
FAILED=$(echo "$JOBS" | python3 -c "import sys,json; jobs=json.load(sys.stdin).get('jobs',[]); print(len([j for j in jobs if j.get('status')=='failed']))" 2>/dev/null || echo "?")
echo "Pending: $PENDING | Running: $RUNNING | Done: $DONE | Failed: $FAILED"

# 2. Costs
echo ""
echo "--- Costs ---"
COSTS=$(curl -s -H "X-Auth-Token: $AUTH" "$GATEWAY/api/costs/summary" 2>/dev/null || echo '{}')
echo "$COSTS" | python3 -c "import sys,json; c=json.load(sys.stdin); print(f\"Today: \${c.get('today_usd',0):.4f} | Month: \${c.get('month_usd',0):.4f}\")" 2>/dev/null || echo "Cost data unavailable"

# 3. Performance metrics
echo ""
echo "--- 7-Day Performance ---"
METRICS=$(curl -s -H "X-Auth-Token: $AUTH" "$GATEWAY/api/metrics/summary?days=7" 2>/dev/null || echo '{}')
echo "$METRICS" | python3 -c "
import sys,json
m=json.load(sys.stdin)
if m.get('total_jobs',0) > 0:
    print(f\"Jobs: {m['total_jobs']} | Success: {m.get('success_rate',0)}% | Avg cost: \${m.get('avg_cost_usd',0):.4f}\")
else:
    print('No jobs in the last 7 days')
" 2>/dev/null || echo "Metrics unavailable"

# 4. Health data
echo ""
echo "--- Health ---"
HEALTH=$(curl -s -H "X-Auth-Token: $AUTH" "$GATEWAY/api/health/today" 2>/dev/null || echo '{"data":[]}')
echo "$HEALTH" | python3 -c "
import sys,json
h=json.load(sys.stdin)
data=h.get('data',[])
if data:
    latest=data[-1]
    parts=[]
    if 'steps' in latest: parts.append(f\"Steps: {latest['steps']}\")
    if 'sleep_hours' in latest: parts.append(f\"Sleep: {latest['sleep_hours']}h\")
    if 'heart_rate' in latest: parts.append(f\"HR: {latest['heart_rate']}bpm\")
    if 'active_calories' in latest: parts.append(f\"Calories: {latest['active_calories']}\")
    print(' | '.join(parts) if parts else 'Health data synced but no recognized fields')
else:
    print('No health data synced today')
" 2>/dev/null || echo "Health data unavailable"

# 5. Reactions triggers
echo ""
echo "--- Recent Reactions ---"
TRIGGERS=$(curl -s -H "X-Auth-Token: $AUTH" "$GATEWAY/api/reactions/triggers?limit=5" 2>/dev/null || echo '{"triggers":[]}')
echo "$TRIGGERS" | python3 -c "
import sys,json
t=json.load(sys.stdin).get('triggers',[])
if t:
    for tr in t[:5]:
        print(f\"  [{tr.get('timestamp','')[:16]}] {tr.get('rule_id','')}: {tr.get('action','')}\")
else:
    print('No recent reaction triggers')
" 2>/dev/null || echo "Triggers unavailable"

# 6. Build Slack summary
SUMMARY="☀️ *Morning Briefing — $(date '+%Y-%m-%d')*
📊 *Agency:* $PENDING pending, $RUNNING running, $DONE done, $FAILED failed
💰 *Costs:* $(echo "$COSTS" | python3 -c "import sys,json;c=json.load(sys.stdin);print(f\"\${c.get('today_usd',0):.2f} today, \${c.get('month_usd',0):.2f} this month\")" 2>/dev/null || echo "unavailable")
📈 *7-day:* $(echo "$METRICS" | python3 -c "import sys,json;m=json.load(sys.stdin);print(f\"{m.get('success_rate',0)}% success, {m.get('total_jobs',0)} jobs\")" 2>/dev/null || echo "no data")"

# Send to Slack
curl -s -X POST -H "X-Auth-Token: $AUTH" -H "Content-Type: application/json" \
  -d "{\"text\": $(echo "$SUMMARY" | python3 -c 'import sys,json;print(json.dumps(sys.stdin.read()))')}" \
  "$GATEWAY/slack/report/send" > /dev/null 2>&1 || true

echo ""
echo "=== Briefing sent to Slack ==="
