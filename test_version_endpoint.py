#!/usr/bin/env python3
"""Test script to verify the /api/version endpoint"""

import json
import sys

# Read the gateway.py file and extract the endpoint function
with open('gateway.py', 'r') as f:
    content = f.read()

# Check if the endpoint is present
if '@app.get("/api/version")' not in content:
    print("❌ FAIL: /api/version endpoint not found")
    sys.exit(1)

# Extract the endpoint code
import re
pattern = r'@app\.get\("/api/version"\)\s*\nasync def api_get_version\(\):\s*\n\s*"""[^"]*"""\s*\n\s*return\s*({[^}]+})'
match = re.search(pattern, content)

if not match:
    print("❌ FAIL: Could not extract endpoint implementation")
    sys.exit(1)

# Parse the return value
try:
    return_str = match.group(1)
    # Use ast.literal_eval instead of json.loads for dict literals
    import ast
    expected_return = ast.literal_eval(return_str)
except Exception as e:
    print(f"❌ FAIL: Could not parse return value: {e}")
    sys.exit(1)

# Verify the response
expected = {
    "version": "4.2.0",
    "name": "openclaw",
    "engine": "autonomous_runner"
}

if expected_return == expected:
    print("✅ PASS: /api/version endpoint returns correct JSON")
    print(f"   Response: {json.dumps(expected_return, indent=2)}")
    sys.exit(0)
else:
    print("❌ FAIL: /api/version endpoint returns unexpected JSON")
    print(f"   Expected: {json.dumps(expected, indent=2)}")
    print(f"   Got: {json.dumps(expected_return, indent=2)}")
    sys.exit(1)
