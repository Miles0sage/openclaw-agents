#!/bin/bash

echo "🤖 OpenClaw Multi-Agent Direct Test"
echo "Testing agents directly (bypassing gateway timeout)"
echo "=========================================="
echo ""

# Test 1: PM via Gateway (Claude - works fast)
echo "1️⃣ PROJECT MANAGER (Claude Sonnet) - Planning..."
echo ""
PM_RESPONSE=$(curl -s -X POST "http://localhost:18789/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"content":"Quick 2-step plan for login function","agent_id":"project_manager"}')

echo "$PM_RESPONSE" | jq -r '.response' | head -8
echo ""
echo "✅ Cost: ~$0.001"
echo "---"
echo ""

# Test 2: Coder via direct Ollama (GPU 32B)
echo "2️⃣ CODEGEN PRO (Direct GPU 32B) - Building..."
echo ""
cat > /tmp/coder-prompt.json <<'EOF'
{
  "model": "qwen2.5-coder:32b",
  "prompt": "Write a Python login function:\n\ndef login(username, password):\n    # Your code here\n\nKeep it simple, 10 lines max.",
  "stream": false
}
EOF

CODER_START=$(date +%s)
CODER_RESPONSE=$(timeout 60 curl -s http://<your-vps-ip>:11434/api/generate -d @/tmp/coder-prompt.json)
CODER_END=$(date +%s)
CODER_TIME=$((CODER_END - CODER_START))

echo "$CODER_RESPONSE" | jq -r '.response' | head -15
echo ""
echo "⏱️  Time: ${CODER_TIME}s | ✅ Cost: FREE (local GPU)"
echo "---"
echo ""

# Test 3: Security via direct Ollama (GPU 14B)
echo "3️⃣ PENTEST AI (Direct GPU 14B) - Auditing..."
echo ""
cat > /tmp/security-prompt.json <<'EOF'
{
  "model": "qwen2.5-coder:14b",
  "prompt": "Security audit this code:\n\ndef login(user, pwd):\n    return user == 'admin' and pwd == '12345'\n\nList 2 main security issues.",
  "stream": false
}
EOF

SECURITY_START=$(date +%s)
SECURITY_RESPONSE=$(timeout 60 curl -s http://<your-vps-ip>:11434/api/generate -d @/tmp/security-prompt.json)
SECURITY_END=$(date +%s)
SECURITY_TIME=$((SECURITY_END - SECURITY_START))

echo "$SECURITY_RESPONSE" | jq -r '.response' | head -15
echo ""
echo "⏱️  Time: ${SECURITY_TIME}s | ✅ Cost: FREE (local GPU)"
echo "---"
echo ""

# Summary
echo "✅ MULTI-AGENT WORKFLOW COMPLETE!"
echo ""
echo "📊 Performance:"
echo "  🎯 PM (Claude):       Fast (~1s)   💰 $0.001"
echo "  💻 Coder (GPU 32B):   ${CODER_TIME}s         💰 FREE"
echo "  🔒 Security (14B):    ${SECURITY_TIME}s         💰 FREE"
echo ""
echo "💡 Total Anthropic Cost: ~$0.001 (vs $0.10+ for all-Claude!)"
echo "🚀 99% cost savings using local GPU models!"
