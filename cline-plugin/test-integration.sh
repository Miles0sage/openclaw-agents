#!/bin/bash

#############################################
# Test Cline <-> OpenClaw Integration
#############################################

echo "🧪 Testing Cline Integration Plugin"
echo "===================================="
echo ""

GATEWAY_URL="http://localhost:18789"

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test 1: Check gateway is running
echo "📊 Test 1: Gateway Status"
response=$(curl -s $GATEWAY_URL/)
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Gateway is running"
    echo "   $response"
else
    echo -e "${RED}✗${NC} Gateway is not running"
    echo "   Start with: cd ./ && python3 gateway.py &"
    exit 1
fi

echo ""

# Test 2: Check plugin status
echo "📊 Test 2: Cline Plugin Status"
response=$(curl -s "$GATEWAY_URL/api/cline/status")
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Cline plugin is active"
    echo "   $response" | jq
else
    echo -e "${YELLOW}⚠${NC} Cline plugin might not be loaded"
    echo "   Response: $response"
fi

echo ""

# Test 3: Send message to Cline
echo "📤 Test 3: Send Message to Cline"
response=$(curl -s -X POST "$GATEWAY_URL/api/cline/send" \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "CodeGen Pro",
    "message": "Test message from OpenClaw",
    "code": "console.log(\"Hello from OpenClaw!\");",
    "action": "review"
  }')

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Message sent to queue"
    echo "   $response" | jq
else
    echo -e "${RED}✗${NC} Failed to send message"
    echo "   $response"
fi

echo ""

# Test 4: Poll for messages (simulate Cline)
echo "📥 Test 4: Poll for Messages (as Cline)"
since=$(($(date +%s) - 3600))  # Last hour
response=$(curl -s "$GATEWAY_URL/api/cline/poll?since=${since}000")

if [ $? -eq 0 ]; then
    message_count=$(echo "$response" | jq '.messages | length')
    echo -e "${GREEN}✓${NC} Successfully polled messages"
    echo "   Found $message_count message(s)"
    echo "   $response" | jq
else
    echo -e "${RED}✗${NC} Failed to poll messages"
    echo "   $response"
fi

echo ""

# Test 5: Send message from Cline to OpenClaw
echo "📤 Test 5: Send Message from Cline to OpenClaw"
response=$(curl -s -X POST "$GATEWAY_URL/api/cline/send" \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "Cline",
    "message": "I implemented the authentication feature",
    "code": "// JWT implementation here"
  }')

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Message from Cline received"
    echo "   $response" | jq
else
    echo -e "${RED}✗${NC} Failed to send message from Cline"
    echo "   $response"
fi

echo ""

# Test 6: Clear queue
echo "🗑️  Test 6: Clear Message Queue"
response=$(curl -s -X DELETE "$GATEWAY_URL/api/cline/clear")

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Queue cleared"
    echo "   $response" | jq
else
    echo -e "${RED}✗${NC} Failed to clear queue"
    echo "   $response"
fi

echo ""

# Summary
echo "========================================"
echo "✅ Integration Tests Complete!"
echo ""
echo "Next steps:"
echo "1. Install Cline in VS Code"
echo "2. Configure Cline to poll $GATEWAY_URL/api/cline/poll"
echo "3. Send messages from OpenClaw agents using cline_send tool"
echo "4. Cline receives and implements tasks!"
echo ""
echo "Endpoints available:"
echo "  Status:  GET  $GATEWAY_URL/api/cline/status"
echo "  Poll:    GET  $GATEWAY_URL/api/cline/poll?since=<timestamp>"
echo "  Send:    POST $GATEWAY_URL/api/cline/send"
echo "  Clear:   DELETE $GATEWAY_URL/api/cline/clear"
