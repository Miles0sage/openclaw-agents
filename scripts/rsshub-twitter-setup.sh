#!/bin/bash
# RSSHub Twitter Cookie Setup
# ===========================
# This script reconfigures the RSSHub Docker container with Twitter authentication.
#
# To get your Twitter cookie:
# 1. Log into twitter.com/x.com in your browser
# 2. Open DevTools (F12) > Application > Cookies > https://x.com
# 3. Copy the values for 'auth_token' and 'ct0'
#
# Usage:
#   ./rsshub-twitter-setup.sh <auth_token> <ct0>
#
# Example:
#   ./rsshub-twitter-setup.sh abc123def456 xyz789cookie

set -e

AUTH_TOKEN="${1}"
CT0="${2}"

if [ -z "$AUTH_TOKEN" ] || [ -z "$CT0" ]; then
    echo "Usage: $0 <auth_token> <ct0>"
    echo ""
    echo "To get these values:"
    echo "  1. Log into twitter.com/x.com in your browser"
    echo "  2. Open DevTools (F12) > Application > Cookies > https://x.com"
    echo "  3. Copy 'auth_token' and 'ct0' values"
    exit 1
fi

TWITTER_COOKIE="auth_token=${AUTH_TOKEN}; ct0=${CT0}"
echo "Configuring RSSHub with Twitter cookie..."

# Stop and remove existing container
docker stop rsshub 2>/dev/null || true
docker rm rsshub 2>/dev/null || true

# Start with Twitter cookie
docker run -d --name rsshub \
    --restart always \
    -p 1200:1200 \
    -e NODE_ENV=production \
    -e CACHE_EXPIRE=3600 \
    -e CACHE_TYPE=memory \
    -e REQUEST_TIMEOUT=10000 \
    -e "TWITTER_COOKIE=${TWITTER_COOKIE}" \
    diygod/rsshub:latest

echo "Waiting for RSSHub to start..."
sleep 5

# Test
echo "Testing Twitter feed..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "http://localhost:1200/twitter/user/AnthropicAI")
CONTENT_TYPE=$(curl -s --max-time 15 "http://localhost:1200/twitter/user/AnthropicAI" | head -1)

if echo "$CONTENT_TYPE" | grep -q "<?xml"; then
    echo "SUCCESS: RSSHub Twitter feeds are working!"
    echo "Test: curl http://localhost:1200/twitter/user/AnthropicAI"
else
    echo "WARNING: Twitter feed returned HTTP $HTTP_CODE but may not be XML."
    echo "The cookie might be invalid or expired. Check:"
    echo "  curl http://localhost:1200/twitter/user/AnthropicAI"
fi
