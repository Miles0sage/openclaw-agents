#!/usr/bin/env python3
"""Script to run n8n webhook tests and capture output."""
import subprocess
import sys

result = subprocess.run(
    [sys.executable, '-m', 'pytest', 'test_n8n_webhook.py', '--tb=short', '-v'],
    cwd='.',
    capture_output=True,
    text=True
)

output = result.stdout + result.stderr

with open('./test_results.txt', 'w') as f:
    f.write(output)

print(output)
print(f"\nExit code: {result.returncode}")
