"""
Output Verification & Quality Gate System for OpenClaw

Verifies agent output quality BEFORE delivery to the user.
This is the last check before code gets committed or deployed.

Six quality gates:
  1. Syntax Check    - Valid code (Python, JS/TS, JSON, HTML)
  2. Security Scan   - Hardcoded secrets, injection patterns, XSS
  3. Test Runner     - Execute tests if they exist
  4. Lint Check      - Available linters + debug statement detection
  5. Diff Validator  - Git diff sanity checks
  6. Cost Gate       - Budget enforcement (per-job, daily, monthly)

Standalone module. Imports only stdlib + subprocess.
"""

import ast
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    """Result from a single quality gate."""
    gate: str       # "syntax", "security", "tests", "lint", "diff", "cost"
    passed: bool
    score: int      # 0-100
    issues: list    # [{"severity": "high", "message": "...", "file": "...", "line": 42}]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VerificationResult:
    """Aggregated result from all quality gates."""
    passed: bool            # All gates passed
    overall_score: int      # 0-100 weighted average
    gates: list             # list[GateResult]
    summary: str            # Human-readable summary
    recommendation: str     # "approve", "fix_and_retry", "reject"

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "overall_score": self.overall_score,
            "gates": [g.to_dict() for g in self.gates],
            "summary": self.summary,
            "recommendation": self.recommendation,
        }


# ---------------------------------------------------------------------------
# Security patterns
# ---------------------------------------------------------------------------

