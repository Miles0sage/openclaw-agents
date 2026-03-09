"""
OpenClaw Reflexion Loop — Self-improving agent memory

After each job, stores a reflection. Before new jobs, injects relevant past reflections.
Primary backend: Supabase | Fallback: JSON files on disk

v2: Structured reflections with what_worked/what_failed/missing_tools analysis
"""
import os
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("reflexion")

REFLECTIONS_DIR = Path("/root/openclaw/data/reflections")


def ensure_dir():
    REFLECTIONS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def _sb():
    try:
        from supabase_client import table_insert, table_select, is_connected
        return {"insert": table_insert, "select": table_select, "connected": is_connected}
    except Exception:
        return None


def _use_supabase() -> bool:
    try:
        sb = _sb()
        return sb is not None and sb["connected"]()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Structured Reflection
# ---------------------------------------------------------------------------

@dataclass
class StructuredReflection:
    """Rich post-job reflection with actionable insights."""
    job_id: str
    task: str
    outcome: str  # success | partial | failed
    what_worked: list = field(default_factory=list)
    what_failed: list = field(default_factory=list)
    missing_tools: list = field(default_factory=list)
    missing_knowledge: list = field(default_factory=list)
    time_wasted_on: list = field(default_factory=list)
    suggested_improvements: list = field(default_factory=list)
    confidence: float = 0.5  # 0-1, how confident the agent was in its output
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    phases_completed: int = 0
    phases_total: int = 5
    error_type: str = ""  # budget | guardrail | timeout | code_error | ""


