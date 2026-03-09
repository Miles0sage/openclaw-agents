"""
OpenClaw Auto-Skill Extraction — Self-improving skill library

After successful jobs, analyzes execution patterns and generates reusable skill files.
Hooks into autonomous_runner.py after save_reflection().
"""
import os
import json
import re
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("openclaw.auto_skills")

SKILLS_DIR = Path("/root/.claude/skills")
JOBS_DIR = Path("os.environ.get("OPENCLAW_DATA_DIR", "./data")/jobs/runs")
REFLECTIONS_DIR = Path("os.environ.get("OPENCLAW_DATA_DIR", "./data")/reflections")

# Minimum thresholds for skill extraction
MIN_PLAN_STEPS = 3          # Don't extract trivial jobs
MIN_EXECUTE_STEPS = 3       # Need meaningful execution
DUPLICATE_SIMILARITY = 0.6  # Threshold for considering a skill duplicate


def extract_skill_from_job(
    job_id: str,
    job_data: dict,
    result: dict,
    run_dir: str = None,
) -> dict | None:
    """
    Analyze a completed successful job and extract a reusable skill.
    Returns skill dict with name, content, etc. or None if not extractable.
    """
    if not result.get("success"):
        return None

    task = job_data.get("task", "")
    project = job_data.get("project", "unknown")
    agent = result.get("agent", "unknown")
    phases = result.get("phases", {})

    # Check minimum complexity
    plan_data = phases.get("plan", {})
    exec_data = phases.get("execute", {})
    plan_steps = plan_data.get("steps", 0)
    exec_steps = exec_data.get("steps_done", 0)

    if plan_steps < MIN_PLAN_STEPS or exec_steps < MIN_EXECUTE_STEPS:
        logger.debug(f"Job {job_id} too simple for skill extraction ({plan_steps} plan, {exec_steps} exec steps)")
        return None

    # Determine run directory
    if not run_dir:
        run_dir = str(JOBS_DIR / job_id)

    run_path = Path(run_dir)

    # Gather job artifacts
    plan = _load_json(run_path / "plan.json")
    verify = phases.get("verify", {})
    deliver = phases.get("deliver", {})

    # Extract metadata
    skill_name = _generate_skill_name(task, project)
    tags = _extract_tags(task)
    tools_used = _extract_tools_from_logs(run_path)
    code_patterns = _extract_code_patterns(run_path)
    plan_steps_text = _extract_plan_steps(plan)

    # Check for duplicates
    if _is_duplicate_skill(skill_name, tags, task):
        logger.debug(f"Skill '{skill_name}' already exists or is too similar to existing skill")
        return None

    # Build skill content
    content = _build_skill_content(
        name=skill_name,
        task=task,
        project=project,
        agent=agent,
        job_id=job_id,
        tags=tags,
        tools_used=tools_used,
        plan_steps=plan_steps_text,
        code_patterns=code_patterns,
        verify_summary=verify.get("summary", ""),
        deliver_summary=deliver.get("summary", ""),
        duration=result.get("completed_at", ""),
        cost=result.get("cost_usd", 0),
    )

    return {
        "name": skill_name,
        "content": content,
        "tags": list(tags),
        "source_job": job_id,
    }


def save_skill(skill: dict) -> Path:
    """Save extracted skill to the skills library."""
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = SKILLS_DIR / f"{skill['name']}.md"

    with open(filepath, "w") as f:
        f.write(skill["content"])

    logger.info(f"Auto-skill saved: {filepath}")
    return filepath


def try_extract_and_save(job_id: str, job_data: dict, result: dict) -> str | None:
    """Convenience wrapper — extract + save in one call. Returns skill name or None."""
    try:
        skill = extract_skill_from_job(job_id, job_data, result)
        if skill:
            save_skill(skill)
            return skill["name"]
    except Exception as e:
        logger.warning(f"Auto-skill extraction failed for {job_id}: {e}")
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _generate_skill_name(task: str, project: str) -> str:
    """Generate a kebab-case skill name from the task description."""
    # Extract key action words
    task_lower = task.lower()

    # Remove common filler words
    stopwords = {
        "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
        "is", "are", "was", "were", "be", "been", "being", "have", "has",
        "had", "do", "does", "did", "will", "would", "could", "should",
        "may", "might", "must", "shall", "can", "that", "this", "these",
        "those", "it", "its", "from", "with", "by", "as", "but", "not",
        "all", "any", "each", "every", "both", "few", "more", "most",
        "other", "some", "such", "no", "nor", "only", "own", "same",
        "so", "than", "too", "very", "just", "because", "if", "when",
        "where", "how", "what", "which", "who", "whom", "why",
    }

    # Clean and tokenize
    words = re.sub(r'[^a-z0-9\s]', '', task_lower).split()
    words = [w for w in words if w not in stopwords and len(w) > 2]

    # Take first 4-5 meaningful words
    name_words = words[:5]

    # Prefix with project if not already present
    if project and project.lower().replace("-", "") not in "".join(name_words):
        name_words = [project.lower()] + name_words[:4]

    name = "-".join(name_words[:5])

    # Ensure uniqueness with suffix if needed
    if (SKILLS_DIR / f"{name}.md").exists():
        name = f"{name}-v2"
        counter = 2
        while (SKILLS_DIR / f"{name}.md").exists():
            counter += 1
            name = re.sub(r'-v\d+$', f'-v{counter}', name)

    return name


