"""
Phase-Level Quality Scoring — Process Reward Model (Lite)

Scores EVERY pipeline phase individually, not just the final result.
This implements the "Per-Step Scoring" pattern from big-tech agent research.

Each phase gets a 0.0-1.0 quality score based on phase-specific criteria.
Scores are stored in result["phases"][phase]["quality_score"] and logged
for trend analysis.

Scoring is deterministic (no LLM calls) for speed. The eval harness uses
LLM-as-Judge for deeper grading — this is the fast, per-job version.
"""

import json
import logging
import re
from typing import Any

logger = logging.getLogger("phase_scoring")


# ---------------------------------------------------------------------------
# Phase-specific scoring functions
# ---------------------------------------------------------------------------

def score_research(phase_result: dict, research_text: Any) -> dict:
    """Score research phase quality.

    Criteria:
    - Has content (not empty/skipped): +0.3
    - Sufficient length (>200 chars): +0.2
    - Contains structured info (bullet points, headers): +0.2
    - Contains URLs or references: +0.15
    - Contains code blocks or technical detail: +0.15
    """
    score = 0.0
    details = {}

    text = str(research_text) if research_text else ""
    status = phase_result.get("status", "")

    if status == "skipped":
        return {"score": 0.0, "details": {"reason": "skipped"}}

    # Has content
    if text and len(text) > 20:
        score += 0.3
        details["has_content"] = True
    else:
        details["has_content"] = False

    # Sufficient length
    if len(text) > 200:
        score += 0.2
        details["sufficient_length"] = True
    elif len(text) > 50:
        score += 0.1
        details["sufficient_length"] = "partial"

    # Structured info (bullets, headers, numbered lists)
    structured_patterns = [r"^[-*•]\s", r"^#{1,3}\s", r"^\d+\.\s"]
    has_structure = any(
        re.search(p, text, re.MULTILINE) for p in structured_patterns
    )
    if has_structure:
        score += 0.2
        details["structured"] = True

    # References (URLs, file paths)
    has_refs = bool(re.search(r"https?://|/\w+/\w+\.\w+", text))
    if has_refs:
        score += 0.15
        details["has_references"] = True

    # Technical detail (code blocks, function names, technical terms)
    has_technical = bool(re.search(r"```|def |class |function |import |const |let ", text))
    if has_technical:
        score += 0.15
        details["has_technical"] = True

    return {"score": min(score, 1.0), "details": details}


def score_plan(phase_result: dict, plan: Any) -> dict:
    """Score plan phase quality.

    Criteria:
    - Has steps: +0.3
    - Steps have descriptions: +0.2
    - Steps have tool hints: +0.2
    - Reasonable step count (2-8): +0.15
    - Steps are ordered logically (read before edit): +0.15
    """
    score = 0.0
    details = {}

    if phase_result.get("status") == "skipped":
        return {"score": 0.0, "details": {"reason": "skipped"}}

    steps = []
    if hasattr(plan, "steps"):
        steps = plan.steps
    elif isinstance(phase_result, dict):
        step_count = phase_result.get("steps", 0)
        if step_count > 0:
            score += 0.3
            details["has_steps"] = True
            # Can't evaluate further without actual plan object
            score += 0.2  # assume descriptions exist
            details["step_count"] = step_count
            if 2 <= step_count <= 8:
                score += 0.15
                details["reasonable_count"] = True
            return {"score": min(score, 1.0), "details": details}

    if not steps:
        return {"score": 0.0, "details": {"reason": "no_steps"}}

    # Has steps
    score += 0.3
    details["has_steps"] = True
    details["step_count"] = len(steps)

    # Steps have descriptions
    described = sum(1 for s in steps if getattr(s, "description", ""))
    if described == len(steps):
        score += 0.2
        details["all_described"] = True
    elif described > 0:
        score += 0.1
        details["all_described"] = False

    # Steps have tool hints
    hinted = sum(1 for s in steps if getattr(s, "tool_hints", []))
    if hinted > 0:
        score += 0.2
        details["has_tool_hints"] = True

    # Reasonable count
    if 2 <= len(steps) <= 8:
        score += 0.15
        details["reasonable_count"] = True
    elif len(steps) == 1:
        score += 0.05  # too few

    # Logical ordering (read/research before edit/write)
    read_first = _check_read_before_edit(steps)
    if read_first is not None:
        if read_first:
            score += 0.15
            details["logical_order"] = True
        else:
            details["logical_order"] = False

    return {"score": min(score, 1.0), "details": details}