def _extract_structured_insights(run_result: dict, job_data: dict, outcome: str) -> StructuredReflection:
    """Analyze the runner's result dict to extract structured insights."""
    phases = run_result.get("phases", {})
    guardrails = run_result.get("guardrails", {})
    error = run_result.get("error")
    cost = run_result.get("cost_usd", 0)
    task = job_data.get("task", "")

    sr = StructuredReflection(
        job_id=run_result.get("job_id", ""),
        task=task,
        outcome=outcome,
        cost_usd=cost,
    )

    # --- Analyze phases ---
    phase_names = ["research", "plan", "execute", "verify", "deliver"]
    completed = 0
    for pname in phase_names:
        pdata = phases.get(pname, {})
        if not pdata:
            continue
        status = pdata.get("status", "")
        if status == "done":
            completed += 1
        elif status == "skipped":
            pass  # resumed job, don't count
        elif status == "partial":
            completed += 0.5
            failed_steps = pdata.get("steps_failed", 0)
            if failed_steps:
                sr.what_failed.append(f"Execute phase: {failed_steps} step(s) failed out of {pdata.get('steps_done', 0) + failed_steps}")

    sr.phases_completed = int(completed)

    # What worked — successful phases
    if phases.get("research", {}).get("status") == "done":
        length = phases["research"].get("length", 0)
        if length > 500:
            sr.what_worked.append(f"Research phase produced {length} chars of useful context")
        elif length > 0:
            sr.what_worked.append("Research phase completed (brief output)")

    if phases.get("plan", {}).get("status") == "done":
        steps = phases["plan"].get("steps", 0)
        sr.what_worked.append(f"Plan phase: {steps} step(s) generated")

    exec_phase = phases.get("execute", {})
    if exec_phase.get("status") == "done":
        steps_done = exec_phase.get("steps_done", 0)
        sr.what_worked.append(f"Execute phase: all {steps_done} step(s) completed")
    elif exec_phase.get("steps_done", 0) > 0:
        sr.what_worked.append(f"Execute phase: {exec_phase['steps_done']} step(s) succeeded")

    if phases.get("verify", {}).get("status") == "done":
        sr.what_worked.append("Verification passed")

    if phases.get("deliver", {}).get("delivered"):
        sr.what_worked.append("Delivery completed")
        pr = phases.get("deliver", {}).get("pr_url")
        if pr:
            sr.what_worked.append(f"PR created: {pr}")

    # --- Analyze failures ---
    if error:
        error_lower = str(error).lower()
        if "budget" in error_lower:
            sr.error_type = "budget"
            sr.what_failed.append(f"Hit budget limit: {error}")
            sr.suggested_improvements.append("Task may need higher budget or simpler decomposition")
        elif "guardrail" in error_lower or "kill" in error_lower:
            sr.error_type = "guardrail"
            sr.what_failed.append(f"Guardrail triggered: {error}")
            if "iteration" in error_lower:
                sr.time_wasted_on.append("Too many iterations — agent may have been looping")
                sr.suggested_improvements.append("Add clearer stop conditions or break task into smaller pieces")
            elif "timeout" in error_lower or "duration" in error_lower:
                sr.error_type = "timeout"
                sr.time_wasted_on.append("Task took too long")
                sr.suggested_improvements.append("Pre-fetch context to reduce research time")
        elif "timeout" in error_lower or "timed out" in error_lower:
            sr.error_type = "timeout"
            sr.what_failed.append(f"Timed out: {error}")
            sr.time_wasted_on.append("Agent ran out of time before completing")
        elif "credit" in error_lower or "billing" in error_lower:
            sr.error_type = "budget"
            sr.what_failed.append(f"Credit/billing issue: {error}")
        else:
            sr.error_type = "code_error"
            sr.what_failed.append(f"Error: {str(error)[:200]}")

    # No phases completed at all
    if sr.phases_completed == 0 and not error:
        sr.what_failed.append("No phases completed — possible early abort")

    # --- Analyze guardrail metrics ---
    if guardrails:
        iterations = guardrails.get("iterations", 0)
        max_iters = guardrails.get("max_iterations", 50)
        if iterations > max_iters * 0.8:
            sr.time_wasted_on.append(f"Used {iterations}/{max_iters} iterations — near limit")
            sr.suggested_improvements.append("Optimize prompts to reduce iteration count")

        cost_pct = (cost / guardrails.get("max_cost_usd", 2.0)) * 100 if guardrails.get("max_cost_usd") else 0
        if cost_pct > 80:
            sr.time_wasted_on.append(f"Cost was {cost_pct:.0f}% of budget (${cost:.4f})")

    # --- Confidence scoring ---
    if outcome == "success":
        sr.confidence = 0.8
        if phases.get("verify", {}).get("status") == "done":
            sr.confidence = 0.9
        if exec_phase.get("steps_failed", 0) > 0:
            sr.confidence -= 0.2
    elif outcome == "partial":
        sr.confidence = 0.4
    else:
        sr.confidence = 0.1 if sr.phases_completed == 0 else 0.2

    # --- Outcome-based suggestions ---
    if outcome == "success" and cost > 0.5:
        sr.suggested_improvements.append(f"Successful but expensive (${cost:.4f}) — consider simpler approach")
    if outcome == "failed" and sr.phases_completed >= 3:
        sr.suggested_improvements.append("Got through most phases — failure was late-stage, review verify/deliver")
    if outcome == "failed" and sr.phases_completed <= 1:
        sr.suggested_improvements.append("Failed early — research or planning may need better context")

    return sr


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def save_reflection(job_id: str, job_data: dict, outcome: str, duration_seconds: float = 0,
                    department: str = "", run_result: dict = None):
    """Save a post-job reflection. Called after job completes.

    When run_result is provided, extracts structured insights from the full
    pipeline result (phases, guardrails, costs, errors). Falls back to
    simple template learnings when run_result is None (backward compat).
    """
    ensure_dir()

    tags = list(_extract_tags(job_data.get("task", "")))

    # Extract structured insights if we have the full result
    structured = None
    if run_result:
        structured = _extract_structured_insights(run_result, job_data, outcome)
        structured.duration_seconds = duration_seconds
        # Build learnings from structured data (backward-compatible summary)
        learnings = []
        for item in structured.what_worked:
            learnings.append(f"[OK] {item}")
        for item in structured.what_failed:
            learnings.append(f"[FAIL] {item}")
        for item in structured.time_wasted_on:
            learnings.append(f"[WASTE] {item}")
        for item in structured.suggested_improvements:
            learnings.append(f"[IMPROVE] {item}")
        if not learnings:
            learnings = [f"Task '{job_data.get('task', '')[:100]}' — {outcome}"]
    else:
        # Legacy path — simple template learnings
        if outcome == "success":
            learnings = [
                f"Task '{job_data.get('task', '')[:100]}' completed successfully",
                f"Project: {job_data.get('project', 'unknown')}",
                f"Duration: {duration_seconds:.0f}s",
            ]
        else:
            learnings = [
                f"Task '{job_data.get('task', '')[:100]}' FAILED",
                f"Project: {job_data.get('project', 'unknown')}",
                "Review logs for error details",
            ]

    # Build the full reflection dict
    reflection = {
        "job_id": job_id,
        "project": job_data.get("project", "unknown"),
        "task": job_data.get("task", ""),
        "outcome": outcome,
        "department": department,
        "duration_seconds": duration_seconds,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tags": tags,
        "learnings": learnings,
    }
    # Attach structured data if available
    if structured:
        reflection["structured"] = asdict(structured)

    # Try Supabase first
    if _use_supabase():
        sb = _sb()
        structured_json = json.dumps(asdict(structured)) if structured else ""
        row = {
            "job_id": job_id,
            "project": reflection["project"],
            "task": reflection["task"],
            "outcome": outcome,
            "reflection": structured_json or json.dumps(learnings),
            "lessons": learnings,
            "cost_usd": run_result.get("cost_usd", 0) if run_result else job_data.get("cost_usd", 0),
            "duration_seconds": int(duration_seconds),
            "created_at": reflection["timestamp"],
        }
        result = sb["insert"]("reflections", row)
        if result:
            logger.info(f"Reflection saved (Supabase): {job_id} [dept={department}, structured={'yes' if structured else 'no'}]")
            return job_id

    # JSON file fallback
    filepath = REFLECTIONS_DIR / f"{job_id}.json"
    with open(filepath, "w") as f:
        json.dump(reflection, f, indent=2)
    logger.info(f"Reflection saved (file): {filepath} [dept={department}, structured={'yes' if structured else 'no'}]")
    return filepath


