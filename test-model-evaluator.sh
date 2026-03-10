#!/bin/bash

#############################################
# Test Model Evaluator
# Quick validation script
#############################################

echo "🧪 Testing Model Evaluator"
echo "=========================="
echo ""

# Check dependencies
echo "📦 Checking dependencies..."

if python3 -c "import anthropic" 2>/dev/null; then
    echo "✅ anthropic library installed"
else
    echo "❌ anthropic library missing"
    echo "   Install: pip3 install anthropic"
    exit 1
fi

if python3 -c "import requests" 2>/dev/null; then
    echo "✅ requests library installed"
else
    echo "❌ requests library missing"
    echo "   Install: pip3 install requests"
    exit 1
fi

echo ""

# Check API keys
echo "🔑 Checking API keys..."

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "⚠️  ANTHROPIC_API_KEY not set"
    echo "   Export it: export ANTHROPIC_API_KEY='your-key'"
    echo "   Skipping Anthropic models..."
else
    echo "✅ ANTHROPIC_API_KEY found"
fi

echo ""

# Check Ollama
echo "🔥 Checking Ollama..."

if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "✅ Ollama is running"
    echo "   Models available:"
    curl -s http://localhost:11434/api/tags | jq -r '.models[].name' | head -5 | sed 's/^/      - /'
else
    echo "⚠️  Ollama not running"
    echo "   Start it: ollama serve &"
    echo "   Skipping Ollama models..."
fi

echo ""

# Verify evaluator script exists
if [ ! -f "model-evaluator.py" ]; then
    echo "❌ model-evaluator.py not found"
    echo "   Make sure you're in ./"
    exit 1
fi

echo "✅ model-evaluator.py found"
echo ""

# Ask to run
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 Ready to run evaluation!"
echo ""
echo "This will:"
echo "  1. Test all available models"
echo "  2. Run 5 capability tests"
echo "  3. Generate comparison report"
echo "  4. Save results to JSON"
echo ""
echo "Estimated time: 2-5 minutes"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

read -p "Run evaluation now? (y/n) [y]: " RUN_IT
RUN_IT=${RUN_IT:-y}

if [[ $RUN_IT =~ ^[Yy]$ ]]; then
    echo ""
    echo "🧪 Running evaluation..."
    echo ""

    python3 model-evaluator.py

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "✅ Evaluation complete!"
    echo ""

    if [ -f "model_evaluation_results.json" ]; then
        echo "📄 Results saved to: model_evaluation_results.json"
        echo ""
        echo "📊 Quick summary:"
        python3 -c "
import json
with open('model_evaluation_results.json') as f:
    data = json.load(f)
    print(f\"   Models tested: {len(data['models'])}\")
    print(f\"   Tests run: {len(data['results'])}\")
    print(f\"   Total time: ~{sum(r.get('latency_ms', 0) for r in data['results']) / 1000:.1f}s\")
" 2>/dev/null || echo "   (Install jq for detailed stats)"
    fi

    echo ""
    echo "📚 Next steps:"
    echo "   - View full guide: cat MODEL-EVALUATION-GUIDE.md"
    echo "   - Review results: cat model_evaluation_results.json | jq"
    echo "   - Run again: python3 model-evaluator.py"
    echo ""
else
    echo ""
    echo "👍 Skipped. Run manually with:"
    echo "   python3 model-evaluator.py"
    echo ""
fi
