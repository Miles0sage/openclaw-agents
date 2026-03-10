#!/bin/bash

echo "🤖 OpenClaw Multi-Agent Test"
echo "Testing 3-agent workflow with minimal Anthropic usage"
echo "=========================================="
echo ""

GATEWAY="http://localhost:18789"

# Test 1: PM plans the task (uses Claude - minimal)
echo "1️⃣ PROJECT MANAGER (Claude Sonnet) - Planning..."
echo ""
PM_RESPONSE=$(curl -s -X POST "$GATEWAY/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"content":"Quick plan: Build a simple login function. Just list 2 steps.","agent_id":"project_manager"}')

echo "$PM_RESPONSE" | jq -r '.response' | head -10
echo ""
echo "---"
echo ""

# Test 2: Coder builds it (uses local GPU 32B)
echo "2️⃣ CODEGEN PRO (Local GPU 32B) - Building..."
echo ""
CODER_RESPONSE=$(curl -s -X POST "$GATEWAY/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"content":"Write a Python login function with username and password validation","agent_id":"coder_agent"}')

echo "$CODER_RESPONSE" | jq -r '.response' | head -20
echo ""
echo "---"
echo ""

# Test 3: Security audits it (uses local GPU 14B)
echo "3️⃣ PENTEST AI (Local GPU 14B) - Auditing..."
echo ""
SECURITY_RESPONSE=$(curl -s -X POST "$GATEWAY/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"content":"Security audit this code: def login(user, pwd): return user == admin and pwd == 12345","agent_id":"hacker_agent"}')

echo "$SECURITY_RESPONSE" | jq -r '.response' | head -20
echo ""
echo "---"
echo ""

# Summary
echo "✅ MULTI-AGENT TEST COMPLETE!"
echo ""
echo "📊 Token Usage Summary:"
echo "  🎯 PM (Claude):      ~200 tokens  💰 ~$0.001"
echo "  💻 Coder (GPU 32B):  FREE (local)"
echo "  🔒 Security (14B):   FREE (local)"
echo ""
echo "Total Cost: ~$0.001 (99% savings vs all-Claude!)"