def search_reflections(task_description: str, project: str = None, department: str = None, limit: int = 3) -> list:
    """Find relevant past reflections for a new task.

    When department is specified, prioritizes same-department reflections
    and pads with cross-department results.
    """

    # Try Supabase first — get all reflections and score locally
    if _use_supabase():
        sb = _sb()
        query = "order=created_at.desc"
        if project:
            query = f"project=eq.{project}&{query}"
        rows = sb["select"]("reflections", query, limit=200)
        if rows:
            return _score_and_rank(rows, task_description, project, limit, department=department)

    # File fallback
    ensure_dir()
    all_reflections = []
    for filepath in REFLECTIONS_DIR.glob("*.json"):
        try:
            with open(filepath) as f:
                ref = json.load(f)
            all_reflections.append(ref)
        except (json.JSONDecodeError, IOError):
            continue

    return _score_and_rank(all_reflections, task_description, project, limit, department=department)


def _score_and_rank(reflections: list, task_description: str, project: str, limit: int, department: str = None) -> list:
    """Score reflections by relevance to a task and return top matches.

    When department is specified, same-department reflections get a bonus
    and are prioritized in the results.
    """
    tags = _extract_tags(task_description)
    scored = []

    for ref in reflections:
        score = 0
        # Tag overlap (Supabase rows use 'lessons' array, file rows use 'tags')
        ref_tags = set(ref.get("tags", []) or [])
        if not ref_tags:
            ref_tags = _extract_tags(ref.get("task", ""))
        score += len(tags & ref_tags) * 2

        if project and ref.get("project") == project:
            score += 3

        # Department bonus: same-department reflections are more relevant
        if department and ref.get("department") == department:
            score += 4

        task_words = set(task_description.lower().split())
        ref_words = set(ref.get("task", "").lower().split())
        score += len(task_words & ref_words)

        if score > 0:
            ref["_relevance_score"] = score
            # Normalize learnings field
            if "learnings" not in ref and "lessons" in ref:
                ref["learnings"] = ref["lessons"]
            scored.append(ref)

    scored.sort(key=lambda r: (r.get("_relevance_score", 0), r.get("timestamp", r.get("created_at", ""))), reverse=True)

    # When department is set, ensure same-department results come first
    if department:
        dept_results = [r for r in scored if r.get("department") == department]
        other_results = [r for r in scored if r.get("department") != department]
        return (dept_results + other_results)[:limit]

    return scored[:limit]


