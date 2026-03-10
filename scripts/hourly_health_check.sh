#!/bin/bash
# OpenClaw Hourly Health Check
# Runs every hour via cron. Checks gateway health, restarts if needed,
# reports status to Slack.

LOG="./data/health_check.log"
TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M:%S UTC")

echo "[$TIMESTAMP] Health check started" >> "$LOG"

# 1. Check if gateway is running
if ! systemctl is-active --quiet openclaw-gateway; then
    echo "[$TIMESTAMP] ALERT: Gateway is DOWN — restarting" >> "$LOG"
    systemctl restart openclaw-gateway
    sleep 5
    if systemctl is-active --quiet openclaw-gateway; then
        echo "[$TIMESTAMP] Gateway restarted successfully" >> "$LOG"
        # Notify via gateway API
        curl -s -X POST http://localhost:18789/api/slack \
            -H "Content-Type: application/json" \
            -d '{"message": "⚠️ Gateway was down — auto-restarted by health check"}' \
            2>/dev/null || true
    else
        echo "[$TIMESTAMP] CRITICAL: Gateway restart FAILED" >> "$LOG"
    fi
else
    echo "[$TIMESTAMP] Gateway: OK" >> "$LOG"
fi

# 2. Check gateway responds to HTTP
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:18789/health 2>/dev/null || echo "000")
if [ "$HTTP_STATUS" != "200" ]; then
    echo "[$TIMESTAMP] ALERT: Gateway HTTP check failed (status=$HTTP_STATUS) — restarting" >> "$LOG"
    systemctl restart openclaw-gateway
    sleep 5
else
    echo "[$TIMESTAMP] Gateway HTTP: OK ($HTTP_STATUS)" >> "$LOG"
fi

# 3. Check disk space
DISK_USAGE=$(df /root --output=pcent | tail -1 | tr -d ' %')
if [ "$DISK_USAGE" -gt 90 ]; then
    echo "[$TIMESTAMP] ALERT: Disk usage at ${DISK_USAGE}%" >> "$LOG"
    # Clean old job worktrees
    find ./data/jobs/worktrees/ -maxdepth 1 -mtime +3 -type d -exec rm -rf {} + 2>/dev/null
    # Clean old log files
    find ./data/ -name "*.log" -mtime +7 -delete 2>/dev/null
    echo "[$TIMESTAMP] Cleaned old worktrees and logs" >> "$LOG"
fi

# 4. Check memory usage
MEM_AVAILABLE=$(free -m | awk '/^Mem:/ {print $7}')
if [ "$MEM_AVAILABLE" -lt 200 ]; then
    echo "[$TIMESTAMP] ALERT: Low memory (${MEM_AVAILABLE}MB available)" >> "$LOG"
fi

# 5. Trim health check log (keep last 500 lines)
if [ -f "$LOG" ]; then
    tail -500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

echo "[$TIMESTAMP] Health check completed" >> "$LOG"
