#!/bin/bash

echo "🚀 OpenClaw Cloudflare Worker Deployment"
echo "=========================================="
echo ""
echo "This will deploy your worker to: oversserclaw-worker.amit-shah-5201.workers.dev"
echo ""

cd ./

# Check if logged in
if ! wrangler whoami 2>/dev/null | grep -q "You are logged in"; then
    echo "⚠️  You need to login to Cloudflare first"
    echo ""
    echo "Run this:"
    echo "  wrangler login"
    echo ""
    exit 1
fi

# Set secrets
echo "📝 Setting secrets..."
echo ""

# Token
echo "Setting OPENCLAW_TOKEN..."
echo "7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d" | wrangler secret put OPENCLAW_TOKEN

# Gateway URL
echo "Setting OPENCLAW_GATEWAY..."
echo "http://<your-vps-ip>:18789" | wrangler secret put OPENCLAW_GATEWAY

# Deploy
echo ""
echo "🚀 Deploying worker..."
wrangler deploy

# Test
echo ""
echo "✅ Testing worker..."
WORKER_URL="https://oversserclaw-worker.amit-shah-5201.workers.dev"
TOKEN="7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d"

curl -s "${WORKER_URL}/?token=${TOKEN}" | jq '.'

echo ""
echo "🎉 Worker deployed!"
echo ""
echo "Test it:"
echo "  curl '${WORKER_URL}/api/chat?token=${TOKEN}' -X POST -H 'Content-Type: application/json' -d '{\"content\":\"Hello\",\"agent_id\":\"coder_agent\"}'"
