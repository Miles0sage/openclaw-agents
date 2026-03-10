#!/bin/bash
# Test cost gates integration via curl
# Note: This requires gateway.py to be running on localhost:8000

set -e

GATEWAY_URL="http://localhost:8000"
AUTH_TOKEN="${GATEWAY_AUTH_TOKEN:?GATEWAY_AUTH_TOKEN must be set}"

echo "=== Cost Gates Curl Tests ==="
echo ""

# Test 1: Under budget (should succeed with 200)
echo "Test 1: Request under budget"
echo "Expected: 200 OK (APPROVED)"
curl -X POST "$GATEWAY_URL/api/chat" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "What is 2+2?",
    "agent_id": "pm",
    "project_id": "test-under-budget",
    "sessionKey": "test-session-1"
  }' \
  -w "\nStatus: %{http_code}\n" \
  -s | head -50
echo ""

# Test 2: At warning threshold (should succeed with 200 but with warning)
echo "Test 2: Request at warning threshold"
echo "Expected: 200 OK but with warning in logs"
curl -X POST "$GATEWAY_URL/api/chat" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Explain quantum computing in detail with examples",
    "agent_id": "pm",
    "project_id": "test-warning-threshold",
    "sessionKey": "test-session-2"
  }' \
  -w "\nStatus: %{http_code}\n" \
  -s | head -50
echo ""

# Test 3: Over budget (should fail with 402)
echo "Test 3: Request over budget"
echo "Expected: 402 Payment Required"
echo "Note: Requires budget to be set to very low limit"
echo ""

echo "=== Testing /api/route endpoint ===" 
echo ""

# Test route endpoint under budget
echo "Route Test 1: Classification under budget"
curl -X POST "$GATEWAY_URL/api/route" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Simple math question",
    "sessionKey": "test-route-1"
  }' \
  -w "\nStatus: %{http_code}\n" \
  -s | head -50
echo ""

