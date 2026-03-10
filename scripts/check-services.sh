#!/usr/bin/env bash
# OpenClaw Service Status Checker
# Run: bash ./scripts/check-services.sh

set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BOLD}============================================${NC}"
echo -e "${BOLD}  OpenClaw Service Status Report${NC}"
echo -e "${BOLD}  $(date '+%Y-%m-%d %H:%M:%S %Z')${NC}"
echo -e "${BOLD}============================================${NC}"
echo ""

# ---- Systemd User Services ----
echo -e "${BOLD}--- Systemd User Services ---${NC}"
USER_SERVICES=(
    "openclaw-gateway.service"
    "openclaw-python-gateway.service"
    "openclaw-dashboard.service"
    "openclaw-jobs.service"
    "openclaw-assistant.service"
)

for svc in "${USER_SERVICES[@]}"; do
    status=$(systemctl --user is-active "$svc" 2>/dev/null || echo "not-found")
    enabled=$(systemctl --user is-enabled "$svc" 2>/dev/null || echo "not-found")
    if [ "$status" = "active" ]; then
        echo -e "  ${GREEN}[RUNNING]${NC}  $svc  (enabled: $enabled)"
    elif [ "$status" = "not-found" ]; then
        echo -e "  ${YELLOW}[MISSING]${NC}  $svc"
    else
        echo -e "  ${RED}[STOPPED]${NC}  $svc  (status: $status, enabled: $enabled)"
    fi
done
echo ""

# ---- System Services ----
echo -e "${BOLD}--- System Services ---${NC}"
SYSTEM_SERVICES=(
    "cloudflared.service"
    "docker.service"
)

for svc in "${SYSTEM_SERVICES[@]}"; do
    status=$(systemctl is-active "$svc" 2>/dev/null || echo "not-found")
    enabled=$(systemctl is-enabled "$svc" 2>/dev/null || echo "not-found")
    if [ "$status" = "active" ]; then
        echo -e "  ${GREEN}[RUNNING]${NC}  $svc  (enabled: $enabled)"
    elif [ "$status" = "not-found" ]; then
        echo -e "  ${YELLOW}[MISSING]${NC}  $svc"
    else
        echo -e "  ${RED}[STOPPED]${NC}  $svc  (status: $status, enabled: $enabled)"
    fi
done
echo ""

# ---- Linger Status ----
echo -e "${BOLD}--- Linger Status ---${NC}"
if [ -f /var/lib/systemd/linger/root ]; then
    echo -e "  ${GREEN}[OK]${NC}  Linger enabled for root"
else
    echo -e "  ${RED}[WARN]${NC}  Linger NOT enabled for root (run: loginctl enable-linger root)"
fi
echo ""

# ---- Port Usage ----
echo -e "${BOLD}--- Key Ports ---${NC}"
PORTS=(18789 18790 9000 8787 8080 8082 8083 8091 3000 9999)
for port in "${PORTS[@]}"; do
    listener=$(ss -tlnp "sport = :$port" 2>/dev/null | tail -n +2)
    if [ -n "$listener" ]; then
        proc=$(echo "$listener" | grep -oP 'users:\(\("\K[^"]+' | head -1)
        echo -e "  ${GREEN}[LISTEN]${NC}  :$port  ($proc)"
    else
        echo -e "  ${YELLOW}[  --  ]${NC}  :$port  (not listening)"
    fi
done
echo ""

# ---- Memory Usage per OpenClaw Process ----
echo -e "${BOLD}--- OpenClaw Process Memory ---${NC}"
ps aux --sort=-%mem | grep -E '(openclaw|gateway\.py|dashboard_api\.py|job_processor\.py|cloudflared|wrangler)' | grep -v grep | while read -r line; do
    user=$(echo "$line" | awk '{print $1}')
    pid=$(echo "$line" | awk '{print $2}')
    mem=$(echo "$line" | awk '{print $4}')
    rss=$(echo "$line" | awk '{print $6}')
    cmd=$(echo "$line" | awk '{for(i=11;i<=NF;i++) printf "%s ", $i; print ""}' | head -c 80)
    rss_mb=$(echo "scale=1; $rss/1024" | bc 2>/dev/null || echo "${rss}K")
    echo -e "  PID $pid  ${mem}% mem  ${rss_mb}MB  $cmd"
done
echo ""

echo -e "${BOLD}============================================${NC}"
echo -e "  To restart all:  systemctl --user restart openclaw-gateway openclaw-python-gateway openclaw-dashboard openclaw-jobs openclaw-assistant"
echo -e "  System tunnel:   sudo systemctl restart cloudflared"
echo -e "${BOLD}============================================${NC}"
