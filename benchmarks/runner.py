"""Benchmark runner for OpenClaw benchmark problems."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmarks.problem import BenchmarkProblem, load_problem, load_suite
from benchmarks.scorer import BenchmarkScorer

logger = logging.getLogger("openclaw.benchmarks")

RESULTS_DIR = Path(__file__).parent / "results"


@dataclass
class ProblemResult:
    problem_id: str
    category: str
    difficulty: str
    passed: bool
    overall_score: float
    file_checks_passed: int
    file_checks_total: int
    command_checks_passed: int
    command_checks_total: int
    cost_usd: float
    duration_sec: float
    agent_key: str
    error: str = ""
    dimension_scores: dict[str, float] = field(default_factory=dict)
    tools_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "category": self.category,
            "difficulty": self.difficulty,
            "passed": self.passed,
            "overall_score": round(self.overall_score, 4),
            "file_checks": f"{self.file_checks_passed}/{self.file_checks_total}",
            "command_checks": f"{self.command_checks_passed}/{self.command_checks_total}",
            "cost_usd": round(self.cost_usd, 4),
            "duration_sec": round(self.duration_sec, 2),
            "agent_key": self.agent_key,
            "error": self.error,
            "dimensions": self.dimension_scores,
            "tools_used": self.tools_used,
        }


@dataclass
class SuiteResult:
    suite_name: str
    timestamp: str
    total: int
    passed: int
    failed: int
    pass_rate: float
    avg_score: float
    total_cost_usd: float
    total_duration_sec: float
    by_difficulty: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_category: dict[str, dict[str, Any]] = field(default_factory=dict)
    results: list[ProblemResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_name": self.suite_name,
            "timestamp": self.timestamp,
            "summary": {
                "total": self.total,
                "passed": self.passed,
                "failed": self.failed,
                "pass_rate": round(self.pass_rate, 4),
                "avg_score": round(self.avg_score, 4),
                "total_cost_usd": round(self.total_cost_usd, 4),
                "total_duration_sec": round(self.total_duration_sec, 2),
            },
            "by_difficulty": self.by_difficulty,
            "by_category": self.by_category,
            "results": [r.to_dict() for r in self.results],
        }


class BenchmarkRunner:
    """Runs benchmark problems through OpenClaw and validates outcomes."""

    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max(1, int(max_concurrent))
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._scorer = BenchmarkScorer()

    async def run_suite(self, suite_dir: str, suite_name: str = "default") -> SuiteResult:
        problems = load_suite(suite_dir)
        logger.info("Loaded %s benchmark problems from %s", len(problems), suite_dir)

        tasks = [self._run_with_semaphore(problem) for problem in problems]
        results = await asyncio.gather(*tasks)
        results = [r for r in results if r is not None]

        passed = sum(1 for r in results if r.passed)
        avg_score = (sum(r.overall_score for r in results) / len(results)) if results else 0.0

        by_difficulty: dict[str, dict[str, Any]] = {}
        for r in results:
            node = by_difficulty.setdefault(r.difficulty, {"total": 0, "passed": 0})
            node["total"] += 1
            if r.passed:
                node["passed"] += 1
        for node in by_difficulty.values():
            node["pass_rate"] = (node["passed"] / node["total"]) if node["total"] else 0.0

        by_category: dict[str, dict[str, Any]] = {}
        for r in results:
            node = by_category.setdefault(r.category, {"total": 0, "passed": 0})
            node["total"] += 1
            if r.passed:
                node["passed"] += 1
        for node in by_category.values():
            node["pass_rate"] = (node["passed"] / node["total"]) if node["total"] else 0.0

        suite_result = SuiteResult(
            suite_name=suite_name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            total=len(results),
            passed=passed,
            failed=len(results) - passed,
            pass_rate=(passed / len(results)) if results else 0.0,
            avg_score=avg_score,
            total_cost_usd=sum(r.cost_usd for r in results),
            total_duration_sec=sum(r.duration_sec for r in results),
            by_difficulty=by_difficulty,
            by_category=by_category,
            results=results,
        )
        self._save_results(suite_result)
        return suite_result

    async def run_single(self, problem: BenchmarkProblem) -> ProblemResult:
        logger.info("Running benchmark %s (%s)", problem.id, problem.difficulty)
        start = time.time()
        workspace = tempfile.mkdtemp(prefix=f"bench_{problem.id}_")
        try:
            self._setup_workspace(problem, workspace)
            job_result = await self._submit_job(problem, workspace)

            file_passed, file_total = self._check_files(problem, workspace)
            cmd_passed, cmd_total = self._check_commands(problem, workspace)

            score = await self._scorer.score(
                problem_id=problem.id,
                agent_key=problem.agent_key,
                task_description=problem.description,
                job_result=job_result,
            )

            duration = time.time() - start
            cost = float(job_result.get("cost_usd", 0.0) or 0.0)
            tools = [str(t) for t in (job_result.get("tools_used") or [])]

            checks_pass = file_passed == file_total and cmd_passed == cmd_total
            score_pass = score.overall_score >= problem.min_quality_score
            budget_pass = cost <= problem.max_cost_usd
            time_pass = duration <= problem.max_duration_sec
            overall_pass = checks_pass and budget_pass and time_pass and (score_pass or score.overall_score == 0.0)

            self._record_kg(problem, overall_pass, tools, cost, duration, score.overall_score)

            return ProblemResult(
                problem_id=problem.id,
                category=problem.category,
                difficulty=problem.difficulty,
                passed=overall_pass,
                overall_score=score.overall_score,
                file_checks_passed=file_passed,
                file_checks_total=file_total,
                command_checks_passed=cmd_passed,
                command_checks_total=cmd_total,
                cost_usd=cost,
                duration_sec=duration,
                agent_key=problem.agent_key,
                dimension_scores=score.dimension_scores,
                tools_used=tools,
                error="" if overall_pass else str(job_result.get("error", "")),
            )
        except Exception as exc:
            return ProblemResult(
                problem_id=problem.id,
                category=problem.category,
                difficulty=problem.difficulty,
                passed=False,
                overall_score=0.0,
                file_checks_passed=0,
                file_checks_total=len(problem.file_expectations),
                command_checks_passed=0,
                command_checks_total=len(problem.command_expectations),
                cost_usd=0.0,
                duration_sec=time.time() - start,
                agent_key=problem.agent_key,
                error=str(exc),
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    async def _run_with_semaphore(self, problem: BenchmarkProblem) -> ProblemResult:
        async with self._semaphore:
            return await self.run_single(problem)

    def _setup_workspace(self, problem: BenchmarkProblem, workspace: str) -> None:
        for fs in problem.setup_files:
            target = os.path.join(workspace, fs.path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(fs.content)

        for cmd in problem.setup_commands:
            subprocess.run(cmd, shell=True, cwd=workspace, timeout=30, capture_output=True, text=True)

    def _check_files(self, problem: BenchmarkProblem, workspace: str) -> tuple[int, int]:
        passed = 0
        total = len(problem.file_expectations)
        for exp in problem.file_expectations:
            path = os.path.join(workspace, exp.path)
            if exp.must_exist and not os.path.exists(path):
                continue
            if not exp.must_exist and not os.path.exists(path):
                passed += 1
                continue
            if not os.path.exists(path):
                continue

            with open(path, "r", encoding="utf-8") as handle:
                content = handle.read()

            ok = True
            for needle in exp.contains:
                if needle not in content:
                    ok = False
            for needle in exp.not_contains:
                if needle in content:
                    ok = False
            for pattern in exp.regex_match:
                if not re.search(pattern, content):
                    ok = False
            if ok:
                passed += 1
        return passed, total

    def _check_commands(self, problem: BenchmarkProblem, workspace: str) -> tuple[int, int]:
        passed = 0
        total = len(problem.command_expectations)
        for exp in problem.command_expectations:
            try:
                proc = subprocess.run(
                    exp.command,
                    shell=True,
                    cwd=workspace,
                    timeout=30,
                    capture_output=True,
                    text=True,
                )
            except subprocess.TimeoutExpired:
                continue

            ok = proc.returncode == exp.exit_code
            for needle in exp.stdout_contains:
                if needle not in proc.stdout:
                    ok = False
            for needle in exp.stdout_not_contains:
                if needle in proc.stdout:
                    ok = False
            if ok:
                passed += 1
        return passed, total

    async def _submit_job(self, problem: BenchmarkProblem, workspace: str) -> dict[str, Any]:
        backend = os.getenv("OPENCLAW_BENCH_BACKEND", "mock").strip().lower()
        if backend == "api":
            return await self._submit_via_api(problem, workspace)

        # Default mock backend keeps local test/CI deterministic.
        return {
            "status": "done",
            "cost_usd": 0.0,
            "tools_used": [],
            "backend": "mock",
            "job_request": problem.to_job_request(workspace),
        }

    async def _submit_via_api(self, problem: BenchmarkProblem, workspace: str) -> dict[str, Any]:
        base_url = os.getenv("OPENCLAW_API_URL", "http://localhost:18789").rstrip("/")
        token = os.getenv("OPENCLAW_AUTH_TOKEN", "")
        api_key = os.getenv("OPENCLAW_API_KEY", "")

        payload = json.dumps(problem.to_job_request(workspace)).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if token:
            headers["X-Auth-Token"] = token
        if api_key:
            headers["X-API-Key"] = api_key

        req = urllib.request.Request(f"{base_url}/api/jobs", data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            return {"status": "error", "error": f"submit failed: {exc}"}
        except json.JSONDecodeError:
            return {"status": "error", "error": "submit failed: invalid json"}

        job_id = body.get("job_id") or body.get("id")
        if not job_id:
            return {"status": "error", "error": "submit failed: missing job_id", "raw": body}

        deadline = time.time() + problem.max_duration_sec
        while time.time() < deadline:
            status_req = urllib.request.Request(f"{base_url}/api/jobs/{job_id}", headers=headers, method="GET")
            try:
                with urllib.request.urlopen(status_req, timeout=20) as response:
                    status_data = json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                return {"status": "error", "error": f"poll failed: {exc}", "job_id": job_id}

            status = str(status_data.get("status", "")).lower()
            if status in {"done", "failed", "error", "cancelled", "success", "completed"}:
                return status_data
            await asyncio.sleep(2)

        return {"status": "timeout", "error": "Exceeded max duration", "job_id": job_id}

    def _record_kg(self, problem: BenchmarkProblem, success: bool, tools: list[str], cost: float, duration: float, quality_score: float) -> None:
        try:
            from kg_engine import get_kg_engine

            kg = get_kg_engine()
            if not kg:
                return
            kg.record_execution(
                job_id=f"bench_{problem.id}",
                agent_key=problem.agent_key,
                tools_used=tools,
                success=success,
                task_type=problem.category,
                cost_usd=cost,
                duration_ms=duration * 1000,
                quality_score=quality_score,
            )
        except Exception:
            pass

    def _save_results(self, suite: SuiteResult) -> None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

        timestamped = RESULTS_DIR / f"{suite.suite_name}_{ts}.json"
        with open(timestamped, "w", encoding="utf-8") as handle:
            json.dump(suite.to_dict(), handle, indent=2)

        latest = RESULTS_DIR / f"{suite.suite_name}_latest.json"
        with open(latest, "w", encoding="utf-8") as handle:
            json.dump(suite.to_dict(), handle, indent=2)

        logger.info("Saved benchmark results to %s and %s", timestamped, latest)