def format_reflections_for_prompt(reflections: list) -> str:
    """Format reflections as context to inject into agent prompts.

    Uses structured data when available for richer, more actionable context.
    Falls back to simple learnings list for older reflections.
    """
    if not reflections:
        return ""

    lines = ["## Past Experience (from similar tasks)"]
    for ref in reflections:
        outcome_label = "SUCCESS" if ref.get("outcome") == "success" else "FAILED"
        lines.append(f"\n### [{outcome_label}] {ref.get('task', 'Unknown task')[:120]}")
        dur = ref.get("duration_seconds", 0)
        cost = ref.get("cost_usd", 0)
        meta = f"Project: {ref.get('project', '?')}"
        if dur:
            meta += f" | Duration: {dur:.0f}s"
        if cost:
            meta += f" | Cost: ${cost:.4f}"
        lines.append(meta)

        # Try structured data first (from 'structured' key or parsed 'reflection' column)
        structured = ref.get("structured")
        if not structured and ref.get("reflection"):
            try:
                parsed = json.loads(ref["reflection"]) if isinstance(ref["reflection"], str) else ref["reflection"]
                if isinstance(parsed, dict) and "what_worked" in parsed:
                    structured = parsed
            except (json.JSONDecodeError, TypeError):
                pass

        if structured:
            if structured.get("what_worked"):
                lines.append("**What worked:**")
                for item in structured["what_worked"][:3]:
                    lines.append(f"  + {item}")
            if structured.get("what_failed"):
                lines.append("**What failed:**")
                for item in structured["what_failed"][:3]:
                    lines.append(f"  - {item}")
            if structured.get("suggested_improvements"):
                lines.append("**Advice:**")
                for item in structured["suggested_improvements"][:2]:
                    lines.append(f"  > {item}")
            if structured.get("missing_tools"):
                lines.append(f"**Missing tools:** {', '.join(structured['missing_tools'][:3])}")
            if structured.get("time_wasted_on"):
                lines.append(f"**Time wasted on:** {'; '.join(structured['time_wasted_on'][:2])}")
        else:
            # Legacy format — simple learnings list
            for learning in ref.get("learnings", ref.get("lessons", [])):
                lines.append(f"- {learning}")

    lines.append("\nUse these past experiences to inform your approach. Avoid repeating past failures.")
    return "\n".join(lines)


def get_stats() -> dict:
    """Get reflection statistics."""
    if _use_supabase():
        sb = _sb()
        rows = sb["select"]("reflections", "", limit=5000)
        if rows is not None:
            total = len(rows)
            successes = sum(1 for r in rows if r.get("outcome") == "success")
            failures = total - successes
            return {
                "total_reflections": total,
                "successes": successes,
                "failures": failures,
                "success_rate": f"{successes/total*100:.1f}%" if total > 0 else "N/A",
            }

    # File fallback
    ensure_dir()
    total = 0
    successes = 0
    for filepath in REFLECTIONS_DIR.glob("*.json"):
        try:
            with open(filepath) as f:
                ref = json.load(f)
            total += 1
            if ref.get("outcome") == "success":
                successes += 1
        except Exception:
            continue

    return {
        "total_reflections": total,
        "successes": successes,
        "failures": total - successes,
        "success_rate": f"{successes/total*100:.1f}%" if total > 0 else "N/A",
    }


def list_reflections(project: str = None, limit: int = 50) -> list:
    """List all reflections, optionally filtered by project."""
    if _use_supabase():
        sb = _sb()
        query = "order=created_at.desc"
        if project:
            query = f"project=eq.{project}&{query}"
        rows = sb["select"]("reflections", query, limit=limit)
        if rows is not None:
            return rows

    # File fallback
    ensure_dir()
    results = []
    for filepath in sorted(REFLECTIONS_DIR.glob("*.json"), reverse=True):
        try:
            with open(filepath) as f:
                ref = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue
        if project and ref.get("project") != project:
            continue
        results.append(ref)
        if len(results) >= limit:
            break
    return results


def _extract_tags(text: str) -> set:
    """Extract relevant tags from task text for matching."""
    tag_keywords = {
        "deploy", "vercel", "supabase", "database", "sql", "api", "endpoint",
        "frontend", "backend", "css", "tailwind", "react", "next", "nextjs",
        "bug", "fix", "refactor", "test", "security", "audit", "pentest",
        "docker", "git", "ci", "cd", "pipeline", "build", "install",
        "auth", "login", "signup", "email", "notification", "slack",
        "performance", "optimize", "cache", "migration", "schema",
        "component", "page", "route", "middleware", "hook",
        "openclaw", "delhi", "barber", "prestress", "canoe",
    }
    words = set(text.lower().split())
    return words & tag_keywords
