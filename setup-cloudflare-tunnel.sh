#!/bin/bash

#############################################
# Cloudflare Tunnel Setup for OpenClaw
# One-command installer
#############################################

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "🌐 Cloudflare Tunnel Setup for OpenClaw"
echo "========================================"
echo -e "${NC}"
echo ""

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo -e "${YELLOW}⚠️  This script needs sudo access for service installation${NC}"
   echo "   Run with: sudo ./setup-cloudflare-tunnel.sh"
   echo "   Or the script will prompt for sudo when needed"
   echo ""
fi

# Check if cloudflared is installed
if ! command -v cloudflared &> /dev/null; then
    echo -e "${YELLOW}📦 cloudflared not found - installing...${NC}"

    # Download latest release
    wget -q --show-progress https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64

    # Make executable
    chmod +x cloudflared-linux-amd64

    # Move to PATH
    sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared

    echo -e "${GREEN}✅ cloudflared installed${NC}"
else
    echo -e "${GREEN}✅ cloudflared already installed${NC}"
    cloudflared --version
fi

echo ""
echo -e "${BLUE}🔑 Step 1: Login to Cloudflare${NC}"
echo "   Your browser will open to authenticate"
echo "   Select the domain you want to use"
echo ""
read -p "Press Enter to continue..."

cloudflared tunnel login

if [ ! -f ~/.cloudflared/cert.pem ]; then
    echo -e "${RED}❌ Login failed - cert.pem not found${NC}"
    echo "   Please try again"
    exit 1
fi

echo -e "${GREEN}✅ Successfully logged in${NC}"
echo ""

# Get tunnel name
echo -e "${BLUE}🔧 Step 2: Create Tunnel${NC}"
read -p "Enter tunnel name [openclaw]: " TUNNEL_NAME
TUNNEL_NAME=${TUNNEL_NAME:-openclaw}

# Check if tunnel already exists
if cloudflared tunnel list 2>/dev/null | grep -q "$TUNNEL_NAME"; then
    echo -e "${YELLOW}⚠️  Tunnel '$TUNNEL_NAME' already exists${NC}"
    read -p "Use existing tunnel? (y/n) [y]: " USE_EXISTING
    USE_EXISTING=${USE_EXISTING:-y}

    if [[ ! $USE_EXISTING =~ ^[Yy]$ ]]; then
        read -p "Enter a different tunnel name: " TUNNEL_NAME
        cloudflared tunnel create $TUNNEL_NAME
    fi
else
    cloudflared tunnel create $TUNNEL_NAME
fi

echo ""
echo -e "${BLUE}📋 Step 3: Get Tunnel ID${NC}"
TUNNEL_ID=$(cloudflared tunnel list 2>/dev/null | grep "$TUNNEL_NAME" | head -1 | awk '{print $1}')

if [ -z "$TUNNEL_ID" ]; then
    echo -e "${RED}❌ Could not find tunnel ID${NC}"
    echo "   Available tunnels:"
    cloudflared tunnel list
    exit 1
fi

echo -e "${GREEN}✅ Tunnel ID: $TUNNEL_ID${NC}"
echo ""

# Get domain info
echo -e "${BLUE}🌍 Step 4: Configure DNS${NC}"
echo ""
echo "Available domains in your Cloudflare account:"
cloudflared tunnel list 2>&1 | grep -i "zone" || echo "   (Run 'cloudflared tunnel list' to see domains)"
echo ""
read -p "Enter your domain (e.g., example.com): " DOMAIN

if [ -z "$DOMAIN" ]; then
    echo -e "${RED}❌ Domain is required${NC}"
    exit 1
fi

read -p "Enter subdomain [openclaw]: " SUBDOMAIN
SUBDOMAIN=${SUBDOMAIN:-openclaw}

FULL_DOMAIN="${SUBDOMAIN}.${DOMAIN}"

echo ""
echo -e "${YELLOW}📡 Creating DNS record for: $FULL_DOMAIN${NC}"
cloudflared tunnel route dns $TUNNEL_NAME $FULL_DOMAIN

echo -e "${GREEN}✅ DNS configured${NC}"
echo ""

# Create config file
echo -e "${BLUE}📝 Step 5: Creating Configuration${NC}"
mkdir -p ~/.cloudflared

# Check if OpenClaw is running and get port
OPENCLAW_PORT=18789
if ! curl -s http://localhost:$OPENCLAW_PORT/ >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  OpenClaw gateway not responding on port $OPENCLAW_PORT${NC}"
    read -p "Enter OpenClaw gateway port [$OPENCLAW_PORT]: " CUSTOM_PORT
    OPENCLAW_PORT=${CUSTOM_PORT:-$OPENCLAW_PORT}
fi

cat > ~/.cloudflared/config.yml << EOF
# OpenClaw Cloudflare Tunnel Configuration
tunnel: $TUNNEL_NAME
credentials-file: /root/.cloudflared/${TUNNEL_ID}.json

# Tunnel settings
originRequest:
  connectTimeout: 30s
  noTLSVerify: true

