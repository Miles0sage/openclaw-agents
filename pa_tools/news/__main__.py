"""
News tool entry point for CLI execution.
Allows: python3 -m pa_tools.news
"""

import asyncio
import json
from . import run_news_digest

if __name__ == "__main__":
    result = asyncio.run(run_news_digest())
    print(json.dumps(result, indent=2, default=str))
