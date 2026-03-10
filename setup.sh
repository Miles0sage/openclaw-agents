#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# OpenClaw v4.2 — One-Command Setup
# Run: curl -sSL https://raw.githubusercontent.com/your-repo/openclaw/main/setup.sh | bash
# Or:  ./setup.sh
# ═══════════════════════════════════════════════════════════════

set -e

echo ""
echo "  ╔═══════════════════════════════════════╗"
echo "  ║       OpenClaw v4.2 Setup             ║"
echo "  ║   AI Agent System + Personal Assistant║"
echo "  ╚═══════════════════════════════════════╝"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ─── Check prerequisites ───
info "Checking prerequisites..."

command -v python3 >/dev/null 2>&1 || error "Python 3 is required. Install it first."
command -v pip3 >/dev/null 2>&1 || command -v pip >/dev/null 2>&1 || error "pip is required. Install it first."

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
success "Python $PYTHON_VERSION found"

# Optional: Docker check
if command -v docker >/dev/null 2>&1; then
    success "Docker found (optional — for containerized deployment)"
    HAS_DOCKER=true
else
    warn "Docker not found (optional — you can run without it)"
    HAS_DOCKER=false
fi

# ─── Configuration Wizard ───
echo ""
echo "═══ Configuration Wizard ═══"
echo ""
echo "I'll ask a few questions to set up your OpenClaw instance."
echo "You can change these later in .env"
echo ""

# Check if .env already exists
if [ -f .env ]; then
    echo "Found existing .env file."
    read -p "Use existing config? (y/n) [y]: " USE_EXISTING
    USE_EXISTING=${USE_EXISTING:-y}
    if [ "$USE_EXISTING" = "y" ]; then
        info "Using existing .env"
    fi
fi

if [ ! -f .env ] || [ "$USE_EXISTING" != "y" ]; then
    cp .env.example .env

    echo ""
    echo "Which AI providers do you have API keys for?"
    echo "  1. Anthropic (Claude) — recommended for complex tasks"
    echo "  2. DeepSeek — recommended for cheap tasks (~100x cheaper)"
    echo "  3. Google Gemini — good free tier"
    echo "  4. OpenAI — optional"
    echo ""

    read -p "Anthropic API key (or press Enter to skip): " ANTHROPIC_KEY
    if [ -n "$ANTHROPIC_KEY" ]; then
        sed -i "s|ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=$ANTHROPIC_KEY|" .env
        success "Anthropic key set"
    fi

    read -p "DeepSeek API key (or press Enter to skip): " DEEPSEEK_KEY
    if [ -n "$DEEPSEEK_KEY" ]; then
        sed -i "s|DEEPSEEK_API_KEY=.*|DEEPSEEK_API_KEY=$DEEPSEEK_KEY|" .env
        success "DeepSeek key set"
    fi

    read -p "Gemini API key (or press Enter to skip): " GEMINI_KEY
    if [ -n "$GEMINI_KEY" ]; then
        sed -i "s|GEMINI_API_KEY=.*|GEMINI_API_KEY=$GEMINI_KEY|" .env
        success "Gemini key set"
    fi

    echo ""
    echo "Messaging (choose one or more):"

    read -p "Telegram Bot Token (or press Enter to skip): " TG_TOKEN
    if [ -n "$TG_TOKEN" ]; then
        sed -i "s|TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=$TG_TOKEN|" .env
        read -p "Your Telegram User ID: " TG_USER
        sed -i "s|TELEGRAM_USER_ID=.*|TELEGRAM_USER_ID=$TG_USER|" .env
        success "Telegram configured"
    fi

    # Generate auth token
    AUTH_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s|GATEWAY_AUTH_TOKEN=.*|GATEWAY_AUTH_TOKEN=$AUTH_TOKEN|" .env
    success "Auth token generated"

    echo ""
    success "Configuration saved to .env"
fi

# ─── Install dependencies ───
echo ""
info "Installing Python dependencies..."

if [ -f requirements.txt ]; then
    pip3 install -r requirements.txt --quiet 2>/dev/null || pip3 install -r requirements.txt --quiet --break-system-packages 2>/dev/null
    success "Python dependencies installed"
else
    warn "No requirements.txt found — skipping pip install"
fi

# ─── Create data directories ───
info "Creating data directories..."
mkdir -p data/sessions data/jobs data/models data/reflections logs
success "Data directories ready"

# ─── Choose deployment method ───
echo ""
echo "═══ Deployment ═══"
echo ""

if [ "$HAS_DOCKER" = true ]; then
    echo "  1. Docker Compose (recommended — isolated, easy to manage)"
    echo "  2. Direct (run gateway.py directly — simpler, for development)"
    echo ""
    read -p "Choose deployment method [1]: " DEPLOY_METHOD
    DEPLOY_METHOD=${DEPLOY_METHOD:-1}
else
    DEPLOY_METHOD=2
fi

if [ "$DEPLOY_METHOD" = "1" ]; then
    info "Starting with Docker Compose..."
    docker compose up -d
    success "OpenClaw is running!"
    echo ""
    echo "  Gateway:   http://localhost:18789"
    echo "  Dashboard: http://localhost:9000"
    echo "  Health:    http://localhost:18789/health"
    echo ""
    echo "  Logs:      docker compose logs -f"
    echo "  Stop:      docker compose down"
else
    info "Starting gateway directly..."
    echo ""
    echo "Run this command to start:"
    echo ""
    echo "  python3 gateway.py"
    echo ""
    echo "Or to run in background:"
    echo ""
    echo "  nohup python3 gateway.py > logs/gateway.log 2>&1 &"
    echo ""
fi

# ─── Summary ───
echo ""
echo "═══════════════════════════════════════════════════"
echo ""
success "OpenClaw v4.2 setup complete!"
echo ""
echo "  What you have:"
echo "  - 9 AI agents (coding, security, data, betting, review, architecture, testing, debugging)"
echo "  - 75+ MCP tools (weather, crypto, web search, calendar, habits, and more)"
echo "  - Personal Assistant with memory (learns about you over time)"
echo "  - Cost tracking ($0.003 average per job)"
echo "  - Budget guardrails (approval flow for expensive operations)"
echo ""
echo "  Next steps:"
echo "  1. Open http://localhost:18789/health to verify"
echo "  2. Send a message to your Telegram bot"
echo "  3. Or use the API: curl -X POST http://localhost:18789/api/chat -d '{\"message\": \"hello\"}'"
echo ""
echo "  Docs: https://github.com/your-repo/openclaw"
echo "  Cost: ~\$5/month to run"
echo ""
