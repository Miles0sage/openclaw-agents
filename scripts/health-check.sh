#!/bin/bash
# OpenClaw Health Check Script
# Runs every 5 minutes via cron to ensure the gateway is healthy.
# Checks: gateway response, disk space, memory usage.
# Sends Telegram alerts on failures. Logs to ./logs/health.log.

set -uo pipefail

# --- Configuration ---
GATEWAY_URL="http://localhost:18789"
GATEWAY_SERVICE="openclaw-gateway.service"
LOG_DIR="./logs"
LOG_FILE="${LOG_DIR}/health.log"
ENV_FILE="./.env"
DISK_WARN_THRESHOLD=90
MEM_WARN_THRESHOLD=90
MAX_LOG_LINES=10000

# --- Load env for Telegram credentials ---
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source <(grep -E '^(TELEGRAM_BOT_TOKEN|TELEGRAM_USER_ID)=' "$ENV_FILE")
fi

TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_USER_ID="${TELEGRAM_USER_ID:-}"

# --- Ensure log directory exists ---
mkdir -p "$LOG_DIR"

# --- Helper: timestamp ---
ts() {
    date '+%Y-%m-%d %H:%M:%S'
}

# --- Helper: log message ---
log() {
    echo "$(ts) [HEALTH] $1" >> "$LOG_FILE"
}

# --- Helper: send Telegram alert ---
send_telegram() {
    local message="$1"
    if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_USER_ID" ]; then
        log "WARN: Telegram not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_USER_ID in .env)"
        return 1
    fi

    curl -s -X POST \
        "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\":\"${TELEGRAM_USER_ID}\",\"text\":\"${message}\",\"parse_mode\":\"HTML\"}" \
        > /dev/null 2>&1
}

# --- Helper: alert (log + telegram) ---
alert() {
    local level="$1"
    local message="$2"
    log "${level}: ${message}"
    send_telegram "<b>${level}</b>: ${message}"
}

# ============================================================
# CHECK 1: Gateway responding
# ============================================================
check_gateway() {
    local http_code
    http_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${GATEWAY_URL}" 2>/dev/null || echo "000")

    if [ "$http_code" = "000" ] || [ "$http_code" -ge 500 ] 2>/dev/null; then
        log "Gateway DOWN (HTTP ${http_code}). Attempting restart..."
        alert "ERROR" "OpenClaw gateway is DOWN (HTTP ${http_code}). Restarting ${GATEWAY_SERVICE}..."

        # Try systemd user service restart first, fall back to system
        if systemctl --user restart "$GATEWAY_SERVICE" 2>/dev/null; then
            sleep 5
            local retry_code
            retry_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${GATEWAY_URL}" 2>/dev/null || echo "000")
            if [ "$retry_code" != "000" ] && [ "$retry_code" -lt 500 ] 2>/dev/null; then
                alert "SUCCESS" "Gateway restarted successfully (HTTP ${retry_code})."
            else
                alert "ERROR" "Gateway restart FAILED. Still returning HTTP ${retry_code}. Manual intervention needed!"
            fi
        elif systemctl restart "$GATEWAY_SERVICE" 2>/dev/null; then
            sleep 5
            local retry_code
            retry_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${GATEWAY_URL}" 2>/dev/null || echo "000")
            if [ "$retry_code" != "000" ] && [ "$retry_code" -lt 500 ] 2>/dev/null; then
                alert "SUCCESS" "Gateway restarted successfully (HTTP ${retry_code})."
            else
                alert "ERROR" "Gateway restart FAILED. Still returning HTTP ${retry_code}. Manual intervention needed!"
            fi
        else
            alert "ERROR" "Could not restart ${GATEWAY_SERVICE} via systemctl. Manual intervention required!"
        fi
    else
        log "Gateway OK (HTTP ${http_code})"
    fi
}

# ============================================================
# CHECK 2: Disk space
# ============================================================
check_disk() {
    local usage
    usage=$(df / --output=pcent | tail -1 | tr -d ' %')

    if [ "$usage" -ge "$DISK_WARN_THRESHOLD" ]; then
        alert "WARNING" "Disk usage at ${usage}% (threshold: ${DISK_WARN_THRESHOLD}%). Free up space!"
    else
        log "Disk OK (${usage}% used)"
    fi
}

# ============================================================
# CHECK 3: Memory usage
# ============================================================
check_memory() {
    local total used pct
    total=$(free -m | awk '/^Mem:/ {print $2}')
    used=$(free -m | awk '/^Mem:/ {print $3}')

    if [ "$total" -gt 0 ]; then
        pct=$((used * 100 / total))
        if [ "$pct" -ge "$MEM_WARN_THRESHOLD" ]; then
            alert "WARNING" "Memory usage at ${pct}% (${used}MB / ${total}MB). Threshold: ${MEM_WARN_THRESHOLD}%."
        else
            log "Memory OK (${pct}% used, ${used}MB / ${total}MB)"
        fi
    fi
}

# ============================================================
# Trim log file if too large
# ============================================================
trim_log() {
    if [ -f "$LOG_FILE" ]; then
        local lines
        lines=$(wc -l < "$LOG_FILE")
        if [ "$lines" -gt "$MAX_LOG_LINES" ]; then
            tail -n "$((MAX_LOG_LINES / 2))" "$LOG_FILE" > "${LOG_FILE}.tmp"
            mv "${LOG_FILE}.tmp" "$LOG_FILE"
            log "Log trimmed from ${lines} to $((MAX_LOG_LINES / 2)) lines"
        fi
    fi
}

# ============================================================
# Main
# ============================================================
log "--- Health check started ---"
check_gateway
check_disk
check_memory
trim_log
log "--- Health check complete ---"
