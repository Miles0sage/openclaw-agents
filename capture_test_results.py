#!/usr/bin/env python3
"""Run n8n webhook tests via pytest.main() and save results."""
import sys
import os
import io

os.chdir('.')
sys.path.insert(0, '.')

# Capture output
import pytest

class OutputCapture:
    def __init__(self):
        self.lines = []

    def write(self, s):
        self.lines.append(s)
        sys.__stdout__.write(s)

    def flush(self):
        sys.__stdout__.flush()

    def fileno(self):
        return sys.__stdout__.fileno()

cap = OutputCapture()
sys.stdout = cap
sys.stderr = cap

exit_code = pytest.main([
    'test_n8n_webhook.py',
    '--tb=short',
    '-v',
    '--no-header',
])

sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__

output = ''.join(cap.lines)
with open('./test_results.txt', 'w') as f:
    f.write(output)
    f.write(f'\n\nExit code: {exit_code}\n')

print(f"Tests done. Exit code: {exit_code}")
print(f"Results saved to test_results.txt")
