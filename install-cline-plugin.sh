#!/bin/bash

#############################################
# Install Cline Plugin for OpenClaw
#############################################

echo "🔌 Installing Cline Integration Plugin"
echo "======================================="
echo ""

# Create extensions directory if not exists
mkdir -p ~/.openclaw/extensions

# Copy plugin
echo "📦 Copying plugin files..."
cp -r ./cline-plugin ~/.openclaw/extensions/cline

echo "✅ Plugin installed at: ~/.openclaw/extensions/cline"
echo ""

# Check if TypeScript is available
if command -v tsc &> /dev/null; then
    echo "✅ TypeScript found"
else
    echo "⚠️  TypeScript not found - installing..."
    npm install -g typescript
fi

# Check if gateway is running
if curl -s http://localhost:18789/ > /dev/null 2>&1; then
    echo "✅ Gateway is running"
    echo ""
    echo "🔄 Restarting gateway to load plugin..."

    # Restart gateway
    fuser -k 18789/tcp 2>/dev/null
    sleep 2
    cd ./
    nohup python3 gateway.py > gateway.log 2>&1 &
    sleep 3

    echo "✅ Gateway restarted"
else
    echo "❌ Gateway is not running"
    echo "   Start with: cd ./ && python3 gateway.py &"
fi

echo ""
echo "🧪 Running integration tests..."
./cline-plugin/test-integration.sh

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Cline Plugin Installation Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📚 Documentation: ./CLINE-OPENCLAW-INTEGRATION.md"
echo ""
echo "🎯 Next Steps:"
echo ""
echo "1. Install Cline in VS Code:"
echo "   code --install-extension saoudrizwan.claude-dev"
echo ""
echo "2. Configure Cline to poll OpenClaw:"
echo "   - Open VS Code"
echo "   - Install extension"
echo "   - Add polling script (see docs)"
echo ""
echo "3. Test it:"
echo "   # Send from OpenClaw to Cline"
echo "   curl -X POST http://localhost:18789/api/cline/send \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"message\": \"Hello Cline!\", \"action\": \"implement\"}'"
echo ""
echo "   # Cline polls and receives messages"
echo "   curl http://localhost:18789/api/cline/poll?since=0"
echo ""
echo "🎉 Happy coding with Cline + OpenClaw!"