# Ingress rules (routes)
ingress:
  # Main gateway
  - hostname: $FULL_DOMAIN
    service: http://localhost:$OPENCLAW_PORT
    originRequest:
      noTLSVerify: true

  # WebSocket endpoint
  - hostname: $FULL_DOMAIN
    path: /ws
    service: ws://localhost:$OPENCLAW_PORT/ws
    originRequest:
      noTLSVerify: true

  # Cline integration
  - hostname: $FULL_DOMAIN
    path: /api/cline/*
    service: http://localhost:$OPENCLAW_PORT
    originRequest:
      noTLSVerify: true

  # API endpoints
  - hostname: $FULL_DOMAIN
    path: /api/*
    service: http://localhost:$OPENCLAW_PORT
    originRequest:
      noTLSVerify: true

  # Catch-all (return 404)
  - service: http_status:404
EOF

echo -e "${GREEN}✅ Configuration created at ~/.cloudflared/config.yml${NC}"
echo ""

# Test tunnel before installing service
echo -e "${BLUE}🧪 Step 6: Testing Tunnel${NC}"
echo "   Starting tunnel in test mode (5 seconds)..."
echo ""

timeout 5s cloudflared tunnel run $TUNNEL_NAME 2>&1 | head -20 || true

echo ""
echo -e "${YELLOW}⚠️  Check for any errors above${NC}"
read -p "Did the tunnel connect successfully? (y/n) [y]: " TUNNEL_OK
TUNNEL_OK=${TUNNEL_OK:-y}

if [[ ! $TUNNEL_OK =~ ^[Yy]$ ]]; then
    echo -e "${RED}❌ Please fix errors and try again${NC}"
    echo ""
    echo "Common issues:"
    echo "  - OpenClaw gateway not running: cd ./ && python3 gateway.py &"
    echo "  - Wrong port: Check that gateway is on port $OPENCLAW_PORT"
    echo "  - Firewall: Ensure localhost:$OPENCLAW_PORT is accessible"
    exit 1
fi

echo ""

# Install as service
echo -e "${BLUE}🚀 Step 7: Installing as System Service${NC}"

# Stop any existing service
sudo systemctl stop cloudflared 2>/dev/null || true

# Install service
sudo cloudflared service install

# Start and enable service
sudo systemctl start cloudflared
sudo systemctl enable cloudflared

echo -e "${GREEN}✅ Service installed and started${NC}"
echo ""

# Wait a moment for service to start
sleep 3

# Check service status
echo -e "${BLUE}📊 Step 8: Checking Service Status${NC}"
sudo systemctl status cloudflared --no-pager | head -15

echo ""

# Final test
echo -e "${BLUE}🧪 Step 9: Final Connectivity Test${NC}"
echo "   Testing https://$FULL_DOMAIN/"
echo ""

sleep 5  # Wait for DNS to propagate

if curl -s -o /dev/null -w "%{http_code}" https://$FULL_DOMAIN/ | grep -q "200"; then
    echo -e "${GREEN}✅ Successfully connected!${NC}"
else
    echo -e "${YELLOW}⚠️  Connection test inconclusive${NC}"
    echo "   DNS may still be propagating (can take a few minutes)"
    echo "   Try manually: curl https://$FULL_DOMAIN/"
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}🎉 Cloudflare Tunnel Setup Complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${BLUE}📝 Your Configuration:${NC}"
echo ""
echo "   Tunnel Name:  $TUNNEL_NAME"
echo "   Tunnel ID:    $TUNNEL_ID"
echo "   Public URL:   https://$FULL_DOMAIN/"
echo "   WebSocket:    wss://$FULL_DOMAIN/ws"
echo "   Local Port:   $OPENCLAW_PORT"
echo ""
echo -e "${BLUE}🎯 Access Points:${NC}"
echo ""
echo "   Gateway:      https://$FULL_DOMAIN/"
echo "   Agents:       https://$FULL_DOMAIN/api/agents"
echo "   Cline Poll:   https://$FULL_DOMAIN/api/cline/poll"
echo "   WebSocket:    wss://$FULL_DOMAIN/ws"
echo ""
echo -e "${BLUE}📊 Service Management:${NC}"
echo ""
echo "   Status:       sudo systemctl status cloudflared"
echo "   Restart:      sudo systemctl restart cloudflared"
echo "   Logs:         sudo journalctl -u cloudflared -f"
echo "   Stop:         sudo systemctl stop cloudflared"
echo ""
echo -e "${BLUE}🧪 Test Commands:${NC}"
echo ""
echo "   # Test from anywhere"
echo "   curl https://$FULL_DOMAIN/"
echo ""
echo "   # Test Cline integration"
echo "   curl https://$FULL_DOMAIN/api/cline/status"
echo ""
echo "   # WebSocket test"
echo "   websocat wss://$FULL_DOMAIN/ws"
echo ""
echo -e "${BLUE}🔒 Security Recommendations:${NC}"
echo ""
echo "   1. Enable Cloudflare Zero Trust access control"
echo "   2. Set up rate limiting in Cloudflare dashboard"
echo "   3. Enable bot protection"
echo "   4. Configure IP allowlists"
echo ""
echo "   Guide: ./CLOUDFLARE-TUNNEL-SETUP.md"
echo ""
echo -e "${BLUE}📚 Documentation:${NC}"
echo ""
echo "   Full guide:   cat ./CLOUDFLARE-TUNNEL-SETUP.md"
echo "   Config file:  cat ~/.cloudflared/config.yml"
echo ""
echo -e "${GREEN}🎊 Your OpenClaw gateway is now globally accessible!${NC}"
echo ""
