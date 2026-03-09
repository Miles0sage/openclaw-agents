"""
Travel tool entry point for CLI execution.
Allows: python3 -m pa_tools.travel
"""

import asyncio
import json
from . import run_travel_planning

if __name__ == "__main__":
    result = asyncio.run(run_travel_planning())
    print(json.dumps(result, indent=2, default=str))
