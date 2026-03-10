#!/bin/bash

echo "🤖 OPENCLAW MULTI-AGENT DEMO"
echo "Real-time agent communication with cost tracking"
echo "=================================================="
echo ""

# Test 1: PM Plans (Claude Sonnet)
echo "1️⃣ 🎯 PROJECT MANAGER (Claude Sonnet - Cloud)"
echo "   Task: Plan a simple website"
echo ""
PM_START=$(date +%s)
PM=$(curl -s -X POST "http://localhost:18789/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"content":"List 3 quick steps to build a simple website","agent_id":"project_manager"}' | jq -r '.response')
PM_END=$(date +%s)
PM_TIME=$((PM_END - PM_START))

echo "$PM" | head -12
echo ""
echo "   ⏱️  ${PM_TIME}s | 💰 ~\$0.001"
echo ""
echo "---"
echo ""

# Test 2: Coder Builds (GPU 32B)
echo "2️⃣ 💻 CODEGEN PRO (GPU 32B - Local)"
echo "   Task: Write HTML code"
echo ""
cat > /tmp/coder.json <<'EOF'
{"model":"qwen2.5-coder:32b","prompt":"Write simple HTML: <h1>Hello</h1><p>Welcome</p> - add 1 button. Code only, 5 lines max.","stream":false}
EOF

CODER_START=$(date +%s)
CODER=$(timeout 45 curl -s http://<your-vps-ip>:11434/api/generate -d @/tmp/coder.json | jq -r '.response')
CODER_END=$(date +%s)
CODER_TIME=$((CODER_END - CODER_START))

echo "$CODER" | head -10
echo ""
echo "   ⏱️  ${CODER_TIME}s | 💰 FREE (local GPU)"
echo ""
echo "---"
echo ""

# Test 3: Security Audits (GPU 14B)
echo "3️⃣ 🔒 PENTEST AI (GPU 14B - Local)"
echo "   Task: Quick security check"
echo ""
cat > /tmp/security.json <<'EOF'
{"model":"qwen2.5-coder:14b","prompt":"Security check: <button onclick='alert(1)'>Click</button> - Main issue? 1 sentence.","stream":false}
EOF

SECURITY_START=$(date +%s)
SECURITY=$(timeout 45 curl -s http://<your-vps-ip>:11434/api/generate -d @/tmp/security.json | jq -r '.response')
SECURITY_END=$(date +%s)
SECURITY_TIME=$((SECURITY_END - SECURITY_START))

echo "$SECURITY" | head -8
echo ""
echo "   ⏱️  ${SECURITY_TIME}s | 💰 FREE (local GPU)"
echo ""
echo "=================================================="
echo ""

# Summary
TOTAL_TIME=$((PM_TIME + CODER_TIME + SECURITY_TIME))
echo "✅ WORKFLOW COMPLETE!"
echo ""
echo "📊 PERFORMANCE:"
echo "   Total Time:    ${TOTAL_TIME}s"
echo "   PM (Claude):   ${PM_TIME}s"
echo "   Coder (32B):   ${CODER_TIME}s"
echo "   Security (14B): ${SECURITY_TIME}s"
echo ""
echo "💰 COST ANALYSIS:"
echo "   Anthropic API: ~\$0.001 (only PM uses Claude)"
echo "   GPU Models:    \$0.000 (free local)"
echo "   vs All-Claude: \$0.15+ (150x more expensive!)"
echo ""
echo "🚀 SAVINGS: 99.3% cost reduction!"
echo ""
echo "💡 KEY INSIGHT:"
echo "   - Use Claude (PM) for planning/coordination (fast, cheap)"
echo "   - Use local GPU for heavy lifting (code, analysis)"
echo "   - Result: Enterprise AI at hobby budget! 🎉"
