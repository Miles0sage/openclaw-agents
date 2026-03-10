#!/usr/bin/env python3
"""OpenClaw Agents — First-time setup.

Creates required data directories and validates configuration.
Run this once after cloning: python setup.py
"""

import os
import sys

DATA_DIR = os.getenv("OPENCLAW_DATA_DIR", "./data")

REQUIRED_DIRS = [
    f"{DATA_DIR}/clients",
    f"{DATA_DIR}/costs",
    f"{DATA_DIR}/jobs",
    f"{DATA_DIR}/logs",
    f"{DATA_DIR}/reflections",
    f"{DATA_DIR}/memory",
    f"{DATA_DIR}/hands",
    f"{DATA_DIR}/events",
    f"{DATA_DIR}/sessions",
    f"{DATA_DIR}/evals",
    f"{DATA_DIR}/proposals",
    f"{DATA_DIR}/coding_factory",
    f"{DATA_DIR}/benchmarks",
]

REQUIRED_STATIC_DIRS = [
    "static",
    "templates",
    "public/dashboard",
]


def main():
    print("OpenClaw Agents — Setup")
    print("=" * 40)

    # Create data directories
    created = 0
    for d in REQUIRED_DIRS + REQUIRED_STATIC_DIRS:
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
            created += 1
            print(f"  Created: {d}/")

    if created == 0:
        print("  All directories already exist.")
    else:
        print(f"  Created {created} directories.")

    # Check .env
    print()
    if os.path.exists(".env"):
        with open(".env") as f:
            env_content = f.read()
        if "GATEWAY_AUTH_TOKEN=" in env_content:
            token_line = [l for l in env_content.splitlines() if l.startswith("GATEWAY_AUTH_TOKEN=")]
            if token_line and token_line[0].split("=", 1)[1].strip():
                print("  .env: GATEWAY_AUTH_TOKEN is set")
            else:
                print("  WARNING: GATEWAY_AUTH_TOKEN is empty in .env — gateway won't start without it")
        else:
            print("  WARNING: GATEWAY_AUTH_TOKEN not found in .env — add it before starting")

        has_llm = any(
            k in env_content
            for k in ["ANTHROPIC_API_KEY=sk", "DEEPSEEK_API_KEY=sk", "GEMINI_API_KEY=AI",
                       "OPENROUTER_API_KEY=sk", "MINIMAX_API_KEY="]
        )
        if has_llm:
            print("  .env: LLM provider key detected")
        else:
            print("  WARNING: No LLM provider API key found — jobs will queue but won't execute")
    else:
        print("  WARNING: .env not found — copy .env.example to .env and configure it")

    print()
    print("Setup complete. Start the gateway with: python gateway.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