def _extract_tags(text: str) -> set:
    """Extract relevant tags from task text."""
    tag_keywords = {
        "deploy", "vercel", "supabase", "database", "sql", "api", "endpoint",
        "frontend", "backend", "css", "tailwind", "react", "next", "nextjs",
        "bug", "fix", "refactor", "test", "security", "audit", "pentest",
        "docker", "git", "ci", "cd", "pipeline", "build", "install",
        "auth", "login", "signup", "email", "notification", "slack",
        "performance", "optimize", "cache", "migration", "schema",
        "component", "page", "route", "middleware", "hook",
        "openclaw", "delhi", "barber", "prestress", "canoe",
        "typescript", "python", "javascript", "node", "stripe",
        "kds", "menu", "order", "checkout", "webhook", "telegram",
        "rls", "policy", "function", "trigger", "index",
    }
    words = set(re.sub(r'[^a-z0-9\s]', '', text.lower()).split())
    return words & tag_keywords


def _extract_tools_from_logs(run_path: Path) -> list[str]:
    """Extract which tools were used during execution from JSONL logs."""
    tools = set()
    for log_file in ["execute.jsonl", "research.jsonl", "verify.jsonl", "deliver.jsonl"]:
        filepath = run_path / log_file
        if not filepath.exists():
            continue
        try:
            with open(filepath) as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        tool = entry.get("tool") or entry.get("tool_name") or ""
                        if tool:
                            tools.add(tool)
                    except json.JSONDecodeError:
                        continue
        except IOError:
            continue
    return sorted(tools)


def _extract_code_patterns(run_path: Path) -> list[dict]:
    """Extract code snippets from workspace files."""
    patterns = []
    workspace = run_path / "workspace"
    if not workspace.exists():
        return patterns

    for filepath in workspace.rglob("*"):
        if not filepath.is_file():
            continue
        if filepath.stat().st_size > 50000:  # Skip huge files
            continue

        try:
            content = filepath.read_text(errors="ignore")
        except Exception:
            continue

        # Only include meaningful files
        ext = filepath.suffix.lower()
        if ext in (".md", ".txt", ".json", ".ts", ".tsx", ".py", ".js", ".jsx", ".sql", ".css"):
            patterns.append({
                "file": filepath.name,
                "ext": ext,
                "preview": content[:500],
                "lines": content.count("\n") + 1,
            })

    return patterns[:5]  # Max 5 files


def _extract_plan_steps(plan: dict) -> list[str]:
    """Extract plan step descriptions."""
    if not plan:
        return []
    steps = plan.get("steps", [])
    return [s.get("description", "") for s in steps if s.get("description")]


def _is_duplicate_skill(name: str, tags: set, task: str) -> bool:
    """Check if a similar skill already exists."""
    if not SKILLS_DIR.exists():
        return False

    # Exact name match
    if (SKILLS_DIR / f"{name}.md").exists():
        return True

    # Check tag overlap with existing auto-generated skills
    task_words = set(task.lower().split())

    for skill_file in SKILLS_DIR.glob("*.md"):
        try:
            content = skill_file.read_text(errors="ignore")[:500]
            # Only check auto-generated skills
            if "source: auto-skill" not in content and "extracted_from_job" not in content:
                continue

            # Check word overlap in description
            skill_words = set(content.lower().split())
            overlap = len(task_words & skill_words) / max(len(task_words), 1)
            if overlap > DUPLICATE_SIMILARITY:
                return True
        except Exception:
            continue

    return False


