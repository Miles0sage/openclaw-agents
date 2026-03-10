#!/bin/bash

echo "🎮 GPU VPS - Ollama Network Setup"
echo "=================================="
echo ""
echo "Run this script ON YOUR GPU VPS (the one with the GPU)"
echo ""

# Check if Ollama is installed
if ! command -v ollama &> /dev/null; then
    echo "❌ Ollama not found!"
    echo "Install it first: curl -fsSL https://ollama.com/install.sh | sh"
    exit 1
fi

echo "✅ Ollama is installed"
echo ""

# Stop Ollama if running
echo "🛑 Stopping Ollama service..."
sudo systemctl stop ollama 2>/dev/null || true
pkill -9 ollama 2>/dev/null || true
sleep 2

echo ""
echo "🌐 Starting Ollama bound to all interfaces..."
echo "   This allows remote connections from your OpenClaw VPS"
echo ""

# Set environment variable to bind to all interfaces
export OLLAMA_HOST=0.0.0.0:11434

# Start Ollama in background
nohup ollama serve > /tmp/ollama.log 2>&1 &
OLLAMA_PID=$!

echo "✅ Ollama started (PID: $OLLAMA_PID)"
echo "   Bound to: 0.0.0.0:11434"
echo ""

sleep 5

# Test if it's accessible
if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "✅ Ollama responding on localhost"
else
    echo "❌ Ollama not responding"
    exit 1
fi

echo ""
echo "📦 Available models:"
curl -s http://localhost:11434/api/tags | jq -r '.models[].name' | sed 's/^/  - /'

echo ""
echo "🔥 Firewall Configuration"
echo "========================="
echo ""
echo "Allow port 11434 from your OpenClaw VPS:"
echo ""
read -p "Enter OpenClaw VPS IP address: " OPENCLAW_IP

if command -v ufw &> /dev/null; then
    echo "Using UFW..."
    sudo ufw allow from $OPENCLAW_IP to any port 11434
    echo "✅ Firewall rule added"
elif command -v firewall-cmd &> /dev/null; then
    echo "Using firewalld..."
    sudo firewall-cmd --permanent --add-rich-rule="rule family='ipv4' source address='$OPENCLAW_IP' port port='11434' protocol='tcp' accept"
    sudo firewall-cmd --reload
    echo "✅ Firewall rule added"
else
    echo "⚠️  Manual firewall configuration needed"
    echo "   Allow TCP port 11434 from $OPENCLAW_IP"
fi

echo ""
echo "🧪 Testing external access..."
echo "   From OpenClaw VPS, run:"
echo "   curl http://$(hostname -I | awk '{print $1}'):11434/api/tags"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ GPU VPS Setup Complete!"
echo ""
echo "GPU VPS IP: $(hostname -I | awk '{print $1}')"
echo "Ollama Port: 11434"
echo ""
echo "Next: Run setup-remote-ollama.sh on your OpenClaw VPS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
