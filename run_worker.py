"""
OpenClaw Worker Startup Script
================================
Called by systemd for each pool worker (P0/P1/P2).
Reads OPENCLAW_POOL from environment, starts the runner loop.

Usage:
    OPENCLAW_POOL=p0 python3 run_worker.py
    OPENCLAW_POOL=p1 python3 run_worker.py
    OPENCLAW_POOL=p2 python3 run_worker.py
"""
import asyncio
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("run_worker")

from autonomous_runner import AutonomousRunner
from pool_config import get_pool_concurrency

pool = os.environ.get("OPENCLAW_POOL", "p2")
if pool not in ("p0", "p1", "p2"):
    logger.error(f"Invalid OPENCLAW_POOL={pool!r}. Must be p0, p1, or p2.")
    sys.exit(1)
concurrency = get_pool_concurrency(pool)

logger.info(f"Starting OpenClaw worker: pool={pool}, concurrency={concurrency}")

runner = AutonomousRunner(max_concurrent=concurrency)


async def main():
    await runner.start()
    # start() creates a background poll task; keep the event loop alive
    if runner._poll_task:
        await runner._poll_task


asyncio.run(main())
