"""
Finance tool entry point for CLI execution.
Allows: python3 -m pa_tools.finance
"""

import asyncio
import json
from . import run_finance_check

if __name__ == "__main__":
    result = asyncio.run(run_finance_check())
    print(json.dumps(result, indent=2, default=str))
