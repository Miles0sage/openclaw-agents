"""OpenClaw project root configuration.

All modules should use PROJECT_ROOT instead of hardcoded paths.
Set OPENCLAW_ROOT env var to override (defaults to this file's directory).
"""
import os
from pathlib import Path

PROJECT_ROOT = os.environ.get("OPENCLAW_ROOT", str(Path(__file__).parent))
DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", os.path.join(PROJECT_ROOT, "data"))
