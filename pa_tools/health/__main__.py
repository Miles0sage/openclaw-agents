"""
Health tool entry point for CLI execution.
Allows: python3 -m pa_tools.health
"""

import asyncio
import json
from . import run_health_check

if __name__ == "__main__":
    result = asyncio.run(run_health_check())
    print(json.dumps(result, indent=2, default=str))
