#!/bin/bash

# OpenClaw Dashboard API Installation Script
# Installs and configures the dashboard monitoring API

set -e

echo "=================================="
echo "OpenClaw Dashboard API Installer"
echo "=================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASHBOARD_DIR="./"
STATIC_DIR="/var/www/dashboard"
SERVICE_FILE="/etc/systemd/system/openclaw-dashboard.service"
ENV_FILE="$DASHBOARD_DIR/.dashboard.env"
ENV_TEMPLATE="$DASHBOARD_DIR/.dashboard.env.template"

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}❌ This script must be run as root${NC}"
   exit 1
fi

# Step 1: Install Python dependencies
echo -e "${BLUE}📦 Installing Python dependencies...${NC}"
python3 -m pip install --upgrade pip > /dev/null 2>&1 || true
python3 -m pip install fastapi uvicorn python-dotenv pydantic --quiet

if command -v pip3 &> /dev/null; then
    pip3 install --quiet fastapi uvicorn python-dotenv pydantic 2>/dev/null || \
    pip3 install --break-system-packages --quiet fastapi uvicorn python-dotenv pydantic
fi

echo -e "${GREEN}✅ Dependencies installed${NC}"

# Step 2: Create environment file
echo -e "${BLUE}⚙️  Setting up environment configuration...${NC}"

if [ ! -f "$ENV_FILE" ]; then
    if [ -f "$ENV_TEMPLATE" ]; then
        cp "$ENV_TEMPLATE" "$ENV_FILE"
        echo -e "${GREEN}✅ Environment file created: $ENV_FILE${NC}"
        echo -e "${YELLOW}⚠️  Review and update $ENV_FILE with your settings${NC}"
    else
        echo -e "${YELLOW}⚠️  Template not found, creating basic .env${NC}"
        cat > "$ENV_FILE" << 'EOF'
OPENCLAW_DASHBOARD_PORT=9000
OPENCLAW_DASHBOARD_PASSWORD=openclaw-dashboard-2026
OPENCLAW_DASHBOARD_TOKEN=moltbot-secure-token-2026
OPENCLAW_GATEWAY_PORT=18789
OPENCLAW_GATEWAY_HOST=localhost
OPENCLAW_GATEWAY_LOG_PATH=/tmp/openclaw-gateway.log
OPENCLAW_TUNNEL_LOG_PATH=/tmp/cloudflared-tunnel.log
OPENCLAW_CONFIG_PATH=./config.json
OPENCLAW_SECRETS_PATH=/tmp/openclaw_secrets.json
OPENCLAW_STATIC_DIR=/var/www/dashboard
EOF
    fi
else
    echo -e "${GREEN}✅ Environment file already exists: $ENV_FILE${NC}"
fi

# Step 3: Create static directory
echo -e "${BLUE}📁 Setting up static files directory...${NC}"
mkdir -p "$STATIC_DIR"
chmod 755 "$STATIC_DIR"
echo -e "${GREEN}✅ Static directory: $STATIC_DIR${NC}"

# Step 4: Create log directories
echo -e "${BLUE}📝 Setting up log files...${NC}"
touch /tmp/openclaw-gateway.log 2>/dev/null || true
touch /tmp/cloudflared-tunnel.log 2>/dev/null || true
chmod 644 /tmp/openclaw-*.log 2>/dev/null || true
echo -e "${GREEN}✅ Log files ready${NC}"

# Step 5: Create systemd service
echo -e "${BLUE}🔧 Setting up systemd service...${NC}"

if [ ! -f "$SERVICE_FILE" ]; then
    if [ -f "$DASHBOARD_DIR/openclaw-dashboard.service" ]; then
        cp "$DASHBOARD_DIR/openclaw-dashboard.service" "$SERVICE_FILE"
        echo -e "${GREEN}✅ Service file installed: $SERVICE_FILE${NC}"
    else
        echo -e "${YELLOW}⚠️  Service template not found${NC}"
    fi
else
    echo -e "${GREEN}✅ Service file already exists: $SERVICE_FILE${NC}"
fi

# Step 6: Verify Python installation
echo -e "${BLUE}🔍 Verifying installation...${NC}"

# Compile the Python module
python3 -m py_compile "$DASHBOARD_DIR/dashboard_api.py" 2>/dev/null && \
    echo -e "${GREEN}✅ Python module syntax check passed${NC}" || \
    echo -e "${RED}❌ Python module has syntax errors${NC}"

# Step 7: Test basic imports
python3 << 'PYEOF'
try:
    import fastapi
    import uvicorn
    import pydantic
    print("✅ All required modules imported successfully")
except ImportError as e:
    print(f"❌ Import error: {e}")
    exit(1)
PYEOF

# Step 8: Reload systemd
echo -e "${BLUE}🔄 Reloading systemd configuration...${NC}"
systemctl daemon-reload 2>/dev/null || true
echo -e "${GREEN}✅ Systemd reloaded${NC}"

# Step 9: Summary
echo ""
echo "=================================="
echo -e "${GREEN}✅ Installation Complete!${NC}"
echo "=================================="
echo ""
echo "📋 Next Steps:"
echo ""
echo "1. Review configuration:"
echo "   ${BLUE}nano $ENV_FILE${NC}"
echo ""
echo "2. Update token/password (recommended):"
echo "   Edit OPENCLAW_DASHBOARD_TOKEN and OPENCLAW_DASHBOARD_PASSWORD"
echo ""
echo "3. Enable auto-start (optional):"
echo "   ${BLUE}sudo systemctl enable openclaw-dashboard${NC}"
echo ""
echo "4. Start the dashboard:"
echo "   ${BLUE}sudo systemctl start openclaw-dashboard${NC}"
echo ""
echo "5. Verify it's running:"
echo "   ${BLUE}sudo systemctl status openclaw-dashboard${NC}"
echo ""
echo "6. View logs:"
echo "   ${BLUE}sudo journalctl -u openclaw-dashboard -f${NC}"
echo ""
echo "7. Test the API (after starting):"
echo "   ${BLUE}curl -H 'Authorization: Bearer moltbot-secure-token-2026' http://localhost:9000/api/status${NC}"
echo ""
echo "📚 Documentation: $DASHBOARD_DIR/DASHBOARD_API.md"
echo ""
