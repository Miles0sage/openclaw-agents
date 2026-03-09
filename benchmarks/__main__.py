"""CLI entrypoint for benchmark suite.

Examples:
    python -m benchmarks --suite=easy
    python -m benchmarks --problem benchmarks/problems/easy/fix-button-color.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from benchmarks.problem import load_problem
from benchmarks.reporter import generate_markdown
from benchmarks.runner import BenchmarkRunner



def main() -> None:
    parser = argparse.ArgumentParser(description="OpenClaw Benchmark Runner")
    parser.add_argument("--suite", default="all", help="Suite to run: easy, medium, hard, all")
    parser.add_argument("--problem", default="", help="Run a single problem by YAML path")
    parser.add_argument("--output", default="", help="Output JSON path")
    parser.add_argument("--report", default="", help="Output Markdown report path")
    parser.add_argument("--concurrent", type=int, default=3, help="Max concurrent problems")
    parser.add_argument("--pass-threshold", type=float, default=0.0, help="Min pass rate required to exit 0")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    runner = BenchmarkRunner(max_concurrent=args.concurrent)
    problems_dir = Path(__file__).parent / "problems"

    if args.problem:
        problem = load_problem(args.problem)
        result = asyncio.run(runner.run_single(problem))
        print(json.dumps(result.to_dict(), indent=2))
        raise SystemExit(0 if result.passed else 1)

    suite_dir = str(problems_dir) if args.suite == "all" else str(problems_dir / args.suite)
    suite_result = asyncio.run(runner.run_suite(suite_dir, suite_name=args.suite))

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(suite_result.to_dict(), handle, indent=2)

    report_text = generate_markdown(suite_result)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            handle.write(report_text)

    print(report_text)

    if args.pass_threshold > 0 and suite_result.pass_rate < args.pass_threshold:
        print(
            f"\nFAILED: Pass rate {suite_result.pass_rate:.0%} < threshold {args.pass_threshold:.0%}"
        )
        raise SystemExit(1)

    raise SystemExit(0)


if __name__ == "__main__":
    main()
