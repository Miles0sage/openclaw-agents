#!/bin/bash
# OpenClaw Daily Cost & Status Report
# Runs daily at 9 AM via cron.
# Curls /admin/status, formats key metrics, sends to Telegram.

set -uo pipefail

GATEWAY_URL="http://localhost:18789"
ADMIN_STATUS_URL="${GATEWAY_URL}/admin/status"
ENV_FILE="./.env"
LOG_FILE="./logs/health.log"
GATEWAY_TOKEN=""

# --- Load env ---
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source <(grep -E '^(TELEGRAM_BOT_TOKEN|TELEGRAM_USER_ID|GATEWAY_AUTH_TOKEN)=' "$ENV_FILE")
fi

TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_USER_ID="${TELEGRAM_USER_ID:-}"
GATEWAY_TOKEN="${GATEWAY_AUTH_TOKEN:-}"

ts() {
    date '+%Y-%m-%d %H:%M:%S'
}

log() {
    echo "$(ts) [REPORT] $1" >> "$LOG_FILE"
}

send_telegram() {
    local message="$1"
    if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_USER_ID" ]; then
        log "WARN: Telegram not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_USER_ID)"
        echo "$message"
        return 1
    fi

    curl -s -X POST \
        "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\":\"${TELEGRAM_USER_ID}\",\"text\":$(echo "$message" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))'),\"parse_mode\":\"HTML\"}" \
        > /dev/null 2>&1

    return $?
}

# --- Fetch admin status ---
log "Fetching admin status..."

HEADERS=(-H "Content-Type: application/json")
if [ -n "$GATEWAY_TOKEN" ]; then
    HEADERS+=(-H "Authorization: Bearer ${GATEWAY_TOKEN}")
fi

STATUS_JSON=$(curl -s --max-time 15 "${HEADERS[@]}" "${ADMIN_STATUS_URL}" 2>/dev/null)

if [ -z "$STATUS_JSON" ] || ! echo "$STATUS_JSON" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
    MESSAGE="<b>OpenClaw Daily Report</b>
$(date '+%A, %B %d %Y')

Gateway is not responding or returned invalid data.
Manual check required: ${ADMIN_STATUS_URL}"

    log "ERROR: Could not fetch admin status"
    send_telegram "$MESSAGE"
    exit 1
fi

# --- Parse metrics with python3 ---
REPORT=$(echo "$STATUS_JSON" | python3 -c "
import sys, json

try:
    data = json.load(sys.stdin)
except:
    print('Failed to parse status JSON')
    sys.exit(1)

# Extract fields - adapt to actual API shape
# Try common structures
agents_active = data.get('agents', {}).get('active', data.get('activeAgents', data.get('agents_active', '?')))
messages_today = data.get('messages', {}).get('today', data.get('messagesToday', data.get('messages_today', '?')))
cost_today = data.get('costs', {}).get('today', data.get('costToday', data.get('cost_today', '?')))
cost_projected = data.get('costs', {}).get('projected', data.get('costProjected', data.get('cost_projected', '?')))
uptime = data.get('uptime', data.get('uptimeSeconds', '?'))
version = data.get('version', data.get('serviceVersion', '?'))

# Format cost values
def fmt_cost(v):
    if isinstance(v, (int, float)):
        return f'\${v:.2f}'
    if isinstance(v, str) and v.replace('.','',1).isdigit():
        return f'\${float(v):.2f}'
    return str(v) if v else '?'

def fmt_uptime(v):
    if isinstance(v, (int, float)):
        hours = int(v) // 3600
        mins = (int(v) % 3600) // 60
        return f'{hours}h {mins}m'
    return str(v) if v else '?'

print(f'''<b>OpenClaw Daily Report</b>

<b>Agents active:</b> {agents_active}
<b>Messages today:</b> {messages_today}
<b>Cost today:</b> {fmt_cost(cost_today)}
<b>Cost projected:</b> {fmt_cost(cost_projected)}
<b>Uptime:</b> {fmt_uptime(uptime)}
<b>Version:</b> {version}''')
" 2>&1)

if [ $? -ne 0 ]; then
    REPORT="<b>OpenClaw Daily Report</b>
$(date '+%A, %B %d %Y')

Status data retrieved but could not parse metrics.
Raw response (truncated):
<pre>$(echo "$STATUS_JSON" | head -c 500)</pre>"
fi

# Add date header
REPORT="$(echo "$REPORT" | head -1)
$(date '+%A, %B %d %Y')
$(echo "$REPORT" | tail -n +2)"

log "Sending daily report to Telegram"
send_telegram "$REPORT"
log "Daily report sent"
