#!/bin/bash
# One-time setup script for OpenClaw health monitoring.
# Run this script to:
#   1. Make monitoring scripts executable
#   2. Install crontab entries
#   3. Verify Telegram connectivity
#   4. Create required directories

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== OpenClaw Health Monitoring Setup ==="

# 1. Make scripts executable
echo "[1/4] Making scripts executable..."
chmod +x "${SCRIPT_DIR}/health-check.sh"
chmod +x "${SCRIPT_DIR}/rotate-logs.sh"
chmod +x "${SCRIPT_DIR}/daily-report.sh"
echo "  Done."

# 2. Create required directories
echo "[2/4] Creating directories..."
mkdir -p ./logs
mkdir -p /tmp/openclaw
echo "  Done."

# 3. Install crontab
echo "[3/4] Installing crontab entries..."

# Preserve existing crontab, add our entries
EXISTING=$(crontab -l 2>/dev/null || true)

# Check if our entries already exist
if echo "$EXISTING" | grep -q "health-check.sh"; then
    echo "  Crontab entries already exist. Skipping."
else
    NEW_CRONTAB="${EXISTING}

# --- OpenClaw Health Monitoring ---
# Health check every 5 minutes
*/5 * * * * ./scripts/health-check.sh >> ./logs/health-cron.log 2>&1
# Log rotation daily at midnight
0 0 * * * ./scripts/rotate-logs.sh >> ./logs/rotate-cron.log 2>&1
# Daily cost report at 9 AM
0 9 * * * ./scripts/daily-report.sh >> ./logs/report-cron.log 2>&1
# --- End OpenClaw Health Monitoring ---
"
    echo "$NEW_CRONTAB" | crontab -
    echo "  Crontab installed. Current entries:"
    crontab -l
fi

# 4. Check Telegram config
echo "[4/4] Checking Telegram configuration..."
source <(grep -E '^(TELEGRAM_BOT_TOKEN|TELEGRAM_USER_ID)=' ./.env 2>/dev/null || true)

if [ -z "${TELEGRAM_USER_ID:-}" ]; then
    echo ""
    echo "  WARNING: TELEGRAM_USER_ID is not set in ./.env"
    echo ""
    echo "  To find your Telegram user/chat ID:"
    echo "    1. Send any message to your bot on Telegram"
    echo "    2. Run:"
    echo "       curl -s 'https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates' | python3 -m json.tool"
    echo "    3. Look for 'chat': {'id': 123456789, ...}"
    echo "    4. Add to ./.env:"
    echo "       TELEGRAM_USER_ID=123456789"
    echo ""
else
    echo "  Telegram bot token: set"
    echo "  Telegram user ID: ${TELEGRAM_USER_ID}"
    # Test send
    echo "  Sending test message..."
    RESULT=$(curl -s -X POST \
        "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\":\"${TELEGRAM_USER_ID}\",\"text\":\"OpenClaw health monitoring activated. You will receive alerts here.\"}" 2>&1)
    if echo "$RESULT" | grep -q '"ok":true'; then
        echo "  Test message sent successfully!"
    else
        echo "  WARNING: Test message failed: $RESULT"
    fi
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Monitoring schedule:"
echo "  - Health check:  every 5 minutes"
echo "  - Log rotation:  daily at 00:00"
echo "  - Cost report:   daily at 09:00"
echo ""
echo "Logs:"
echo "  - Health:  ./logs/health.log"
echo "  - Cron:    ./logs/health-cron.log"
echo "  - Rotate:  ./logs/rotate-cron.log"
echo "  - Report:  ./logs/report-cron.log"