SECRET_PATTERNS: list[tuple[str, str, str]] = [
    # (name, regex, severity)
    ("AWS Access Key", r"AKIA[0-9A-Z]{16}", "critical"),
    ("OpenAI/Anthropic API Key", r"sk-[a-zA-Z0-9]{20,}", "critical"),
    ("GitHub Token", r"ghp_[a-zA-Z0-9]{36}", "critical"),
    ("GitHub OAuth Token", r"gho_[a-zA-Z0-9]{36}", "critical"),
    ("GitHub App Token", r"ghs_[a-zA-Z0-9]{36}", "critical"),
    ("Slack Token", r"xox[bpsa]-[a-zA-Z0-9\-]{10,}", "critical"),
    ("Stripe Secret Key", r"sk_live_[a-zA-Z0-9]{24,}", "critical"),
    ("Stripe Test Key", r"sk_test_[a-zA-Z0-9]{24,}", "medium"),
    ("Private Key Block", r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----", "critical"),
    ("Hardcoded Password Assignment",
     r"""(?:password|passwd|pwd|secret)\s*=\s*["'][^"']{4,}["']""", "high"),
    ("Hardcoded Token Assignment",
     r"""(?:token|api_key|apikey|auth_key)\s*=\s*["'][^"']{8,}["']""", "high"),
    ("Generic Bearer Token", r"Bearer\s+[a-zA-Z0-9\-_.]{20,}", "medium"),
]

INJECTION_PATTERNS: list[tuple[str, str, str]] = [
    # SQL injection
    ("SQL Injection (f-string)",
     r"""f["'](?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER)\b[^"']*\{""", "critical"),
    ("SQL Injection (format)",
     r"""(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER)\b.*\.format\(""", "high"),
    ("SQL Injection (% formatting)",
     r"""(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER)\b.*%\s*\(""", "high"),

    # XSS
    ("XSS - innerHTML",
     r"""\.innerHTML\s*=\s*(?!["']<)""", "high"),
    ("XSS - dangerouslySetInnerHTML",
     r"""dangerouslySetInnerHTML\s*=\s*\{\s*\{""", "medium"),
    ("XSS - document.write",
     r"""document\.write\s*\(""", "medium"),

    # Command injection
    ("Command Injection - os.system",
     r"""os\.system\s*\(\s*(?:f["']|.*\+|.*\.format|.*%)""", "critical"),
    ("Command Injection - subprocess with shell",
     r"""subprocess\.(?:run|call|Popen)\s*\([^)]*shell\s*=\s*True""", "high"),
    ("Command Injection - eval",
     r"""eval\s*\(\s*(?!["'])""", "high"),
    ("Command Injection - exec",
     r"""exec\s*\(\s*(?!["'])""", "high"),

    # Path traversal
    ("Path Traversal",
     r"""(?:open|Path)\s*\([^)]*\.\.\/""", "high"),
    ("Path Traversal (user input)",
     r"""(?:open|Path)\s*\([^)]*(?:request|input|params|query)""", "medium"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file_extension(filepath: str) -> str:
    """Return lowercase file extension without the dot."""
    return Path(filepath).suffix.lstrip(".").lower()


def _run_cmd(cmd: list[str], cwd: str | None = None,
             timeout: int = 120) -> tuple[int, str, str]:
    """Run a subprocess, return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=cwd, timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "", f"Command timed out after {timeout}s"


def _which(name: str) -> bool:
    """Check if a command is available on PATH."""
    try:
        subprocess.run(
            ["which", name], capture_output=True, timeout=5,
        )
        return True
    except Exception:
        return False


def _read_file_safe(filepath: str, max_bytes: int = 2_000_000) -> str | None:
    """Read a file, returning None on error. Cap at max_bytes."""
    try:
        p = Path(filepath)
        if not p.is_file():
            return None
        if p.stat().st_size > max_bytes:
            return None  # skip huge files
        return p.read_text(errors="replace")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Gate weight configuration
# ---------------------------------------------------------------------------

GATE_WEIGHTS = {
    "syntax": 25,
    "security": 30,
    "tests": 20,
    "lint": 10,
    "diff": 10,
    "cost": 5,
}


# ---------------------------------------------------------------------------
# OutputVerifier
# ---------------------------------------------------------------------------

class OutputVerifier:
    """
    Runs all quality gates against agent output before delivery.

    Usage:
        verifier = OutputVerifier()
        result = verifier.verify_all(
            job_id="job-123",
            files_changed=["src/main.py", "src/utils.py"],
            work_dir="/path/to/repo",
        )
        if result.passed:
            print("Ship it!")
        else:
            print(result.summary)
    """

    def __init__(
        self,
        cost_file: str = os.path.join(os.environ.get("OPENCLAW_DATA_DIR", "./data"), "costs", "costs.jsonl"),
        budget_per_job: float = 5.0,
        budget_daily: float = 20.0,
        budget_monthly: float = 1000.0,
        test_timeout: int = 120,
        max_diff_lines: int = 1000,
        max_file_deletion_pct: float = 50.0,
    ):
        self.cost_file = cost_file
        self.budget_per_job = budget_per_job
        self.budget_daily = budget_daily
        self.budget_monthly = budget_monthly
        self.test_timeout = test_timeout
        self.max_diff_lines = max_diff_lines
        self.max_file_deletion_pct = max_file_deletion_pct

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def verify_all(
        self,
        job_id: str,
        files_changed: list[str],
        work_dir: str,
    ) -> VerificationResult:
        """Run every quality gate and return an aggregated result."""
        gates: list[GateResult] = []

        # 1. Syntax
        syntax_issues: list[dict] = []
        for fp in files_changed:
            full_path = os.path.join(work_dir, fp) if not os.path.isabs(fp) else fp
            r = self.verify_syntax(full_path)
            syntax_issues.extend(r.issues)
        syntax_passed = all(
            i["severity"] != "error" for i in syntax_issues
        )
        syntax_score = max(0, 100 - len([
            i for i in syntax_issues if i["severity"] == "error"
        ]) * 25)
        gates.append(GateResult(
            gate="syntax", passed=syntax_passed,
            score=syntax_score, issues=syntax_issues,
        ))

        # 2. Security
        security_issues: list[dict] = []
        for fp in files_changed:
            full_path = os.path.join(work_dir, fp) if not os.path.isabs(fp) else fp
            r = self.verify_security(full_path)
            security_issues.extend(r.issues)
        has_critical = any(i["severity"] == "critical" for i in security_issues)
        has_high = any(i["severity"] == "high" for i in security_issues)
        security_passed = not has_critical
        security_score = max(0, 100 - (
            len([i for i in security_issues if i["severity"] == "critical"]) * 40
            + len([i for i in security_issues if i["severity"] == "high"]) * 20
            + len([i for i in security_issues if i["severity"] == "medium"]) * 5
        ))
        gates.append(GateResult(
            gate="security", passed=security_passed,
            score=max(0, security_score), issues=security_issues,
        ))

        # 3. Tests
        test_result = self.verify_tests(work_dir)
        gates.append(test_result)

        # 4. Lint
        lint_issues: list[dict] = []
        for fp in files_changed:
            full_path = os.path.join(work_dir, fp) if not os.path.isabs(fp) else fp
            r = self.verify_lint(full_path)
            lint_issues.extend(r.issues)
        lint_errors = len([i for i in lint_issues if i["severity"] in ("error", "high")])
        lint_warnings = len([i for i in lint_issues if i["severity"] in ("warning", "medium")])
        lint_passed = lint_errors == 0
        lint_score = max(0, 100 - lint_errors * 15 - lint_warnings * 3)
        gates.append(GateResult(
            gate="lint", passed=lint_passed,
            score=max(0, lint_score), issues=lint_issues,
        ))

        # 5. Diff
        diff_result = self.verify_diff(work_dir)
        gates.append(diff_result)

        # 6. Cost
        cost_result = self.verify_cost(job_id)
        gates.append(cost_result)

        # Aggregate
        all_passed = all(g.passed for g in gates)
        weighted_total = sum(
            g.score * GATE_WEIGHTS.get(g.gate, 10) for g in gates
        )
        weight_sum = sum(GATE_WEIGHTS.get(g.gate, 10) for g in gates)
        overall_score = round(weighted_total / weight_sum) if weight_sum else 0

        # Recommendation
        if all_passed and overall_score >= 80:
            recommendation = "approve"
        elif has_critical or overall_score < 30:
            recommendation = "reject"
        else:
            recommendation = "fix_and_retry"

        # Summary
        failed_gates = [g.gate for g in gates if not g.passed]
        total_issues = sum(len(g.issues) for g in gates)
        if all_passed:
            summary = (
                f"All 6 gates passed. Score: {overall_score}/100. "
                f"{total_issues} minor issue(s) noted."
            )
        else:
            summary = (
                f"FAILED gates: {', '.join(failed_gates)}. "
                f"Score: {overall_score}/100. "
                f"{total_issues} issue(s) found. "
                f"Recommendation: {recommendation}."
            )

        return VerificationResult(
            passed=all_passed,
            overall_score=overall_score,
            gates=gates,
            summary=summary,
            recommendation=recommendation,
        )

    # ------------------------------------------------------------------
    # Gate 1: Syntax Check
    # ------------------------------------------------------------------

    def verify_syntax(self, filepath: str) -> GateResult:
        """Check that the file is syntactically valid."""
        issues: list[dict] = []
        ext = _file_extension(filepath)

        content = _read_file_safe(filepath)
        if content is None:
            # File doesn't exist or is too large -- skip gracefully
            issues.append({
                "severity": "warning",
                "message": f"Could not read file: {filepath}",
                "file": filepath,
                "line": 0,
            })
            return GateResult(gate="syntax", passed=True, score=80, issues=issues)

        if ext == "py":
            issues.extend(self._check_python_syntax(filepath, content))
        elif ext in ("js", "jsx", "ts", "tsx", "mjs", "cjs"):
            issues.extend(self._check_js_syntax(filepath, content))
        elif ext == "json":
            issues.extend(self._check_json_syntax(filepath, content))
        elif ext in ("html", "htm"):
            issues.extend(self._check_html_syntax(filepath, content))
        # else: unknown extension -- skip

        errors = [i for i in issues if i["severity"] == "error"]
        passed = len(errors) == 0
        score = max(0, 100 - len(errors) * 25)
        return GateResult(gate="syntax", passed=passed, score=score, issues=issues)

    def _check_python_syntax(self, filepath: str, content: str) -> list[dict]:
        issues = []
        try:
            ast.parse(content, filename=filepath)
        except SyntaxError as e:
            issues.append({
                "severity": "error",
                "message": f"Python syntax error: {e.msg}",
                "file": filepath,
                "line": e.lineno or 0,
            })
        return issues

    def _check_js_syntax(self, filepath: str, content: str) -> list[dict]:
        """
        Check JS/TS syntax via bracket/brace/paren matching.
        Also try `node --check` for .js/.mjs/.cjs files.
        """
        issues = []

        # Bracket matching (works for all JS/TS variants)
        issues.extend(self._check_bracket_matching(filepath, content))

        # Try node --check for pure JS files
        ext = _file_extension(filepath)
        if ext in ("js", "mjs", "cjs") and _which("node"):
            rc, _, stderr = _run_cmd(["node", "--check", filepath], timeout=10)
            if rc != 0 and stderr.strip():
                # Extract line number if possible
                line = 0
                m = re.search(r":(\d+)", stderr)
                if m:
                    line = int(m.group(1))
                issues.append({
                    "severity": "error",
                    "message": f"Node syntax error: {stderr.strip()[:200]}",
                    "file": filepath,
                    "line": line,
                })

        return issues

    def _check_bracket_matching(self, filepath: str, content: str) -> list[dict]:
        """Verify that brackets, braces, and parens are balanced."""
        issues = []
        stack: list[tuple[str, int]] = []
        pairs = {"(": ")", "[": "]", "{": "}"}
        closers = set(pairs.values())

        # Strip strings and comments (rough but effective)
        # Remove single-line comments
        cleaned = re.sub(r"//.*$", "", content, flags=re.MULTILINE)
        # Remove multi-line comments
        cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
        # Remove strings (double-quoted, single-quoted, template literals)
        cleaned = re.sub(r'"(?:[^"\\]|\\.)*"', '""', cleaned)
        cleaned = re.sub(r"'(?:[^'\\]|\\.)*'", "''", cleaned)
        cleaned = re.sub(r"`(?:[^`\\]|\\.)*`", "``", cleaned)

        for line_num, line in enumerate(cleaned.split("\n"), 1):
            for ch in line:
                if ch in pairs:
                    stack.append((ch, line_num))
                elif ch in closers:
                    if not stack:
                        issues.append({
                            "severity": "error",
                            "message": f"Unmatched closing '{ch}'",
                            "file": filepath,
                            "line": line_num,
                        })
                    else:
                        opener, _ = stack.pop()
                        if pairs[opener] != ch:
                            issues.append({
                                "severity": "error",
                                "message": (
                                    f"Mismatched brackets: "
                                    f"'{opener}' closed with '{ch}'"
                                ),
                                "file": filepath,
                                "line": line_num,
                            })

        for opener, line_num in stack:
            issues.append({
                "severity": "error",
                "message": f"Unclosed '{opener}'",
                "file": filepath,
                "line": line_num,
            })

        return issues

    def _check_json_syntax(self, filepath: str, content: str) -> list[dict]:
        issues = []
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            issues.append({
                "severity": "error",
                "message": f"JSON parse error: {e.msg}",
                "file": filepath,
                "line": e.lineno,
            })
        return issues

    def _check_html_syntax(self, filepath: str, content: str) -> list[dict]:
        """Basic HTML tag matching (not a full parser)."""
        issues = []
        # Find all opening and closing tags
        tag_pattern = re.compile(r"<(/?)(\w+)[^>]*?(/?)>")
        void_elements = {
            "area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr",
        }
        stack: list[tuple[str, int]] = []

        for line_num, line in enumerate(content.split("\n"), 1):
            for m in tag_pattern.finditer(line):
                is_closing = m.group(1) == "/"
                tag_name = m.group(2).lower()
                is_self_closing = m.group(3) == "/"

                if tag_name in void_elements or is_self_closing:
                    continue

                if is_closing:
                    if stack and stack[-1][0] == tag_name:
                        stack.pop()
                    elif stack:
                        issues.append({
                            "severity": "warning",
                            "message": (
                                f"Mismatched HTML tag: expected </{stack[-1][0]}>, "
                                f"got </{tag_name}>"
                            ),
                            "file": filepath,
                            "line": line_num,
                        })
                    else:
                        issues.append({
                            "severity": "warning",
                            "message": f"Unexpected closing tag </{tag_name}>",
                            "file": filepath,
                            "line": line_num,
                        })
                else:
                    stack.append((tag_name, line_num))

        for tag_name, line_num in stack:
            issues.append({
                "severity": "warning",
                "message": f"Unclosed HTML tag <{tag_name}>",
                "file": filepath,
                "line": line_num,
            })

        return issues

    # ------------------------------------------------------------------
    # Gate 2: Security Scan
    # ------------------------------------------------------------------

    def verify_security(self, filepath: str) -> GateResult:
        """Scan file for hardcoded secrets, injection patterns, etc."""
        issues: list[dict] = []
        content = _read_file_safe(filepath)
        if content is None:
            return GateResult(gate="security", passed=True, score=100, issues=[])

        ext = _file_extension(filepath)

        # Skip binary / non-text files
        if ext in ("png", "jpg", "jpeg", "gif", "ico", "woff", "woff2",
                    "ttf", "eot", "svg", "pdf", "zip", "tar", "gz"):
            return GateResult(gate="security", passed=True, score=100, issues=[])

        lines = content.split("\n")

        # Check secret patterns
        for name, pattern, severity in SECRET_PATTERNS:
            regex = re.compile(pattern, re.IGNORECASE)
            for line_num, line in enumerate(lines, 1):
                # Skip comments that explain patterns (like this module itself)
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("//"):
                    # Only flag comments if they contain an actual key format
                    # that looks real (not a regex pattern or documentation)
                    if re.search(r"r[\"']|regex|pattern|example|test|fake|dummy",
                                 line, re.IGNORECASE):
                        continue
                if regex.search(line):
                    # Skip test/mock/example files
                    lower_path = filepath.lower()
                    if any(kw in lower_path for kw in
                           ("test", "mock", "fixture", "example", "spec")):
                        severity_adj = "low"
                    else:
                        severity_adj = severity
                    issues.append({
                        "severity": severity_adj,
                        "message": f"Potential {name} detected",
                        "file": filepath,
                        "line": line_num,
                    })

        # Check injection patterns
        for name, pattern, severity in INJECTION_PATTERNS:
            regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
            for line_num, line in enumerate(lines, 1):
                if regex.search(line):
                    issues.append({
                        "severity": severity,
                        "message": f"Potential {name}",
                        "file": filepath,
                        "line": line_num,
                    })

        has_critical = any(i["severity"] == "critical" for i in issues)
        score = max(0, 100 - (
            len([i for i in issues if i["severity"] == "critical"]) * 40
            + len([i for i in issues if i["severity"] == "high"]) * 20
            + len([i for i in issues if i["severity"] == "medium"]) * 5
        ))
        return GateResult(
            gate="security",
            passed=not has_critical,
            score=max(0, score),
            issues=issues,
        )

    # ------------------------------------------------------------------
    # Gate 3: Test Runner
    # ------------------------------------------------------------------

    def verify_tests(self, work_dir: str) -> GateResult:
        """Detect and run tests if a test framework is available."""
        issues: list[dict] = []
        framework, cmd = self._detect_test_framework(work_dir)

        if framework is None:
            issues.append({
                "severity": "info",
                "message": "No test framework detected -- skipping test gate",
                "file": work_dir,
                "line": 0,
            })
            return GateResult(gate="tests", passed=True, score=70, issues=issues)

        rc, stdout, stderr = _run_cmd(cmd, cwd=work_dir, timeout=self.test_timeout)
        output = stdout + "\n" + stderr

        parsed = self._parse_test_output(framework, output, rc)
        total = parsed["passed"] + parsed["failed"] + parsed["skipped"]

        if rc == -2:
            issues.append({
                "severity": "high",
                "message": f"Tests timed out after {self.test_timeout}s",
                "file": work_dir,
                "line": 0,
            })
            return GateResult(gate="tests", passed=False, score=20, issues=issues)

        if parsed["failed"] > 0:
            issues.append({
                "severity": "error",
                "message": (
                    f"{parsed['failed']}/{total} tests failed "
                    f"({framework})"
                ),
                "file": work_dir,
                "line": 0,
            })
            # Include first few failure lines
            fail_lines = [
                ln for ln in output.split("\n")
                if re.search(r"FAIL|ERROR|AssertionError|expected|assert", ln,
                             re.IGNORECASE)
            ][:5]
            for fl in fail_lines:
                issues.append({
                    "severity": "error",
                    "message": fl.strip()[:200],
                    "file": work_dir,
                    "line": 0,
                })
        else:
            issues.append({
                "severity": "info",
                "message": (
                    f"{parsed['passed']}/{total} tests passed, "
                    f"{parsed['skipped']} skipped ({framework})"
                ),
                "file": work_dir,
                "line": 0,
            })

        passed = parsed["failed"] == 0 and rc in (0, -1)
        score = 100 if passed else max(0, round(
            100 * parsed["passed"] / max(total, 1)
        ))
        return GateResult(gate="tests", passed=passed, score=score, issues=issues)

    def _detect_test_framework(
        self, work_dir: str,
    ) -> tuple[str | None, list[str]]:
        """Detect which test framework is available."""
        wd = Path(work_dir)

        # Python: pytest
        if (wd / "pytest.ini").exists() or (wd / "pyproject.toml").exists() or \
           (wd / "setup.cfg").exists() or list(wd.glob("test_*.py")) or \
           list(wd.glob("tests/")):
            if _which("pytest"):
                return "pytest", ["pytest", "--tb=short", "-q", "--no-header"]
            elif _which("python3"):
                return "pytest", ["python3", "-m", "pytest", "--tb=short",
                                  "-q", "--no-header"]

        # JS: check package.json for test script
        pkg_json = wd / "package.json"
        if pkg_json.exists():
            try:
                pkg = json.loads(pkg_json.read_text())
                scripts = pkg.get("scripts", {})
                test_script = scripts.get("test", "")

                if "vitest" in test_script:
                    return "vitest", ["npx", "vitest", "run", "--reporter=verbose"]
                if "jest" in test_script:
                    return "jest", ["npx", "jest", "--verbose", "--no-coverage"]
                if "mocha" in test_script:
                    return "mocha", ["npx", "mocha", "--reporter", "spec"]
                if test_script and "no test" not in test_script:
                    return "npm-test", ["npm", "test", "--", "--no-coverage"]
            except (json.JSONDecodeError, KeyError):
                pass

        return None, []

    def _parse_test_output(
        self, framework: str, output: str, rc: int,
    ) -> dict:
        """Extract pass/fail/skip counts from test output."""
        result = {"passed": 0, "failed": 0, "skipped": 0}

        if framework == "pytest":
            # "5 passed, 2 failed, 1 skipped"
            m = re.search(r"(\d+)\s+passed", output)
            if m:
                result["passed"] = int(m.group(1))
            m = re.search(r"(\d+)\s+failed", output)
            if m:
                result["failed"] = int(m.group(1))
            m = re.search(r"(\d+)\s+skipped", output)
            if m:
                result["skipped"] = int(m.group(1))
            m = re.search(r"(\d+)\s+error", output)
            if m:
                result["failed"] += int(m.group(1))

        elif framework in ("jest", "vitest"):
            # "Tests: 3 failed, 10 passed, 13 total"
            m = re.search(r"Tests:\s*(?:(\d+)\s+failed,?\s*)?(?:(\d+)\s+skipped,?\s*)?(?:(\d+)\s+passed)", output)
            if m:
                result["failed"] = int(m.group(1) or 0)
                result["skipped"] = int(m.group(2) or 0)
                result["passed"] = int(m.group(3) or 0)

        elif framework == "mocha":
            m = re.search(r"(\d+)\s+passing", output)
            if m:
                result["passed"] = int(m.group(1))
            m = re.search(r"(\d+)\s+failing", output)
            if m:
                result["failed"] = int(m.group(1))
            m = re.search(r"(\d+)\s+pending", output)
            if m:
                result["skipped"] = int(m.group(1))

        else:
            # npm-test fallback: infer from exit code
            if rc == 0:
                result["passed"] = 1
            else:
                result["failed"] = 1

        return result

    # ------------------------------------------------------------------
    # Gate 4: Lint Check
    # ------------------------------------------------------------------

    def verify_lint(self, filepath: str) -> GateResult:
        """Run available linters and check for debug statements."""
        issues: list[dict] = []
        ext = _file_extension(filepath)
        content = _read_file_safe(filepath)

        if content is None:
            return GateResult(gate="lint", passed=True, score=90, issues=[])

        # Run external linter if available
        if ext == "py":
            issues.extend(self._lint_python(filepath))
        elif ext in ("js", "jsx", "ts", "tsx"):
            issues.extend(self._lint_js(filepath))

        # Generic checks on all text files
        issues.extend(self._check_debug_statements(filepath, content, ext))
        issues.extend(self._check_todo_fixme(filepath, content))

        errors = len([i for i in issues if i["severity"] in ("error", "high")])
        warnings = len([i for i in issues if i["severity"] in ("warning", "medium")])
        passed = errors == 0
        score = max(0, 100 - errors * 15 - warnings * 3)
        return GateResult(gate="lint", passed=passed, score=max(0, score), issues=issues)

    def _lint_python(self, filepath: str) -> list[dict]:
        """Run ruff or flake8 on a Python file."""
        issues = []

        if _which("ruff"):
            rc, stdout, _ = _run_cmd(
                ["ruff", "check", "--output-format=json", filepath], timeout=30,
            )
            if stdout.strip():
                try:
                    findings = json.loads(stdout)
                    for f in findings[:20]:  # cap at 20
                        issues.append({
                            "severity": "warning" if f.get("fix") else "error",
                            "message": f"{f.get('code', '?')}: {f.get('message', '?')}",
                            "file": filepath,
                            "line": f.get("location", {}).get("row", 0),
                        })
                except json.JSONDecodeError:
                    pass  # non-JSON output, ignore
        elif _which("flake8"):
            rc, stdout, _ = _run_cmd(
                ["flake8", "--max-line-length=120", "--format=json", filepath],
                timeout=30,
            )
            if stdout.strip():
                try:
                    findings = json.loads(stdout)
                    for fpath, errs in findings.items():
                        for e in errs[:20]:
                            issues.append({
                                "severity": "warning",
                                "message": f"{e.get('code', '?')}: {e.get('text', '?')}",
                                "file": filepath,
                                "line": e.get("line_number", 0),
                            })
                except json.JSONDecodeError:
                    pass

        return issues

    def _lint_js(self, filepath: str) -> list[dict]:
        """Run eslint on a JS/TS file if available."""
        issues = []
        if _which("npx"):
            rc, stdout, _ = _run_cmd(
                ["npx", "eslint", "--format=json", "--no-error-on-unmatched-pattern",
                 filepath],
                timeout=30,
            )
            if stdout.strip():
                try:
                    results = json.loads(stdout)
                    for r in results:
                        for msg in r.get("messages", [])[:20]:
                            severity = "error" if msg.get("severity", 0) == 2 else "warning"
                            issues.append({
                                "severity": severity,
                                "message": f"{msg.get('ruleId', '?')}: {msg.get('message', '?')}",
                                "file": filepath,
                                "line": msg.get("line", 0),
                            })
                except json.JSONDecodeError:
                    pass

        return issues

    def _check_debug_statements(
        self, filepath: str, content: str, ext: str,
    ) -> list[dict]:
        """Detect leftover debug/logging statements."""
        issues = []
        lines = content.split("\n")

        patterns: list[tuple[str, str]] = []
        if ext == "py":
            patterns = [
                (r"^\s*print\s*\(", "Leftover print() statement"),
                (r"^\s*breakpoint\s*\(", "Leftover breakpoint()"),
                (r"^\s*pdb\.set_trace\s*\(", "Leftover pdb debugger"),
                (r"^\s*import\s+pdb", "Leftover pdb import"),
                (r"^\s*import\s+ipdb", "Leftover ipdb import"),
            ]
        elif ext in ("js", "jsx", "ts", "tsx"):
            patterns = [
                (r"^\s*console\.log\s*\(", "Leftover console.log()"),
                (r"^\s*console\.debug\s*\(", "Leftover console.debug()"),
                (r"^\s*debugger\s*;?\s*$", "Leftover debugger statement"),
                (r"^\s*alert\s*\(", "Leftover alert()"),
            ]

        for line_num, line in enumerate(lines, 1):
            for pattern, message in patterns:
                if re.search(pattern, line):
                    issues.append({
                        "severity": "warning",
                        "message": message,
                        "file": filepath,
                        "line": line_num,
                    })

        return issues

    def _check_todo_fixme(self, filepath: str, content: str) -> list[dict]:
        """Flag TODO, FIXME, HACK, XXX comments."""
        issues = []
        todo_pattern = re.compile(
            r"\b(TODO|FIXME|HACK|XXX|TEMP|TEMPORARY)\b", re.IGNORECASE,
        )
        lines = content.split("\n")
        for line_num, line in enumerate(lines, 1):
            m = todo_pattern.search(line)
            if m:
                tag = m.group(1).upper()
                severity = "warning" if tag in ("HACK", "FIXME", "XXX") else "info"
                issues.append({
                    "severity": severity,
                    "message": f"{tag} comment: {line.strip()[:120]}",
                    "file": filepath,
                    "line": line_num,
                })
        return issues

    # ------------------------------------------------------------------
    # Gate 5: Diff Validator
    # ------------------------------------------------------------------

    def verify_diff(self, work_dir: str) -> GateResult:
        """Validate the git diff for sanity."""
        issues: list[dict] = []

        # Check if we're in a git repo
        rc, _, _ = _run_cmd(["git", "rev-parse", "--git-dir"], cwd=work_dir)
        if rc != 0:
            issues.append({
                "severity": "info",
                "message": "Not a git repository -- skipping diff gate",
                "file": work_dir,
                "line": 0,
            })
            return GateResult(gate="diff", passed=True, score=70, issues=issues)

        # Get diff stats
        rc, stdout, _ = _run_cmd(
            ["git", "diff", "--stat", "--cached", "HEAD"], cwd=work_dir,
        )
        if rc != 0:
            # Maybe no commits yet, try without HEAD
            rc, stdout, _ = _run_cmd(
                ["git", "diff", "--stat"], cwd=work_dir,
            )

        # Also check unstaged
        rc2, stdout2, _ = _run_cmd(
            ["git", "diff", "--stat"], cwd=work_dir,
        )
        combined_stat = stdout + "\n" + stdout2

        # Check for large diffs
        total_lines = self._count_diff_lines(work_dir)
        if total_lines > self.max_diff_lines:
            issues.append({
                "severity": "warning",
                "message": (
                    f"Large diff: {total_lines} lines changed "
                    f"(threshold: {self.max_diff_lines})"
                ),
                "file": work_dir,
                "line": 0,
            })

        # Check for accidental large deletions
        issues.extend(self._check_large_deletions(work_dir))

        # Check for binary files
        issues.extend(self._check_binary_files(work_dir))

        # Check for secrets in diff
        issues.extend(self._check_secrets_in_diff(work_dir))

        has_high = any(i["severity"] in ("critical", "high") for i in issues)
        warnings = len([i for i in issues if i["severity"] == "warning"])
        passed = not has_high
        score = max(0, 100 - (
            len([i for i in issues if i["severity"] in ("critical", "high")]) * 30
            + warnings * 10
        ))
        return GateResult(
            gate="diff", passed=passed, score=max(0, score), issues=issues,
        )

    def _count_diff_lines(self, work_dir: str) -> int:
        """Count total lines added + removed in the diff."""
        rc, stdout, _ = _run_cmd(
            ["git", "diff", "--shortstat"], cwd=work_dir,
        )
        rc2, stdout2, _ = _run_cmd(
            ["git", "diff", "--cached", "--shortstat"], cwd=work_dir,
        )
        total = 0
        for s in (stdout, stdout2):
            m = re.search(r"(\d+)\s+insertion", s)
            if m:
                total += int(m.group(1))
            m = re.search(r"(\d+)\s+deletion", s)
            if m:
                total += int(m.group(1))
        return total

    def _check_large_deletions(self, work_dir: str) -> list[dict]:
        """Detect files where >50% of content was removed."""
        issues = []
        rc, stdout, _ = _run_cmd(
            ["git", "diff", "--numstat"], cwd=work_dir,
        )
        rc2, stdout2, _ = _run_cmd(
            ["git", "diff", "--cached", "--numstat"], cwd=work_dir,
        )
        for line in (stdout + "\n" + stdout2).strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            added, removed, fname = parts[0], parts[1], parts[2]
            if added == "-" or removed == "-":
                continue  # binary
            try:
                added_n = int(added)
                removed_n = int(removed)
            except ValueError:
                continue
            if removed_n > 0 and added_n == 0:
                # Entire file deleted
                issues.append({
                    "severity": "warning",
                    "message": f"File entirely deleted: {fname} (-{removed_n} lines)",
                    "file": fname,
                    "line": 0,
                })
            elif removed_n > 50 and added_n > 0:
                total_original = added_n + removed_n  # rough estimate
                pct_removed = (removed_n / total_original) * 100
                if pct_removed > self.max_file_deletion_pct:
                    issues.append({
                        "severity": "warning",
                        "message": (
                            f"Large deletion in {fname}: "
                            f"{removed_n} lines removed ({pct_removed:.0f}% of changes)"
                        ),
                        "file": fname,
                        "line": 0,
                    })
        return issues

    def _check_binary_files(self, work_dir: str) -> list[dict]:
        """Check for binary files in the diff."""
        issues = []
        rc, stdout, _ = _run_cmd(
            ["git", "diff", "--numstat", "--cached"], cwd=work_dir,
        )
        rc2, stdout2, _ = _run_cmd(
            ["git", "diff", "--numstat"], cwd=work_dir,
        )
        for line in (stdout + "\n" + stdout2).strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 3 and parts[0] == "-" and parts[1] == "-":
                fname = parts[2]
                # Some binary files are expected
                expected_binary = {
                    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff",
                    ".woff2", ".ttf", ".eot", ".pdf",
                }
                ext = Path(fname).suffix.lower()
                if ext not in expected_binary:
                    issues.append({
                        "severity": "warning",
                        "message": f"Binary file staged: {fname}",
                        "file": fname,
                        "line": 0,
                    })
        return issues

    def _check_secrets_in_diff(self, work_dir: str) -> list[dict]:
        """Scan the actual diff content for secrets."""
        issues = []
        rc, stdout, _ = _run_cmd(
            ["git", "diff", "--cached", "-U0"], cwd=work_dir,
        )
        rc2, stdout2, _ = _run_cmd(
            ["git", "diff", "-U0"], cwd=work_dir,
        )
        diff_content = stdout + "\n" + stdout2

        # Only check added lines (lines starting with +)
        added_lines = [
            ln[1:] for ln in diff_content.split("\n")
            if ln.startswith("+") and not ln.startswith("+++")
        ]

        for name, pattern, severity in SECRET_PATTERNS:
            regex = re.compile(pattern, re.IGNORECASE)
            for line in added_lines:
                if regex.search(line):
                    issues.append({
                        "severity": severity,
                        "message": f"Secret in diff: potential {name}",
                        "file": work_dir,
                        "line": 0,
                    })
                    break  # one finding per pattern is enough

        return issues

    # ------------------------------------------------------------------
    # Gate 6: Cost Gate
    # ------------------------------------------------------------------

    def verify_cost(self, job_id: str) -> GateResult:
        """Check job cost against budget limits."""
        issues: list[dict] = []
        job_cost = 0.0
        daily_cost = 0.0
        monthly_cost = 0.0

        cost_path = Path(self.cost_file)
        if not cost_path.exists():
            issues.append({
                "severity": "info",
                "message": "No cost log found -- skipping cost gate",
                "file": self.cost_file,
                "line": 0,
            })
            return GateResult(gate="cost", passed=True, score=80, issues=issues)

        # Parse JSONL cost log
        now = time.time()
        today_start = now - (now % 86400)  # midnight UTC approx
        month_start = now - (30 * 86400)   # last 30 days

        try:
            for line in cost_path.read_text().strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                cost = entry.get("cost_usd", entry.get("cost", 0.0))
                ts = entry.get("timestamp", entry.get("ts", 0))
                eid = entry.get("job_id", entry.get("id", ""))

                if isinstance(ts, str):
                    # Try ISO format
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        ts = dt.timestamp()
                    except (ValueError, TypeError):
                        ts = 0

                if eid == job_id:
                    job_cost += float(cost)
                if ts >= today_start:
                    daily_cost += float(cost)
                if ts >= month_start:
                    monthly_cost += float(cost)
        except Exception as e:
            issues.append({
                "severity": "warning",
                "message": f"Error reading cost log: {e}",
                "file": self.cost_file,
                "line": 0,
            })
            return GateResult(gate="cost", passed=True, score=70, issues=issues)

        # Check per-job budget
        if job_cost > self.budget_per_job:
            issues.append({
                "severity": "high",
                "message": (
                    f"Job {job_id} cost ${job_cost:.2f} exceeds "
                    f"per-job budget ${self.budget_per_job:.2f}"
                ),
                "file": self.cost_file,
                "line": 0,
            })
        elif job_cost > self.budget_per_job * 0.8:
            issues.append({
                "severity": "warning",
                "message": (
                    f"Job {job_id} cost ${job_cost:.2f} is at "
                    f"{job_cost / self.budget_per_job * 100:.0f}% of budget"
                ),
                "file": self.cost_file,
                "line": 0,
            })

        # Check daily budget
        if daily_cost > self.budget_daily:
            issues.append({
                "severity": "high",
                "message": (
                    f"Daily cost ${daily_cost:.2f} exceeds "
                    f"daily budget ${self.budget_daily:.2f}"
                ),
                "file": self.cost_file,
                "line": 0,
            })
        elif daily_cost > self.budget_daily * 0.8:
            issues.append({
                "severity": "warning",
                "message": (
                    f"Daily cost ${daily_cost:.2f} is at "
                    f"{daily_cost / self.budget_daily * 100:.0f}% of budget"
                ),
                "file": self.cost_file,
                "line": 0,
            })

        # Check monthly budget
        if monthly_cost > self.budget_monthly:
            issues.append({
                "severity": "high",
                "message": (
                    f"Monthly cost ${monthly_cost:.2f} exceeds "
                    f"monthly budget ${self.budget_monthly:.2f}"
                ),
                "file": self.cost_file,
                "line": 0,
            })
        elif monthly_cost > self.budget_monthly * 0.8:
            issues.append({
                "severity": "warning",
                "message": (
                    f"Monthly cost ${monthly_cost:.2f} is at "
                    f"{monthly_cost / self.budget_monthly * 100:.0f}% of budget"
                ),
                "file": self.cost_file,
                "line": 0,
            })

        has_high = any(i["severity"] in ("critical", "high") for i in issues)
        has_warning = any(i["severity"] == "warning" for i in issues)
        passed = not has_high
        if has_high:
            score = 20
        elif has_warning:
            score = 60
        else:
            score = 100

        return GateResult(gate="cost", passed=passed, score=score, issues=issues)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """Run the verifier from the command line."""
    import argparse

    parser = argparse.ArgumentParser(
        description="OpenClaw Output Verifier - Quality gate system",
    )
    parser.add_argument(
        "--job-id", default="cli-manual",
        help="Job ID for cost tracking (default: cli-manual)",
    )
    parser.add_argument(
        "--work-dir", default=".",
        help="Working directory / repo root (default: current dir)",
    )
    parser.add_argument(
        "files", nargs="*",
        help="Files to verify (default: all staged + modified files)",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--budget-job", type=float, default=5.0,
        help="Per-job budget in USD (default: 5.0)",
    )
    parser.add_argument(
        "--budget-daily", type=float, default=20.0,
        help="Daily budget in USD (default: 20.0)",
    )
    parser.add_argument(
        "--budget-monthly", type=float, default=1000.0,
        help="Monthly budget in USD (default: 1000.0)",
    )

    args = parser.parse_args()
    work_dir = os.path.abspath(args.work_dir)

    # Auto-detect files if none given
    files = args.files
    if not files:
        # Try to get staged + modified files from git
        rc, stdout, _ = _run_cmd(
            ["git", "diff", "--name-only", "HEAD"], cwd=work_dir,
        )
        rc2, stdout2, _ = _run_cmd(
            ["git", "diff", "--cached", "--name-only"], cwd=work_dir,
        )
        files = list(set(
            f.strip() for f in (stdout + "\n" + stdout2).split("\n")
            if f.strip()
        ))
        if not files:
            print("No files to verify. Pass files as arguments or stage changes.")
            sys.exit(0)

    verifier = OutputVerifier(
        budget_per_job=args.budget_job,
        budget_daily=args.budget_daily,
        budget_monthly=args.budget_monthly,
    )
    result = verifier.verify_all(
        job_id=args.job_id,
        files_changed=files,
        work_dir=work_dir,
    )

    if args.json_output:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        # Human-readable output
        print("=" * 60)
        print("  OpenClaw Output Verifier")
        print("=" * 60)
        print()
        print(f"  Overall: {'PASS' if result.passed else 'FAIL'}  "
              f"Score: {result.overall_score}/100  "
              f"Recommendation: {result.recommendation}")
        print()
        for g in result.gates:
            status = "PASS" if g.passed else "FAIL"
            icon = "[+]" if g.passed else "[-]"
            print(f"  {icon} {g.gate:<12} {status:<6} {g.score:>3}/100  "
                  f"({len(g.issues)} issue{'s' if len(g.issues) != 1 else ''})")
            for issue in g.issues:
                sev = issue["severity"]
                if sev in ("critical", "error"):
                    prefix = "  !!!"
                elif sev in ("high",):
                    prefix = "  !!"
                elif sev in ("warning", "medium"):
                    prefix = "  !"
                else:
                    prefix = "  -"
                line_info = f":{issue['line']}" if issue.get("line") else ""
                file_info = issue.get("file", "")
                if file_info:
                    file_info = os.path.basename(file_info) + line_info
                print(f"      {prefix} [{sev}] {issue['message'][:120]}"
                      f"  {file_info}")
        print()
        print(f"  Summary: {result.summary}")
        print("=" * 60)

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
