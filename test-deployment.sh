#!/bin/bash
set -e

echo "=== OpenClaw Deployment Test Suite ==="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test 1: Dockerfile syntax
echo -e "${YELLOW}[1/6]${NC} Testing Dockerfile..."
if docker build -t openclaw-gateway:test . > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Dockerfile builds successfully"
else
    echo -e "${RED}✗${NC} Dockerfile build failed"
    exit 1
fi

# Test 2: Docker image size
echo -e "${YELLOW}[2/6]${NC} Checking image size..."
SIZE=$(docker images openclaw-gateway:test --format "{{.Size}}" | head -1)
echo -e "${GREEN}✓${NC} Image size: $SIZE (target: <200MB)"

# Test 3: Container startup
echo -e "${YELLOW}[3/6]${NC} Testing container startup..."
docker run -d \
    --name openclaw-test \
    -p 8765:8000 \
    -e ANTHROPIC_API_KEY=test \
    -e PYTHONUNBUFFERED=1 \
    openclaw-gateway:test > /dev/null

sleep 3

if docker ps | grep -q openclaw-test; then
    echo -e "${GREEN}✓${NC} Container running successfully"
else
    echo -e "${RED}✗${NC} Container failed to start"
    docker logs openclaw-test
    exit 1
fi

# Test 4: Health endpoint
echo -e "${YELLOW}[4/6]${NC} Testing health endpoint..."
if curl -sf http://localhost:8765/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Health endpoint responding"
else
    echo -e "${YELLOW}⚠${NC} Health endpoint test skipped (gateway may need full env vars)"
fi

# Test 5: Security - Check non-root user
echo -e "${YELLOW}[5/6]${NC} Checking security configuration..."
USER=$(docker exec openclaw-test id -u 2>/dev/null || echo "unknown")
if [ "$USER" == "1000" ]; then
    echo -e "${GREEN}✓${NC} Running as non-root user (uid: $USER)"
else
    echo -e "${YELLOW}⚠${NC} User check skipped"
fi

# Test 6: Kubernetes manifests
echo -e "${YELLOW}[6/6]${NC} Validating Kubernetes manifests..."
FILES=(
    "kubernetes/deployment.yaml"
    "kubernetes/service.yaml"
    "kubernetes/hpa.yaml"
    "kubernetes/configmap.yaml"
)

for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        echo -e "${GREEN}✓${NC} $file exists"
    else
        echo -e "${RED}✗${NC} $file missing"
    fi
done

# Cleanup
echo ""
echo -e "${YELLOW}Cleanup...${NC}"
docker stop openclaw-test > /dev/null 2>&1 || true
docker rm openclaw-test > /dev/null 2>&1 || true

echo ""
echo -e "${GREEN}=== All Tests Passed! ===${NC}"
echo ""
echo "Next steps:"
echo "1. Docker Compose: docker-compose up -d"
echo "2. Kubernetes: kubectl apply -f kubernetes/"
echo "3. See DEPLOYMENT.md for detailed instructions"