def score_execute(phase_result: dict, exec_results: list) -> dict:
    """Score execute phase quality.

    Criteria:
    - Some steps completed: +0.3
    - All steps completed: +0.2
    - No failed steps: +0.2
    - Produced output/artifacts: +0.15
    - Low retry count: +0.15
    """
    score = 0.0
    details = {}

    if phase_result.get("status") == "skipped":
        return {"score": 0.0, "details": {"reason": "skipped"}}

    if not exec_results:
        return {"score": 0.0, "details": {"reason": "no_results"}}

    steps_done = phase_result.get("steps_done", 0)
    steps_failed = phase_result.get("steps_failed", 0)
    total = steps_done + steps_failed

    # Some steps completed
    if steps_done > 0:
        score += 0.3
        details["steps_done"] = steps_done

    # All steps completed
    if total > 0 and steps_failed == 0:
        score += 0.2
        details["all_passed"] = True
    elif total > 0:
        # Partial credit based on success ratio
        ratio = steps_done / total
        score += 0.2 * ratio
        details["success_ratio"] = round(ratio, 2)

    # No failed steps
    if steps_failed == 0:
        score += 0.2
        details["no_failures"] = True
    else:
        details["failures"] = steps_failed

    # Produced output
    has_output = any(
        r.get("output") or r.get("text") or r.get("result")
        for r in exec_results if isinstance(r, dict)
    )
    if has_output:
        score += 0.15
        details["has_output"] = True

    # Low retry count (check exec results for attempt counts)
    total_attempts = sum(
        r.get("attempts", 1) for r in exec_results if isinstance(r, dict)
    )
    if total > 0 and total_attempts <= total * 1.5:
        score += 0.15
        details["low_retries"] = True

    return {"score": min(score, 1.0), "details": details}


def score_code_review(phase_result: dict) -> dict:
    """Score code review phase quality.

    Criteria:
    - Review completed (not error): +0.3
    - Has review content: +0.2
    - Passed review: +0.2
    - Multiple reviewers: +0.15
    - Actionable feedback: +0.15
    """
    score = 0.0
    details = {}

    if not phase_result or phase_result.get("error"):
        return {"score": 0.0, "details": {"reason": "error_or_missing"}}

    # Review completed
    if "passed" in phase_result:
        score += 0.3
        details["completed"] = True

    # Has content
    summary = phase_result.get("summary", "")
    if summary and len(str(summary)) > 20:
        score += 0.2
        details["has_content"] = True

    # Passed
    if phase_result.get("passed", False):
        score += 0.2
        details["passed"] = True

    # Multiple reviewers
    reviews = phase_result.get("reviews", [])
    if len(reviews) >= 2:
        score += 0.15
        details["multi_reviewer"] = True
    elif len(reviews) == 1:
        score += 0.07

    # Actionable feedback (has specific issues or all-clear)
    issues = phase_result.get("issues_found", 0)
    if issues > 0 or phase_result.get("passed"):
        score += 0.15
        details["actionable"] = True

    return {"score": min(score, 1.0), "details": details}


