#!/bin/bash
# OpenClaw PC Connection Verification Script
# Run this on the VPS to verify your Windows PC is connected and Ollama is accessible
# Usage: ./connect-pc.sh

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== OpenClaw PC Connection Status ===${NC}\n"

# Check if Ollama port is listening (tunnel active)
echo -e "${BLUE}[1/4] Checking SSH tunnel...${NC}"
if ss -tlnp 2>/dev/null | grep -q ':11434'; then
    echo -e "${GREEN}✓ SSH tunnel ACTIVE (port 11434 listening)${NC}"
    tunnel_active=true
else
    echo -e "${RED}✗ SSH tunnel NOT ACTIVE (port 11434 not listening)${NC}"
    echo -e "${YELLOW}   → Start the tunnel on your PC:${NC}"
    echo -e "${YELLOW}     ssh -R 11434:localhost:11434 -i ~/.ssh/openclaw -N root@<your-vps-ip>${NC}"
    tunnel_active=false
fi
echo ""

# Check Ollama availability via HTTP
echo -e "${BLUE}[2/4] Checking Ollama API...${NC}"
if timeout 3 curl -s -f http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Ollama API RESPONDING${NC}"
    ollama_available=true
else
    echo -e "${RED}✗ Ollama API NOT RESPONDING${NC}"
    echo -e "${YELLOW}   → Make sure Ollama is running on your PC${NC}"
    echo -e "${YELLOW}   → PowerShell: ollama serve${NC}"
    ollama_available=false
fi
echo ""

# List available models
echo -e "${BLUE}[3/4] Available models on PC Ollama...${NC}"
if [ "$ollama_available" = true ]; then
    model_count=$(curl -s http://localhost:11434/api/tags | jq '.models | length' 2>/dev/null || echo 0)
    if [ "$model_count" -gt 0 ]; then
        echo -e "${GREEN}✓ Found $model_count model(s):${NC}"
        curl -s http://localhost:11434/api/tags | jq -r '.models[] | "  - \(.name) (\(.size | . / 1e9 | round)GB)"' 2>/dev/null || echo "  (Could not parse models)"
    else
        echo -e "${YELLOW}⚠ No models found on Ollama${NC}"
        echo -e "${YELLOW}   → Pull models on your PC:${NC}"
        echo -e "${YELLOW}     ollama pull qwen2.5:7b${NC}"
        echo -e "${YELLOW}     ollama pull deepseek-coder-v2:6.7b${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Cannot list models (Ollama not responding)${NC}"
fi
echo ""

# Test a quick inference
echo -e "${BLUE}[4/4] Testing inference on PC GPU...${NC}"
if [ "$ollama_available" = true ]; then
    echo -e "${YELLOW}   Running test inference (this may take 5-10 seconds)...${NC}"
    test_start=$(date +%s%N)
    if timeout 15 curl -s -X POST http://localhost:11434/api/generate \
        -H "Content-Type: application/json" \
        -d '{"model": "qwen2.5:7b", "prompt": "Hello", "stream": false}' | \
        jq -e '.response' > /dev/null 2>&1; then
        test_end=$(date +%s%N)
        test_duration=$(echo "scale=2; ($test_end - $test_start) / 1000000000" | bc)
        echo -e "${GREEN}✓ Inference SUCCESS (${test_duration}s)${NC}"
        inference_ok=true
    else
        echo -e "${YELLOW}⚠ Inference test failed or timed out${NC}"
        echo -e "${YELLOW}   → Try again, or verify model exists: curl http://localhost:11434/api/tags${NC}"
        inference_ok=false
    fi
else
    echo -e "${YELLOW}⚠ Cannot test inference (Ollama not responding)${NC}"
    inference_ok=false
fi
echo ""

# Summary
echo -e "${BLUE}=== Summary ===${NC}"
if [ "$tunnel_active" = true ] && [ "$ollama_available" = true ]; then
    echo -e "${GREEN}✓ READY TO USE${NC}"
    echo -e "   Your PC Ollama is available to OpenClaw agents"
    echo ""
    echo -e "${BLUE}Next steps:${NC}"
    echo "  1. Use models in OpenClaw: Set OLLAMA_BASE_URL=http://localhost:11434"
    echo "  2. Keep SSH tunnel running: ssh -R 11434:localhost:11434 -i ~/.ssh/openclaw -N root@<your-vps-ip>"
    echo "  3. Monitor GPU: nvidia-smi on your PC"
else
    echo -e "${RED}✗ NOT READY${NC}"
    echo -e "   Check the failures above and fix them"
    echo ""
    if [ "$tunnel_active" = false ]; then
        echo -e "${YELLOW}SSH Tunnel Fix:${NC}"
        echo "  On Windows PC, open PowerShell and run:"
        echo "  ssh -R 11434:localhost:11434 -i \$env:USERPROFILE\.ssh\openclaw -N root@<your-vps-ip>"
    fi
    if [ "$ollama_available" = false ]; then
        echo -e "${YELLOW}Ollama Fix:${NC}"
        echo "  On Windows PC, open PowerShell and run:"
        echo "  ollama serve"
    fi
fi
echo ""

# Show current SSH connections
echo -e "${BLUE}=== Active SSH Connections ===${NC}"
ss -tlnp 2>/dev/null | grep ssh || echo "No SSH connections found"
echo ""

# Show tunnel-specific details
echo -e "${BLUE}=== Tunnel Details ===${NC}"
echo "VPS Address: <your-vps-ip>"
echo "Ollama Port: 11434"
echo "Tunnel Type: Remote port forwarding (PC Ollama → VPS)"
if [ "$tunnel_active" = true ]; then
    pgrep -a sshd | grep -E "11434|R 11434" || echo "Tunnel process details not directly visible (tunnel may be in ssh session)"
fi
echo ""

# Tips
echo -e "${BLUE}=== Troubleshooting Tips ===${NC}"
echo "• SSH won't connect?"
echo "  → Verify key: ssh -i ~/.ssh/openclaw root@<your-vps-ip> 'echo ok'"
echo "  → Check firewall on Windows: Windows Defender Firewall → Allow app → ssh"
echo ""
echo "• Ollama not responding?"
echo "  → Check if running on PC: tasklist | findstr ollama"
echo "  → Restart Ollama: Close terminal, run 'ollama serve' again"
echo ""
echo "• Tunnel keeps disconnecting?"
echo "  → Use autossh (WSL2): autossh -M 0 -f -N -R 11434:localhost:11434 -i ~/.ssh/openclaw root@<your-vps-ip>"
echo "  → Or enable persistent SSH in Windows (OpenSSH service)"
echo ""
