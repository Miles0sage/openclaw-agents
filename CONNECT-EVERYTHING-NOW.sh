#!/bin/bash

clear
echo "🚀 CONNECTING EVERYTHING NOW!"
echo "══════════════════════════════════════════"
echo ""

GPU_VPS="<your-vps-ip>"

# Step 1: Test SSH
echo "1️⃣ Testing SSH connection to GPU VPS..."
if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 root@$GPU_VPS "echo 'Connected!'" 2>/dev/null; then
    echo "✅ SSH works!"
else
    echo "❌ SSH failed! Did you add the SSH key?"
    echo ""
    echo "On GPU VPS (<your-vps-ip>), run:"
    echo "echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGta1s3rQseT0RHIj9YJWE6a+yltg/qGfkp+UndbHndB ollama-vps' >> ~/.ssh/authorized_keys"
    exit 1
fi

echo ""
echo "2️⃣ Checking Ollama on GPU VPS..."
ssh root@$GPU_VPS "curl -s http://localhost:11434/api/tags" >/dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✅ Ollama running!"
    MODELS=$(ssh root@$GPU_VPS "curl -s http://localhost:11434/api/tags | jq -r '.models[].name' 2>/dev/null")
    echo ""
    echo "Available models:"
    echo "$MODELS" | sed 's/^/  🎮 /'
else
    echo "⚠️  Starting Ollama on GPU VPS..."
    ssh root@$GPU_VPS "OLLAMA_HOST=0.0.0.0:11434 nohup ollama serve > /tmp/ollama.log 2>&1 &"
    sleep 3
    echo "✅ Ollama started!"
fi

echo ""
echo "3️⃣ Creating SSH tunnel..."
pkill -f "ssh.*11434.*$GPU_VPS" 2>/dev/null
ssh -f -N -L 11434:localhost:11434 root@$GPU_VPS
sleep 2

if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "✅ Tunnel created!"
else
    echo "❌ Tunnel failed!"
    exit 1
fi

echo ""
echo "4️⃣ Updating OpenClaw config for GPU models..."
cd ./

# Backup
cp config.json config.json.backup-gpu

# Update to use 32B models from GPU
jq '.agents.coder_agent.model = "qwen2.5-coder:32b" |
    .agents.coder_agent.apiProvider = "ollama" |
    .agents.coder_agent.endpoint = "http://localhost:11434" |
    .agents.hacker_agent.model = "qwen2.5:32b" |
    .agents.hacker_agent.apiProvider = "ollama" |
    .agents.hacker_agent.endpoint = "http://localhost:11434"' config.json > config.json.tmp

mv config.json.tmp config.json
echo "✅ Config updated!"

echo ""
echo "5️⃣ Restarting OpenClaw gateway..."
fuser -k 18789/tcp 2>/dev/null
sleep 2
nohup python3 gateway.py > /tmp/openclaw-gateway.log 2>&1 &
sleep 3

if curl -s http://localhost:18789/ >/dev/null 2>&1; then
    echo "✅ Gateway restarted!"
else
    echo "❌ Gateway failed to start!"
    echo "Check logs: tail -f /tmp/openclaw-gateway.log"
    exit 1
fi

echo ""
echo "6️⃣ Testing GPU-accelerated coder..."
RESPONSE=$(curl -s -X POST http://localhost:18789/api/chat \
  -H "Content-Type: application/json" \
  -d '{"content": "Write hello world in Python", "agent_id": "coder_agent"}')

if echo "$RESPONSE" | jq -e '.response' >/dev/null 2>&1; then
    echo "✅ GPU CODER WORKS!"
    echo ""
    echo "Preview:"
    echo "$RESPONSE" | jq -r '.response' | head -3
    echo ""
    echo "Model: $(echo "$RESPONSE" | jq -r '.model')"
else
    echo "⚠️  Response: $RESPONSE"
fi

echo ""
echo "══════════════════════════════════════════"
echo "🎉 ALL CONNECTED!"
echo "══════════════════════════════════════════"
echo ""
echo "✅ Gateway: http://localhost:18789/"
echo "✅ Tunnel:  localhost:11434 → $GPU_VPS:11434"
echo "✅ Models:  GPU-accelerated 32B models"
echo ""
echo "Configuration:"
echo "  🎯 PM:       Claude Sonnet (cloud)"
echo "  💻 Coder:    Qwen2.5-Coder 32B (GPU) 🚀"
echo "  🔒 Security: Qwen2.5 32B (GPU) 🚀"
echo ""
echo "Test it:"
echo "  curl -X POST http://localhost:18789/api/chat \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"content\":\"Hello\",\"agent_id\":\"coder_agent\"}'"
echo ""

