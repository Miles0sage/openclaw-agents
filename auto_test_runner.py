"""
Auto-Test Runner — Automatically run tests, detect failures, suggest fixes.

Supports: pytest, jest, vitest, go test, cargo test, mocha, vitest
- Detects test framework automatically
- Parses test failures into structured format
- Suggests fixes based on error analysis
- Can watch and auto-fix failing tests
- Generates coverage reports
"""

import subprocess
import json
import os
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path


class AutoTestRunner:
    """Run tests across multiple frameworks, parse results, suggest fixes."""

    FRAMEWORK_CONFIGS = {
        "pytest": {
            "detect": ["pytest.ini", "setup.py", "pyproject.toml", "conftest.py"],
            "run": "pytest {pattern} -v --tb=short --json-report --json-report-file=/tmp/pytest-report.json 2>&1",
            "run_fallback": "pytest {pattern} -v --tb=short 2>&1",
            "coverage": "pytest {pattern} --cov --cov-report=json 2>&1",
        },
        "jest": {
            "detect": ["jest.config.js", "jest.config.json", "package.json"],
            "run": "jest {pattern} --json --outputFile=/tmp/jest-report.json 2>&1",
            "run_fallback": "jest {pattern} 2>&1",
            "coverage": "jest {pattern} --coverage --json --outputFile=/tmp/jest-coverage.json 2>&1",
        },
        "vitest": {
            "detect": ["vitest.config.js", "vitest.config.ts"],
            "run": "vitest {pattern} --reporter=json --outputFile=/tmp/vitest-report.json 2>&1",
            "run_fallback": "vitest {pattern} 2>&1",
            "coverage": "vitest {pattern} --coverage --reporter=json --outputFile=/tmp/vitest-coverage.json 2>&1",
        },
        "mocha": {
            "detect": [".mocharc.json", ".mocharc.js", "test/mocha.opts"],
            "run": "mocha {pattern} --reporter json > /tmp/mocha-report.json 2>&1",
            "run_fallback": "mocha {pattern} 2>&1",
            "coverage": "nyc mocha {pattern} 2>&1",
        },
        "cargo": {
            "detect": ["Cargo.toml"],
            "run": "cargo test {pattern} -- --nocapture 2>&1",
            "run_fallback": "cargo test {pattern} 2>&1",
            "coverage": "cargo tarpaulin --out Json 2>&1",
        },
        "go": {
            "detect": ["go.mod"],
            "run": "go test {pattern} -v -json 2>&1",
            "run_fallback": "go test {pattern} -v 2>&1",
            "coverage": "go test {pattern} -cover 2>&1",
        },
    }

    def __init__(self):
        self.detected_framework = None
        self.test_results = {}

    def detect_framework(self, project_path: str) -> str:
        """Auto-detect test framework."""
        project_path = os.path.abspath(project_path)
        if not os.path.isdir(project_path):
            return "unknown"

        for framework, config in self.FRAMEWORK_CONFIGS.items():
            for marker in config["detect"]:
                if os.path.exists(os.path.join(project_path, marker)):
                    self.detected_framework = framework
                    return framework

        return "unknown"

    def run_tests(
        self,
        project_path: str,
        framework: str = "auto",
        test_pattern: str = None,
        verbose: bool = True,
    ) -> Dict:
        """
        Run tests and return structured results.

        Args:
            project_path: Directory to run tests in
            framework: "auto", "pytest", "jest", "vitest", "go", "cargo", "mocha"
            test_pattern: Glob pattern or specific test file
            verbose: Include full output

        Returns:
            {
                "status": "passed|failed|error",
                "framework": str,
                "duration_seconds": float,
                "total": int,
                "passed": int,
                "failed": int,
                "skipped": int,
                "failures": [{"test": str, "error": str, "file": str, "line": int, "suggestion": str}],
                "output": str (if verbose),
                "timestamp": str,
            }
        """
        project_path = os.path.abspath(project_path)
        if not os.path.isdir(project_path):
            return {
                "status": "error",
                "error": f"Directory not found: {project_path}",
                "timestamp": datetime.now().isoformat(),
            }

        # Auto-detect framework if needed
        if framework == "auto":
            framework = self.detect_framework(project_path)
            if framework == "unknown":
                return {
                    "status": "error",
                    "error": "Could not detect test framework. Specify explicitly: pytest|jest|vitest|go|cargo|mocha",
                    "timestamp": datetime.now().isoformat(),
                }

        if framework not in self.FRAMEWORK_CONFIGS:
            return {
                "status": "error",
                "error": f"Unsupported framework: {framework}",
                "timestamp": datetime.now().isoformat(),
            }

        config = self.FRAMEWORK_CONFIGS[framework]
        test_pattern = test_pattern or ""

        # Build command
        cmd = config["run"].format(pattern=test_pattern)
        if test_pattern == "":
            cmd = config["run_fallback"].format(pattern="")

        start_time = datetime.now()
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=300,  # 5 min timeout
            )
            duration = (datetime.now() - start_time).total_seconds()

            output = result.stdout + result.stderr
            parsed = self._parse_test_output(framework, output, project_path)
            parsed["duration_seconds"] = duration
            parsed["framework"] = framework
            parsed["timestamp"] = datetime.now().isoformat()

            if verbose:
                parsed["output"] = output[:5000]  # Limit output size

            self.test_results = parsed
            return parsed

        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "error": "Test run timed out after 300 seconds",
                "framework": framework,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "framework": framework,
                "timestamp": datetime.now().isoformat(),
            }

    def _parse_test_output(self, framework: str, output: str, project_path: str) -> Dict:
        """Parse test framework output into structured format."""
        result = {
            "status": "passed" if output.find("FAIL") == -1 else "failed",
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "failures": [],
        }

        if framework == "pytest":
            return self._parse_pytest(output, project_path, result)
        elif framework in ["jest", "vitest"]:
            return self._parse_jest_vitest(output, project_path, result)
        elif framework == "mocha":
            return self._parse_mocha(output, project_path, result)
        elif framework == "go":
            return self._parse_go(output, project_path, result)
        elif framework == "cargo":
            return self._parse_cargo(output, project_path, result)
        else:
            result["status"] = "unknown"
            return result

    def _parse_pytest(self, output: str, project_path: str, result: Dict) -> Dict:
        """Parse pytest output."""
        # Look for summary line: "X passed, Y failed, Z skipped"
        match = re.search(
            r"(\d+)\s+passed(?:\s*,\s*(\d+)\s+failed)?(?:\s*,\s*(\d+)\s+skipped)?",
            output,
        )
        if match:
            result["passed"] = int(match.group(1))
            result["failed"] = int(match.group(2) or 0)
            result["skipped"] = int(match.group(3) or 0)
            result["total"] = result["passed"] + result["failed"] + result["skipped"]

        # Extract failed tests
        failed_tests = re.finditer(
            r"FAILED\s+([^\s]+)\s*(?:-\s*(.+?))?(?:\n|$)", output
        )
        for match in failed_tests:
            test_name = match.group(1)
            error_msg = match.group(2) or ""

            # Try to extract file and line
            file_match = re.search(r"([^:]+):(\d+)", test_name)
            test_file = file_match.group(1) if file_match else "unknown"
            test_line = int(file_match.group(2)) if file_match else 0

            result["failures"].append(
                {
                    "test": test_name,
                    "error": error_msg[:200],
                    "file": test_file,
                    "line": test_line,
                    "suggestion": self._suggest_fix_pytest(error_msg, test_file),
                }
            )

        result["status"] = "failed" if result["failed"] > 0 else "passed"
        return result

    def _parse_jest_vitest(self, output: str, project_path: str, result: Dict) -> Dict:
        """Parse Jest/Vitest output."""
        # Summary line: "Tests:   X passed, Y total" or similar
        match = re.search(r"Tests:\s+(\d+)\s+passed,\s+(\d+)\s+total", output)
        if match:
            result["passed"] = int(match.group(1))
            result["total"] = int(match.group(2))
            result["failed"] = result["total"] - result["passed"]

        # Extract failed tests from "● Test Suite › test name"
        failed_tests = re.finditer(r"●\s+([^\n]+)\s+›\s+([^\n]+)", output)
        for match in failed_tests:
            suite = match.group(1)
            test_name = match.group(2)

            # Find error message following the test
            error_start = output.find(match.group(0))
            error_section = output[error_start : error_start + 500]
            error_match = re.search(r"(?:Error|AssertionError):\s+(.+?)(?:\n|at)", error_section)
            error_msg = error_match.group(1) if error_match else "Test failed"

            result["failures"].append(
                {
                    "test": f"{suite} › {test_name}",
                    "error": error_msg[:200],
                    "file": "unknown",
                    "line": 0,
                    "suggestion": self._suggest_fix_jest(error_msg),
                }
            )

        result["status"] = "failed" if result["failed"] > 0 else "passed"
        return result

    def _parse_mocha(self, output: str, project_path: str, result: Dict) -> Dict:
        """Parse Mocha output."""
        # Mocha summary: "X passing (123ms)" and "X failing"
        passing = re.search(r"(\d+)\s+passing", output)
        failing = re.search(r"(\d+)\s+failing", output)

        if passing:
            result["passed"] = int(passing.group(1))
        if failing:
            result["failed"] = int(failing.group(1))

        result["total"] = result["passed"] + result["failed"]

        # Extract failed tests
        failed_tests = re.finditer(
            r"(\d+\))\s+([^\n]+)\n(?:\s+([^\n]+))?", output
        )
        for i, match in enumerate(failed_tests):
            test_name = match.group(2)
            error_msg = match.group(3) or ""

            result["failures"].append(
                {
                    "test": test_name,
                    "error": error_msg[:200],
                    "file": "unknown",
                    "line": 0,
                    "suggestion": self._suggest_fix_mocha(error_msg),
                }
            )

        result["status"] = "failed" if result["failed"] > 0 else "passed"
        return result

    def _parse_go(self, output: str, project_path: str, result: Dict) -> Dict:
        """Parse Go test output."""
        # Go test: "ok package 0.123s" or "FAIL package"
        ok_match = re.search(r"ok\s+([^\s]+)\s+([\d.]+)s", output)
        fail_match = re.search(r"FAIL\s+([^\s]+)", output)

        if ok_match:
            result["passed"] = 1
            result["total"] = 1
            result["status"] = "passed"
        elif fail_match:
            result["failed"] = 1
            result["total"] = 1
            result["status"] = "failed"

        # Extract test failures
        failed_tests = re.finditer(r"---\s+FAIL:\s+([^\s]+)\s+\(", output)
        for match in failed_tests:
            test_name = match.group(1)
            error_start = output.find(match.group(0))
            error_section = output[error_start : error_start + 300]
            error_msg = error_section.split("\n")[1] if "\n" in error_section else ""

            result["failures"].append(
                {
                    "test": test_name,
                    "error": error_msg[:200],
                    "file": "unknown",
                    "line": 0,
                    "suggestion": self._suggest_fix_go(error_msg),
                }
            )

        return result

    def _parse_cargo(self, output: str, project_path: str, result: Dict) -> Dict:
        """Parse Cargo test output."""
        # Cargo: "test result: ok. X passed; Y failed"
        match = re.search(r"test result: (\w+)\.\s+(\d+)\s+passed", output)
        if match:
            result["status"] = match.group(1)
            result["passed"] = int(match.group(2))

        fail_match = re.search(r"(\d+)\s+failed", output)
        if fail_match:
            result["failed"] = int(fail_match.group(1))

        result["total"] = result["passed"] + result["failed"]

        # Extract failures
        failed_tests = re.finditer(r"test\s+([^\s]+)\s+\.\.\..*?FAILED", output)
        for match in failed_tests:
            test_name = match.group(1)
            result["failures"].append(
                {
                    "test": test_name,
                    "error": "Rust test failed",
                    "file": "unknown",
                    "line": 0,
                    "suggestion": "Run 'cargo test -- --nocapture' for more details",
                }
            )

        return result

    def _suggest_fix_pytest(self, error_msg: str, file_path: str) -> str:
        """Suggest fix for pytest failure."""
        error_lower = error_msg.lower()

        if "assertion" in error_lower or "assert" in error_lower:
            return "Check assertion logic. Use -vv flag for more details."
        elif "import" in error_lower or "importerror" in error_lower:
            return "Missing dependency. Run: pip install -e ."
        elif "fixture" in error_lower:
            return "Check fixture definition and scope."
        elif "timeout" in error_lower:
            return "Test is too slow. Increase timeout or optimize code."
        elif "undefined" in error_lower or "not found" in error_lower:
            return f"Check {file_path} for undefined references."
        else:
            return "Review test assumptions and dependencies."

    def _suggest_fix_jest(self, error_msg: str) -> str:
        """Suggest fix for Jest/Vitest failure."""
        error_lower = error_msg.lower()

        if "cannot find" in error_lower or "is not defined" in error_lower:
            return "Check imports and variable definitions."
        elif "expected" in error_lower:
            return "Assertion failed. Check expected vs actual values."
        elif "timeout" in error_lower:
            return "Async test timeout. Increase timeout or use done() callback."
        elif "module" in error_lower:
            return "Check module imports and exports."
        else:
            return "Add console.log() to debug test flow."

    def _suggest_fix_mocha(self, error_msg: str) -> str:
        """Suggest fix for Mocha failure."""
        return "Check test assertions and error handling."

    def _suggest_fix_go(self, error_msg: str) -> str:
        """Suggest fix for Go test failure."""
        return "Run: go test -v for detailed output."

    def analyze_failure(
        self, error_output: str, test_file: str = None, project_path: str = None
    ) -> Dict:
        """
        Analyze a test failure and suggest fixes.

        Args:
            error_output: Full error message from test
            test_file: Path to failing test file (optional)
            project_path: Project root for context (optional)

        Returns:
            {
                "root_cause": str,
                "suggestions": [str],
                "code_snippet": str,  # Relevant code from test file if available
                "related_files": [str],  # Other files that might be involved
            }
        """
        result = {
            "root_cause": "",
            "suggestions": [],
            "code_snippet": "",
            "related_files": [],
        }

        # Categorize error
        error_lower = error_output.lower()

        if "assertion" in error_lower:
            result["root_cause"] = "Assertion failure"
            result["suggestions"] = [
                "Verify expected vs actual values",
                "Check mock/stub setup",
                "Ensure test data is correct",
            ]
        elif "import" in error_lower or "module" in error_lower:
            result["root_cause"] = "Module/import error"
            result["suggestions"] = [
                "Install missing dependencies: npm install",
                "Check import paths are correct",
                "Verify files exist",
            ]
        elif "timeout" in error_lower:
            result["root_cause"] = "Test timeout"
            result["suggestions"] = [
                "Increase timeout: jest.setTimeout(10000)",
                "Optimize async operations",
                "Check for hanging promises",
            ]
        elif "undefined" in error_lower or "not defined" in error_lower:
            result["root_cause"] = "Undefined reference"
            result["suggestions"] = [
                "Check variable/function definitions",
                "Verify initialization order",
                "Look for typos in names",
            ]
        elif "type" in error_lower:
            result["root_cause"] = "Type error"
            result["suggestions"] = [
                "Check type annotations",
                "Verify method signatures",
                "Run type checker: tsc --noEmit",
            ]
        else:
            result["root_cause"] = "Unknown error"
            result["suggestions"] = ["Check error message carefully", "Add logging/debugging"]

        # Try to extract code snippet if test file available
        if test_file and os.path.exists(test_file):
            try:
                with open(test_file, "r") as f:
                    content = f.read()
                    lines = content.split("\n")
                    # Get first 10 lines
                    result["code_snippet"] = "\n".join(lines[:10])
            except Exception:
                pass

        return result

    def watch_and_fix(self, project_path: str, framework: str = "auto") -> Dict:
        """
        Run tests, analyze failures, suggest patches.

        Returns:
            {
                "status": "passed|fixed|still_failing",
                "initial_failures": int,
                "fixes_attempted": int,
                "final_status": "passed|failed",
                "patches": [{file, old_code, new_code, explanation}],
                "report": str,
            }
        """
        project_path = os.path.abspath(project_path)

        # Initial test run
        result = self.run_tests(project_path, framework=framework, verbose=True)

        if result.get("status") == "passed":
            return {
                "status": "passed",
                "initial_failures": 0,
                "fixes_attempted": 0,
                "final_status": "passed",
                "patches": [],
                "report": "All tests passing! No fixes needed.",
            }

        initial_failures = result.get("failed", 0)
        failures = result.get("failures", [])

        # Analyze failures
        analysis = {
            "status": "still_failing",
            "initial_failures": initial_failures,
            "fixes_attempted": len(failures),
            "final_status": "failed",
            "patches": [],
            "report": f"Found {initial_failures} failing tests. Suggestions generated.",
        }

        for failure in failures[:3]:  # Limit to first 3 for now
            fix_analysis = self.analyze_failure(
                failure.get("error", ""), failure.get("file", ""), project_path
            )

            analysis["patches"].append(
                {
                    "test": failure.get("test"),
                    "root_cause": fix_analysis["root_cause"],
                    "suggestions": fix_analysis["suggestions"],
                    "code_snippet": fix_analysis.get("code_snippet", ""),
                }
            )

        return analysis

    def coverage_report(self, project_path: str, framework: str = "auto") -> Dict:
        """
        Generate coverage report.

        Returns:
            {
                "status": "success|error",
                "framework": str,
                "total_coverage": float,  # 0-100
                "uncovered_lines": [str],
                "uncovered_functions": [str],
                "report_file": str,
            }
        """
        project_path = os.path.abspath(project_path)

        if framework == "auto":
            framework = self.detect_framework(project_path)

        config = self.FRAMEWORK_CONFIGS.get(framework, {})
        coverage_cmd = config.get("coverage", "")

        if not coverage_cmd:
            return {
                "status": "error",
                "error": f"Coverage not supported for {framework}",
                "framework": framework,
            }

        try:
            result = subprocess.run(
                coverage_cmd,
                shell=True,
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=300,
            )

            output = result.stdout + result.stderr

            # Extract coverage percentage
            coverage_match = re.search(r"(\d+(?:\.\d+)?)\s*%", output)
            total_coverage = float(coverage_match.group(1)) if coverage_match else 0.0

            return {
                "status": "success",
                "framework": framework,
                "total_coverage": total_coverage,
                "uncovered_lines": [],  # Would need detailed parsing
                "uncovered_functions": [],
                "report_file": "/tmp/coverage-report.json",
                "output": output[:2000],
            }

        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "framework": framework,
            }


# Singleton instance
_runner = AutoTestRunner()


def run_tests(
    project_path: str, framework: str = "auto", test_pattern: str = None, verbose: bool = True
) -> str:
    """Run tests and return JSON results."""
    result = _runner.run_tests(project_path, framework, test_pattern, verbose)
    return json.dumps(result, indent=2)


def analyze_failure(error_output: str, test_file: str = None) -> str:
    """Analyze failure and suggest fixes."""
    result = _runner.analyze_failure(error_output, test_file)
    return json.dumps(result, indent=2)


def watch_and_fix(project_path: str, framework: str = "auto") -> str:
    """Run tests, analyze, suggest fixes."""
    result = _runner.watch_and_fix(project_path, framework)
    return json.dumps(result, indent=2)


def coverage_report(project_path: str, framework: str = "auto") -> str:
    """Generate coverage report."""
    result = _runner.coverage_report(project_path, framework)
    return json.dumps(result, indent=2)