def score_verify(phase_result: dict) -> dict:
    """Score verify phase quality.

    Criteria:
    - Verification ran: +0.3
    - Has pass/fail determination: +0.2
    - Passed verification: +0.2
    - Checked multiple aspects: +0.15
    - Partial success (successful_steps present): +0.15
    - Error context provided (failed_step_context present): +0.10
    - Has evidence (test output, screenshots): +0.15
    """
    score = 0.0
    details = {}

    if not phase_result or phase_result.get("status") == "skipped":
        return {"score": 0.0, "details": {"reason": "skipped"}}

    # Ran
    if phase_result.get("status") or phase_result.get("verified") is not None:
        score += 0.3
        details["ran"] = True

    # Has determination
    has_verdict = ("verified" in phase_result or "passed" in phase_result
                   or "status" in phase_result)
    if has_verdict:
        score += 0.2
        details["has_verdict"] = True

    # Passed
    verified = phase_result.get("verified", phase_result.get("passed", False))
    if verified or (phase_result.get("successful_steps") and not verified):
        score += 0.2
        details["passed"] = True

    # Partial success
    if phase_result.get("successful_steps"):
        score += 0.15
        details["partial_success"] = True

    # Error context provided
    if phase_result.get("failed_step_context"):
        score += 0.10
        details["error_context_provided"] = True

    # Checked multiple aspects
    checks = phase_result.get("checks", phase_result.get("aspects_checked", 0))
    if isinstance(checks, (int, float)) and checks >= 2:
        score += 0.15
        details["multi_check"] = True
    elif isinstance(checks, list) and len(checks) >= 2:
        score += 0.15
        details["multi_check"] = True

    # Has evidence
    evidence_keys = ["test_output", "screenshot", "logs", "output", "evidence"]
    has_evidence = any(phase_result.get(k) for k in evidence_keys)
    if has_evidence:
        score += 0.15
        details["has_evidence"] = True

    return {"score": min(score, 1.0), "details": details}


def score_deliver(phase_result: dict) -> dict:
    """Score deliver phase quality.

    Criteria:
    - Delivery attempted: +0.3
    - Has summary: +0.2
    - Delivered successfully: +0.2
    - Has artifacts (commit, PR, deploy URL): +0.15
    - Has actionable next steps: +0.15
    """
    score = 0.0
    details = {}

    if not phase_result:
        return {"score": 0.0, "details": {"reason": "missing"}}

    # Attempted
    if phase_result.get("delivered") is not None or phase_result.get("summary"):
        score += 0.3
        details["attempted"] = True

    # Has summary
    summary = phase_result.get("summary", "")
    if summary and len(str(summary)) > 20:
        score += 0.2
        details["has_summary"] = True

    # Delivered
    if phase_result.get("delivered", False):
        score += 0.2
        details["delivered"] = True

    # Artifacts
    artifacts = ["commit_hash", "pr_url", "vercel_deploy", "deploy_url", "branch"]
    has_artifacts = any(phase_result.get(k) for k in artifacts)
    if has_artifacts:
        score += 0.15
        details["has_artifacts"] = True

    # Next steps
    next_steps = phase_result.get("next_steps", "")
    if next_steps and len(str(next_steps)) > 10:
        score += 0.15
        details["has_next_steps"] = True

    return {"score": min(score, 1.0), "details": details}


# ---------------------------------------------------------------------------
# Schema validation — validate phase outputs before passing to next phase
# ---------------------------------------------------------------------------

PHASE_SCHEMAS = {
    "research": {
        "required_type": str,
        "min_length": 10,
        "description": "Research text (string with findings)",
    },
    "plan": {
        "required_attrs": ["steps"],
        "min_steps": 1,
        "description": "ExecutionPlan with steps list",
    },
    "execute": {
        "required_type": list,
        "min_length": 1,
        "description": "List of step execution results",
    },
    "verify": {
        "required_type": dict,
        "required_keys": [],  # flexible — at least be a dict
        "description": "Verification result dict",
    },
    "deliver": {
        "required_type": dict,
        "required_keys": [],  # flexible
        "description": "Delivery result dict",
    },
}