def _build_skill_content(
    name: str,
    task: str,
    project: str,
    agent: str,
    job_id: str,
    tags: set,
    tools_used: list[str],
    plan_steps: list[str],
    code_patterns: list[dict],
    verify_summary: str,
    deliver_summary: str,
    duration: str,
    cost: float,
) -> str:
    """Build the full skill markdown content."""
    tags_str = ", ".join(sorted(tags)) if tags else "general"
    tools_str = ", ".join(tools_used) if tools_used else "general"

    lines = [
        "---",
        f'name: {name}',
        f'description: "Auto-extracted pattern from: {task[:120]}"',
        f'source: auto-skill',
        f'risk: unknown',
        f'extracted_from_job: "{job_id}"',
        f'project: "{project}"',
        f'agent: "{agent}"',
        f'tags: [{tags_str}]',
        "---",
        "",
        f"# {_title_case(name)}",
        "",
        f"Auto-extracted skill from successful job execution.",
        "",
        "## When to Use",
        f"- Tasks involving: {tags_str}",
        f"- Project context: {project}",
        f"- Similar to: {task[:150]}",
        "",
        "## Do Not Use",
        "- Unrelated domains or frameworks",
        "- When the task requires a fundamentally different approach",
        "",
    ]

    # Plan / approach section
    if plan_steps:
        lines.append("## Execution Pattern")
        lines.append("")
        lines.append(f"This task was completed in {len(plan_steps)} steps using `{agent}`:")
        lines.append("")
        for i, step in enumerate(plan_steps[:10], 1):
            lines.append(f"{i}. {step}")
        lines.append("")

    # Tools section
    if tools_used:
        lines.append("## Tools Used")
        lines.append("")
        for tool in tools_used:
            lines.append(f"- `{tool}`")
        lines.append("")

    # Code patterns section
    if code_patterns:
        lines.append("## Code Patterns")
        lines.append("")
        for pattern in code_patterns[:3]:
            lines.append(f"### {pattern['file']} ({pattern['lines']} lines)")
            lines.append("")
            ext_map = {".py": "python", ".ts": "typescript", ".tsx": "typescript",
                       ".js": "javascript", ".jsx": "javascript", ".sql": "sql",
                       ".css": "css", ".json": "json", ".md": "markdown"}
            lang = ext_map.get(pattern["ext"], "")
            lines.append(f"```{lang}")
            lines.append(pattern["preview"].strip())
            lines.append("```")
            lines.append("")

    # Verification section
    if verify_summary:
        lines.append("## Verification")
        lines.append("")
        # Truncate long verification summaries
        summary = verify_summary[:800]
        lines.append(summary)
        lines.append("")

    # Delivery section
    if deliver_summary:
        lines.append("## Delivery Summary")
        lines.append("")
        lines.append(deliver_summary[:500])
        lines.append("")

    # Metadata footer
    lines.append("## Metadata")
    lines.append("")
    lines.append(f"- **Job ID**: `{job_id}`")
    lines.append(f"- **Agent**: `{agent}`")
    lines.append(f"- **Project**: `{project}`")
    lines.append(f"- **Cost**: ${cost:.4f}")
    lines.append(f"- **Extracted**: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
    lines.append("")

    return "\n".join(lines)


def _title_case(kebab: str) -> str:
    """Convert kebab-case to Title Case."""
    return " ".join(w.capitalize() for w in kebab.split("-"))


def _load_json(path: Path) -> dict:
    """Safely load a JSON file."""
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Backfill — extract skills from all past successful jobs
# ---------------------------------------------------------------------------

def backfill_skills(limit: int = 50) -> list[str]:
    """Extract skills from past successful jobs that don't have skills yet."""
    if not JOBS_DIR.exists():
        return []

    extracted = []
    jobs_jsonl = Path("os.environ.get("OPENCLAW_DATA_DIR", "./data")/jobs/jobs.jsonl")

    if not jobs_jsonl.exists():
        return []

    # Load all jobs
    jobs = []
    with open(jobs_jsonl) as f:
        for line in f:
            try:
                job = json.loads(line.strip())
                if job.get("status") == "done":
                    jobs.append(job)
            except json.JSONDecodeError:
                continue

    for job in jobs[-limit:]:  # Most recent N
        job_id = job.get("id", "")
        run_dir = JOBS_DIR / job_id

        if not (run_dir / "result.json").exists():
            continue

        result = _load_json(run_dir / "result.json")
        if not result.get("success"):
            continue

        skill_name = try_extract_and_save(job_id, job, result)
        if skill_name:
            extracted.append(skill_name)

    return extracted
