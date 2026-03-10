"""
pytest conftest.py for openclaw test suite.

Sets required environment variables before any test module imports occur,
preventing RuntimeError from gateway.py's module-level auth token check.
"""

import os
import sys

# Must be set before `from gateway import app` — gateway.py raises RuntimeError
# at import time if GATEWAY_AUTH_TOKEN is absent.
os.environ.setdefault("GATEWAY_AUTH_TOKEN", "test-token-for-pytest")

# Default data dir for tests (can be overridden per-test via monkeypatch)
os.environ.setdefault("OPENCLAW_DATA_DIR", "/tmp/openclaw-test-data")

# Ensure openclaw root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