def validate_phase_output(phase_name: str, output: Any) -> dict:
    """Validate phase output against expected schema.

    Returns:
        {"valid": bool, "errors": list[str], "warnings": list[str]}
    """
    schema = PHASE_SCHEMAS.get(phase_name)
    if not schema:
        return {"valid": True, "errors": [], "warnings": ["No schema defined"]}

    errors = []
    warnings = []

    # Null check
    if output is None:
        errors.append(f"{phase_name}: output is None")
        return {"valid": False, "errors": errors, "warnings": warnings}

    # Type check
    req_type = schema.get("required_type")
    if req_type:
        if req_type == str and not isinstance(output, str):
            errors.append(f"{phase_name}: expected str, got {type(output).__name__}")
        elif req_type == list and not isinstance(output, list):
            errors.append(f"{phase_name}: expected list, got {type(output).__name__}")
        elif req_type == dict and not isinstance(output, dict):
            errors.append(f"{phase_name}: expected dict, got {type(output).__name__}")

    # Attribute check (for plan objects)
    req_attrs = schema.get("required_attrs", [])
    for attr in req_attrs:
        if not hasattr(output, attr):
            errors.append(f"{phase_name}: missing attribute '{attr}'")

    # Min length/steps
    min_len = schema.get("min_length")
    if min_len is not None:
        if isinstance(output, str) and len(output) < min_len:
            warnings.append(f"{phase_name}: output too short ({len(output)} < {min_len})")
        elif isinstance(output, list) and len(output) < min_len:
            warnings.append(f"{phase_name}: too few items ({len(output)} < {min_len})")

    min_steps = schema.get("min_steps")
    if min_steps is not None and hasattr(output, "steps"):
        if len(output.steps) < min_steps:
            errors.append(f"{phase_name}: plan has {len(output.steps)} steps, need {min_steps}+")

    # Required keys (for dicts)
    req_keys = schema.get("required_keys", [])
    if isinstance(output, dict):
        for key in req_keys:
            if key not in output:
                warnings.append(f"{phase_name}: missing key '{key}'")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Aggregate scoring
# ---------------------------------------------------------------------------

def score_all_phases(result: dict, plan: Any = None,
                     research_text: Any = None,
                     exec_results: list = None) -> dict:
    """Score all phases in a job result. Returns per-phase scores + aggregate.

    This function scores the following phases: research, plan, execute, code_review, verify, and deliver.
    This is called at the end of the pipeline to add quality_score to each phase.
    """
    phases = result.get("phases", {})
    scores = {}

    # Research
    if "research" in phases:
        scores["research"] = score_research(phases["research"], research_text)

    # Plan
    if "plan" in phases:
        scores["plan"] = score_plan(phases["plan"], plan)

    # Execute
    if "execute" in phases:
        scores["execute"] = score_execute(phases["execute"], exec_results or [])

    # Code review
    if "code_review" in phases:
        scores["code_review"] = score_code_review(phases["code_review"])

    # Verify
    if "verify" in phases:
        scores["verify"] = score_verify(phases["verify"])

    # Deliver
    if "deliver" in phases:
        scores["deliver"] = score_deliver(phases["deliver"])

    # Aggregate
    phase_scores = [s["score"] for s in scores.values()]
    aggregate = sum(phase_scores) / len(phase_scores) if phase_scores else 0.0

    return {
        "phases": scores,
        "aggregate": round(aggregate, 3),
        "scored_phases": len(phase_scores),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_read_before_edit(steps) -> bool | None:
    """Check if plan reads files before editing them. Returns None if N/A."""
    read_tools = {"file_read", "read", "Read", "Glob", "Grep"}
    edit_tools = {"file_edit", "file_write", "Edit", "Write"}

    first_read = None
    first_edit = None

    for i, step in enumerate(steps):
        hints = set(getattr(step, "tool_hints", []))
        desc = getattr(step, "description", "").lower()

        is_read = bool(hints & read_tools) or "read" in desc
        is_edit = bool(hints & edit_tools) or "edit" in desc or "write" in desc

        if is_read and first_read is None:
            first_read = i
        if is_edit and first_edit is None:
            first_edit = i

    if first_read is not None and first_edit is not None:
        return first_read < first_edit
    return None  # can't determine
