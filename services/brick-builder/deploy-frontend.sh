#!/bin/bash
# Deploy Brick Builder frontend from PC to VPS
# Run this after Claude Code finishes enhancing the frontend on PC

set -e

PC_USER="Miles"
PC_IP="100.67.6.27"
PC_BUILD_DIR="C:\\Users\\Miles\\brick-builder\\dist"
VPS_DIST_DIR="./services/brick-builder/frontend-dist"
TELEGRAM_BOT_TOKEN="8327486359:AAGECiQ1DsVUuBtrMgGzXnANhI_B9nfQZIQ"
TELEGRAM_CHAT_ID="8475962905"

send_telegram() {
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d chat_id="${TELEGRAM_CHAT_ID}" \
        -d parse_mode="Markdown" \
        -d text="$1" > /dev/null 2>&1
}

echo "[1/4] Building frontend on PC..."
ssh ${PC_USER}@${PC_IP} "cd C:\\Users\\Miles\\brick-builder && npm run build 2>&1" || {
    send_telegram "❌ *Brick Builder* frontend build FAILED on PC"
    exit 1
}

echo "[2/4] Copying dist from PC to VPS..."
mkdir -p "$VPS_DIST_DIR"
# Use scp with recursive copy
scp -r ${PC_USER}@${PC_IP}:"C:/Users/Miles/brick-builder/dist/*" "$VPS_DIST_DIR/" || {
    # Fallback: tar on PC, pipe to VPS
    ssh ${PC_USER}@${PC_IP} "powershell -NoProfile -Command \"tar -cf - -C 'C:\\Users\\Miles\\brick-builder\\dist' .\"" | tar -xf - -C "$VPS_DIST_DIR/"
}

echo "[3/4] Restarting brick-builder service..."
systemctl restart brick-builder

echo "[4/4] Verifying..."
sleep 2
HEALTH=$(curl -s http://localhost:8001/health)
if echo "$HEALTH" | grep -q '"ok"'; then
    FILE_COUNT=$(find "$VPS_DIST_DIR" -type f | wc -l)
    send_telegram "✅ *Brick Builder MVP* deployed!

🧱 Frontend: ${FILE_COUNT} files deployed
🤖 AI Backend: Running on port 8001
🔗 URL: http://<your-vps-ip>:8001

Features:
- 3D LEGO brick building (Three.js)
- AI Suggest / Complete / Describe
- Save & Load builds
- Undo/Redo, color picker, size selector

_Built autonomously while you were at work_"
    echo "Deploy complete! Telegram notification sent."
else
    send_telegram "⚠️ *Brick Builder* deployed but health check failed: ${HEALTH}"
    echo "Deploy done but health check issue."
fi
