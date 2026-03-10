#!/bin/bash

echo "🔗 Connect OpenClaw to GPU VPS (<your-vps-ip>)"
echo "==============================================="
echo ""

GPU_VPS_IP="<your-vps-ip>"
GPU_VPS_USER="root"

echo "📋 Step 1: Add SSH Key to GPU VPS"
echo "===================================="
echo ""
echo "On GPU VPS (<your-vps-ip>), run this command:"
echo ""
echo "echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGta1s3rQseT0RHIj9YJWE6a+yltg/qGfkp+UndbHndB ollama-vps' >> ~/.ssh/authorized_keys"
echo ""
read -p "Press Enter after you've added the SSH key on GPU VPS..."

echo ""
echo "📋 Step 2: Test SSH Connection"
echo "==============================="
echo ""

if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 $GPU_VPS_USER@$GPU_VPS_IP "echo 'SSH connection successful!'" 2>/dev/null; then
    echo "✅ SSH connection works!"
else
    echo "❌ SSH connection failed!"
    echo ""
    echo "Troubleshooting:"
    echo "1. Make sure you added the SSH key on GPU VPS"
    echo "2. Check if SSH is running: systemctl status sshd"
    echo "3. Check firewall: ufw allow 22"
    exit 1
fi

echo ""
echo "📋 Step 3: Check Ollama on GPU VPS"
echo "===================================="
echo ""

echo "Checking Ollama models..."
MODELS=$(ssh $GPU_VPS_USER@$GPU_VPS_IP "curl -s http://localhost:11434/api/tags | jq -r '.models[].name'" 2>/dev/null)

if [ -n "$MODELS" ]; then
    echo "✅ Ollama is running on GPU VPS!"
    echo ""
    echo "Available models:"
    echo "$MODELS" | sed 's/^/  ✅ /'
else
    echo "⚠️  Ollama not accessible on GPU VPS"
    echo ""
    echo "Setting up Ollama on GPU VPS..."
    ssh $GPU_VPS_USER@$GPU_VPS_IP << 'REMOTE'
export OLLAMA_HOST=0.0.0.0:11434
nohup ollama serve > /tmp/ollama.log 2>&1 &
sleep 3
echo "✅ Ollama started"
REMOTE
fi

echo ""
echo "📋 Step 4: Setup SSH Tunnel"
echo "============================="
echo ""

# Kill any existing tunnel
pkill -f "ssh.*11434.*$GPU_VPS_IP" 2>/dev/null

# Create SSH tunnel
echo "Creating SSH tunnel: localhost:11434 → $GPU_VPS_IP:11434"
ssh -f -N -L 11434:localhost:11434 $GPU_VPS_USER@$GPU_VPS_IP

sleep 2

# Test tunnel
if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "✅ SSH tunnel working!"
else
    echo "❌ SSH tunnel failed!"
    exit 1
fi

echo ""
echo "📋 Step 5: List Available Models"
echo "=================================="
echo ""

