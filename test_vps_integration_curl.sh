#!/bin/bash
# VPS Integration Testing Script
# ==============================
# Tests the VPS integration bridge with curl commands

set -e

GATEWAY_URL="${GATEWAY_URL:-http://localhost:18789}"
TOKEN="${GATEWAY_TOKEN:-moltbot-secure-token-2026}"

echo "═══════════════════════════════════════════════════════════════"
echo "VPS Integration Testing"
echo "═══════════════════════════════════════════════════════════════"
echo "Gateway: $GATEWAY_URL"
echo ""

# Function to make API call
api_call() {
    local method=$1
    local endpoint=$2
    local data=$3
    
    local url="${GATEWAY_URL}${endpoint}"
    
    if [ -z "$data" ]; then
        curl -s -X "$method" \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer $TOKEN" \
            "$url"
    else
        curl -s -X "$method" \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer $TOKEN" \
            -d "$data" \
            "$url"
    fi
}

# Test 1: Register VPS agents
echo "Test 1: Register VPS Agents"
echo "---"

echo "Registering primary PM agent..."
api_call POST /api/vps/register '{
  "name": "pm-agent",
  "host": "192.168.1.100",
  "port": 5000,
  "protocol": "http",
  "timeout_seconds": 30,
  "max_retries": 2,
  "fallback_agents": ["sonnet-agent"]
}' | jq .
echo ""

echo "Registering fallback Sonnet agent..."
api_call POST /api/vps/register '{
  "name": "sonnet-agent",
  "host": "192.168.1.101",
  "port": 5001,
  "protocol": "http",
  "timeout_seconds": 30,
  "max_retries": 1
}' | jq .
echo ""

# Test 2: List registered agents
echo "Test 2: List Registered Agents"
echo "---"
api_call GET /api/vps/agents | jq .
echo ""

# Test 3: Get initial health status
echo "Test 3: Get VPS Health Status"
echo "---"
api_call GET /api/vps/health | jq .
echo ""

# Test 4: Call VPS agent (will fail since no actual server)
echo "Test 4: Call VPS Agent (Expected to fail gracefully)"
echo "---"
api_call POST /api/vps/call '{
  "agent_name": "pm-agent",
  "prompt": "Plan a 3-phase project with cost estimation",
  "session_id": "sess-user-123",
  "user_id": "user-123",
  "metadata": {"context": "planning"}
}' | jq .
echo ""

# Test 5: Check health after failed call
echo "Test 5: Check Agent Health After Failure"
echo "---"
api_call GET /api/vps/health/pm-agent | jq .
echo ""

# Test 6: Get session
echo "Test 6: Get Session Details"
echo "---"
api_call GET /api/vps/sessions/sess-user-123 | jq .
echo ""

# Test 7: Call nonexistent agent (validation test)
echo "Test 7: Call Nonexistent Agent (Validation Test)"
echo "---"
api_call POST /api/vps/call '{
  "agent_name": "nonexistent-agent",
  "prompt": "Test",
  "session_id": "sess-test",
  "user_id": "user-test"
}' | jq .
echo ""

# Test 8: Gateway status
echo "Test 8: Gateway Status"
echo "---"
api_call GET /api/vps/status | jq .
echo ""

# Test 9: Cleanup sessions
echo "Test 9: Cleanup Old Sessions"
echo "---"
api_call POST /api/vps/sessions/cleanup | jq .
echo ""

echo "═══════════════════════════════════════════════════════════════"
echo "Testing Complete"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Key endpoints tested:"
echo "  POST   /api/vps/call              - Call VPS agent with fallback"
echo "  POST   /api/vps/register          - Register new VPS agent"
echo "  GET    /api/vps/agents            - List all agents"
echo "  GET    /api/vps/health            - Get health summary"
echo "  GET    /api/vps/health/{agent}    - Get agent health"
echo "  GET    /api/vps/sessions/{id}     - Get session"
echo "  DELETE /api/vps/sessions/{id}     - Delete session"
echo "  POST   /api/vps/sessions/cleanup  - Clean up old sessions"
echo "  GET    /api/vps/status            - Get gateway status"
echo ""

