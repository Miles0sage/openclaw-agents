"""
PA Tools orchestrator entry point for CLI execution.
Allows: python3 -m pa_tools
"""

import asyncio
import json
from .orchestrator import PAOrchestrator

if __name__ == "__main__":
    orchestrator = PAOrchestrator()

    # Run all daily tasks
    result = asyncio.run(orchestrator.run_all_daily())
    print(json.dumps(result, indent=2, default=str))