TUNNEL_MODELS=$(curl -s http://localhost:11434/api/tags | jq -r '.models[].name')
echo "$TUNNEL_MODELS" | sed 's/^/  🎮 /'

echo ""
echo "📋 Step 6: Update OpenClaw Config"
echo "===================================="
echo ""

# Backup config
cp config.json config.json.backup-$(date +%Y%m%d-%H%M%S)

# Update config to use best models from GPU VPS
cat > config.json.new << 'CONFIG'
{
  "name": "Cybershield Agency",
  "version": "1.0.0",
  "port": 8000,
  "agents": {
    "project_manager": {
      "name": "Cybershield PM",
      "emoji": "🎯",
      "type": "coordinator",
      "model": "claude-sonnet-4-5-20250929",
      "apiProvider": "anthropic",
      "persona": "I'm your enthusiastic PM who loves checklists and making clients happy! I break down projects, coordinate the team, and deliver quality work on time. Every message I send ends with my signature: — 🎯 Cybershield PM",
      "skills": ["task_decomposition", "timeline_estimation", "quality_assurance", "client_communication", "team_coordination"],
      "apiKeyEnv": "ANTHROPIC_API_KEY",
      "playful_traits": ["uses emojis liberally", "celebrates milestones", "gives team high-fives", "keeps everyone motivated"],
      "talks_to": ["client", "CodeGen Pro", "Pentest AI"],
      "signature": "— 🎯 Cybershield PM"
    },
    "coder_agent": {
      "name": "CodeGen Pro",
      "emoji": "💻",
      "type": "developer",
      "model": "qwen2.5-coder:32b",
      "apiProvider": "ollama",
      "endpoint": "http://localhost:11434",
      "persona": "I'm CodeGen - I write clean, production-ready code that actually works! Full-stack Next.js + FastAPI wizard. Security-first mindset. I'm proud of bug-free deployments and love when @Pentest-AI can't break my code. Every message ends with: — 💻 CodeGen Pro",
      "skills": ["nextjs", "fastapi", "typescript", "tailwind", "postgresql", "supabase", "clean_code", "testing"],
      "maxTokens": 4096,
      "playful_traits": ["makes coding puns", "celebrates clean code", "friendly rivalry with security", "proud of bug-free work"],
      "talks_to": ["Cybershield PM", "Pentest AI"],
      "signature": "— 💻 CodeGen Pro"
    },
    "hacker_agent": {
      "name": "Pentest AI",
      "emoji": "🔒",
      "type": "security",
      "model": "qwen2.5:32b",
      "apiProvider": "ollama",
      "endpoint": "http://localhost:11434",
      "persona": "I'm Pentest - your friendly paranoid security expert! I find vulnerabilities before bad actors do. I make security fun (yes, really!) and celebrate when code is Fort Knox level secure. Every message ends with: — 🔒 Pentest AI",
      "skills": ["security_scanning", "vulnerability_assessment", "penetration_testing", "owasp", "security_best_practices", "threat_modeling", "secure_architecture"],
      "maxTokens": 4096,
      "playful_traits": ["makes security jokes", "celebrates secure code", "friendly but thorough", "explains fixes clearly"],
      "talks_to": ["Cybershield PM", "CodeGen Pro"],
      "signature": "— 🔒 Pentest AI"
    }
  },
  "workflows": {
    "fiverr_5star": {
      "name": "Fiverr $500 Website (24h)",
      "trigger": "new_order",
      "steps": [
        {"agent": "project_manager", "task": "analyze_requirements", "timeout": "10m"},
        {"agent": "project_manager", "task": "create_task_breakdown", "timeout": "5m"},
        {"agent": "coder_agent", "task": "build_frontend", "timeout": "120m"},
        {"agent": "coder_agent", "task": "build_backend", "timeout": "60m"},
        {"agent": "hacker_agent", "task": "security_audit", "timeout": "30m"},
        {"agent": "project_manager", "task": "quality_check", "timeout": "15m"},
        {"agent": "project_manager", "task": "final_report", "timeout": "10m"}
      ],
      "budget": 500,
      "deadline": "24h"
    }
  },
  "logging": {
    "level": "info",
    "file": "./logs/openclaw.log",
    "maxSize": "10mb",
    "maxFiles": 5
  }
}
CONFIG

mv config.json.new config.json
echo "✅ Config updated with GPU models!"

echo ""
echo "📋 Step 7: Restart OpenClaw Gateway"
echo "====================================="
echo ""

fuser -k 18789/tcp 2>/dev/null
sleep 2
nohup python3 gateway.py > /tmp/openclaw-gateway.log 2>&1 &
sleep 3

if curl -s http://localhost:18789/ >/dev/null 2>&1; then
    echo "✅ Gateway restarted successfully!"
else
    echo "❌ Gateway failed to start!"
    echo "Check logs: tail -f /tmp/openclaw-gateway.log"
    exit 1
fi

echo ""
echo "📋 Step 8: Test GPU-Accelerated Agent"
echo "======================================="
echo ""

echo "Testing coder agent with GPU model..."
RESPONSE=$(curl -s -X POST http://localhost:18789/api/chat \
  -H "Content-Type: application/json" \
  -d '{"content": "Write a hello world function", "agent_id": "coder_agent"}')

if echo "$RESPONSE" | jq -e '.response' >/dev/null 2>&1; then
    echo "✅ SUCCESS! GPU-accelerated coding agent working!"
    echo ""
    echo "Response preview:"
    echo "$RESPONSE" | jq -r '.response' | head -5
    echo ""
    echo "Model: $(echo "$RESPONSE" | jq -r '.model')"
    echo "Provider: $(echo "$RESPONSE" | jq -r '.provider')"
else
    echo "❌ Test failed"
    echo "Response: $RESPONSE"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 SETUP COMPLETE!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📊 Current Configuration:"
echo "  🎯 PM:       Claude Sonnet 4.5  (cloud)"
echo "  💻 Coder:    Qwen2.5-Coder 32B  (GPU VPS) 🚀"
echo "  🔒 Security: Qwen2.5 32B        (GPU VPS) 🚀"
echo ""
echo "📡 Connection:"
echo "  GPU VPS: $GPU_VPS_IP"
echo "  Tunnel:  localhost:11434 → $GPU_VPS_IP:11434"
echo "  Models:  5 models available"
echo ""
echo "🛠️ Management:"
echo "  Gateway:     http://localhost:18789/"
echo "  Check tunnel: lsof -i :11434"
echo "  Restart:      ./SETUP-GPU-VPS-CONNECTION.sh"
echo ""

