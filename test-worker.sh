#!/bin/bash

WORKER_URL="https://oversserclaw-worker.amit-shah-5201.workers.dev"
TOKEN="7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d"

echo "🧪 Testing Cloudflare Worker Connection"
echo "========================================"
echo ""

echo "1️⃣ Test GET without token:"
curl -s "$WORKER_URL/" | jq '.' 2>/dev/null || curl -s "$WORKER_URL/"
echo ""

echo "2️⃣ Test GET with token in query:"
curl -s "$WORKER_URL/?token=$TOKEN" | jq '.' 2>/dev/null || curl -s "$WORKER_URL/?token=$TOKEN"
echo ""

echo "3️⃣ Test GET with token in header:"
curl -s -H "Authorization: Bearer $TOKEN" "$WORKER_URL/" | jq '.' 2>/dev/null || curl -s -H "Authorization: Bearer $TOKEN" "$WORKER_URL/"
echo ""

echo "4️⃣ Test POST with JSON:"
curl -s -X POST "$WORKER_URL/" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"action": "status"}' | jq '.' 2>/dev/null || curl -s -X POST "$WORKER_URL/" -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -d '{"action": "status"}'
echo ""

echo "5️⃣ Test OpenClaw connection endpoint:"
curl -s -X POST "$WORKER_URL/connect" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"gateway": "http://localhost:18789"}' | jq '.' 2>/dev/null || echo "(no response or error)"
echo ""

