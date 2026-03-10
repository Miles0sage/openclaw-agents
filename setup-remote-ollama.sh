#!/bin/bash

echo "🔧 OpenClaw → Remote GPU Ollama Setup"
echo "======================================"
echo ""

# Step 1: Get GPU VPS details
echo "📍 Step 1: Enter your GPU VPS details"
echo ""
read -p "GPU VPS IP address: " GPU_IP
read -p "GPU VPS Ollama port [11434]: " GPU_PORT
GPU_PORT=${GPU_PORT:-11434}

echo ""
echo "Testing connection to GPU VPS..."
if curl -s --connect-timeout 5 "http://${GPU_IP}:${GPU_PORT}/api/tags" >/dev/null 2>&1; then
    echo "✅ Connection successful!"
    MODELS=$(curl -s "http://${GPU_IP}:${GPU_PORT}/api/tags" | jq -r '.models[].name')
    echo ""
    echo "📦 Available models on GPU VPS:"
    echo "$MODELS" | sed 's/^/  - /'
else
    echo "❌ Cannot connect to GPU VPS Ollama"
    echo "   Please ensure:"
    echo "   1. Ollama is running on GPU VPS"
    echo "   2. Ollama is bound to 0.0.0.0 (not just localhost)"
    echo "   3. Firewall allows port $GPU_PORT"
    echo ""
    exit 1
fi

echo ""
echo "📝 Step 2: Update OpenClaw config"

# Backup current config
cp config.json config.json.backup
echo "✅ Backed up config.json to config.json.backup"

# Update config with remote Ollama endpoint
jq --arg endpoint "http://${GPU_IP}:${GPU_PORT}" '
  .agents.coder_agent.endpoint = $endpoint |
  .agents.hacker_agent.endpoint = $endpoint
' config.json > config.json.tmp && mv config.json.tmp config.json

echo "✅ Updated config.json with remote Ollama endpoint"
echo ""
echo "📊 New configuration:"
jq '.agents | to_entries[] | select(.value.apiProvider == "ollama") | {
  agent: .key,
  provider: .value.apiProvider,
  model: .value.model,
  endpoint: .value.endpoint
}' config.json

echo ""
echo "🔄 Step 3: Restart OpenClaw Gateway"
fuser -k 18789/tcp 2>/dev/null
sleep 2
nohup python3 gateway.py > /tmp/openclaw-gateway.log 2>&1 &
sleep 3

echo "✅ Gateway restarted"
echo ""
echo "🧪 Step 4: Test remote Ollama connection"
echo ""

TEST_RESPONSE=$(curl -s -X POST http://localhost:18789/api/chat \
  -H "Content-Type: application/json" \
  -d '{"content": "Say hello", "agent_id": "coder_agent"}')

if echo "$TEST_RESPONSE" | jq -e '.response' >/dev/null 2>&1; then
    echo "✅ SUCCESS! OpenClaw → GPU Ollama connection working!"
    echo ""
    echo "Response:"
    echo "$TEST_RESPONSE" | jq -r '.response' | head -5
    echo ""
    echo "Provider: $(echo "$TEST_RESPONSE" | jq -r '.provider')"
    echo "Model: $(echo "$TEST_RESPONSE" | jq -r '.model')"
    echo "Endpoint: http://${GPU_IP}:${GPU_PORT}"
else
    echo "❌ Test failed"
    echo "Response: $TEST_RESPONSE"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Setup complete!"
echo ""
echo "Your OpenClaw is now using:"
echo "  🎯 PM:       Claude Sonnet (cloud)"
echo "  💻 Coder:    Qwen2.5-Coder on GPU VPS"
echo "  🔒 Security: Claude Haiku (cloud)"
echo ""
