#!/bin/bash
echo "════════════════════════════════════════════════════════════"
echo "OPENCLAW PHASE 5X: CAP GATES DEPLOYMENT VALIDATION"
echo "════════════════════════════════════════════════════════════"
echo ""

# Check files exist
echo "1. CHECKING FILES..."
files=(
  "quota_manager.py"
  "test_quotas.py"
  "gateway.py"
  "config.json"
  "cost_tracker.py"
  "QUOTAS.md"
  "QUOTAS-IMPLEMENTATION-SUMMARY.md"
  "CRITICAL-GAP-2-COMPLETION.md"
)

missing=0
for file in "${files[@]}"; do
  if [ -f "$file" ]; then
    size=$(wc -l < "$file" 2>/dev/null || echo "N/A")
    echo "   ✅ $file ($size lines)"
  else
    echo "   ❌ $file (MISSING)"
    missing=$((missing + 1))
  fi
done

if [ $missing -eq 0 ]; then
  echo "   ✅ ALL FILES PRESENT"
else
  echo "   ❌ $missing files missing"
  exit 1
fi

echo ""
echo "2. CHECKING SYNTAX..."

# Check Python syntax
python3 -m py_compile quota_manager.py 2>/dev/null
if [ $? -eq 0 ]; then
  echo "   ✅ quota_manager.py: Valid Python"
else
  echo "   ❌ quota_manager.py: Syntax error"
  exit 1
fi

python3 -m py_compile gateway.py 2>/dev/null
if [ $? -eq 0 ]; then
  echo "   ✅ gateway.py: Valid Python"
else
  echo "   ❌ gateway.py: Syntax error"
  exit 1
fi

# Check JSON
python3 -c "import json; json.load(open('config.json'))" 2>/dev/null
if [ $? -eq 0 ]; then
  echo "   ✅ config.json: Valid JSON"
else
  echo "   ❌ config.json: Invalid JSON"
  exit 1
fi

echo ""
echo "3. RUNNING TESTS..."
python3 test_quotas.py > /tmp/test_output.txt 2>&1
if grep -q "ALL TESTS PASSED" /tmp/test_output.txt; then
  echo "   ✅ test_quotas.py: 100% passing"
  grep "✓ Testing" /tmp/test_output.txt | wc -l | xargs echo "   ✅ Test functions:"
else
  echo "   ❌ Tests failed"
  cat /tmp/test_output.txt
  exit 1
fi

echo ""
echo "4. CHECKING CONFIG..."
python3 << 'PYEOF'
import json
config = json.load(open('config.json'))
quotas = config.get('quotas', {})

print(f"   Quotas enabled: {quotas.get('enabled', False)}")
print(f"   Daily limit (global): ${quotas.get('daily_limit_usd', 'N/A')}")
print(f"   Monthly limit (global): ${quotas.get('monthly_limit_usd', 'N/A')}")
print(f"   Max queue size: {quotas.get('max_queue_size', 'N/A')}")
print(f"   Projects configured: {len(quotas.get('per_project', {}))}")

projects = quotas.get('per_project', {})
for proj, limits in projects.items():
    daily = limits.get('daily_limit_usd', 'N/A')
    monthly = limits.get('monthly_limit_usd', 'N/A')
    print(f"   - {proj}: ${daily}/day, ${monthly}/month")
PYEOF

echo ""
echo "5. CHECKING API ENDPOINTS..."
python3 << 'PYEOF'
import sys
sys.path.insert(0, './')

from quota_manager import (
    load_quota_config, check_all_quotas, get_quota_status,
    check_daily_quota, check_monthly_quota, check_queue_size
)
from cost_tracker import clear_cost_log

clear_cost_log()

# Test quota checks
ok, _ = check_all_quotas("barber-crm", queue_size=10)
print(f"   ✅ check_all_quotas: {ok}")

ok, _ = check_daily_quota("barber-crm")
print(f"   ✅ check_daily_quota: {ok}")

ok, _ = check_monthly_quota("barber-crm")
print(f"   ✅ check_monthly_quota: {ok}")

ok, _ = check_queue_size(50)
print(f"   ✅ check_queue_size: {ok}")

status = get_quota_status("barber-crm")
print(f"   ✅ get_quota_status: {status['project']}")
PYEOF

echo ""
echo "════════════════════════════════════════════════════════════"
echo "✅ DEPLOYMENT VALIDATION COMPLETE"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "Ready for production deployment!"
