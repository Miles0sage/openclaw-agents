"""
repo_map.py — Auto-generate project structure summaries for agent context.

Scans a project directory and produces a compact text map showing:
- Directory tree (configurable depth)
- Lines of code for source files
- Detected technologies and frameworks
- Entry points and key files

Designed to fit in ~2000 tokens so agents skip the 10-15 minute
exploration phase and jump straight into productive work.

Usage:
    from repo_map import generate_repo_map
    summary = generate_repo_map(".", max_depth=3)
"""

import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("repo_map")

# Directories to always skip
SKIP_DIRS = {
    ".git", ".github", "__pycache__", "node_modules", ".next", ".vercel",
    ".cache", ".claude", "dist", "build", ".tox", ".pytest_cache",
    ".mypy_cache", "venv", ".venv", "env", ".env", "egg-info",
    ".eggs", "htmlcov", ".coverage", "coverage", ".svn", ".hg",
    "vendor", "bower_components",
}

# Files to skip
SKIP_FILES = {
    ".DS_Store", "Thumbs.db", ".gitignore", ".gitattributes",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Pipfile.lock", "bun.lockb",
}

# Extensions we count LOC for
SOURCE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
    ".c", ".cpp", ".h", ".hpp", ".rb", ".php", ".swift", ".kt",
    ".sql", ".sh", ".bash", ".zsh", ".r", ".R",
}

# Config/markup extensions (show but don't count LOC)
CONFIG_EXTENSIONS = {
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env",
    ".md", ".rst", ".txt", ".html", ".css", ".scss", ".xml",
    ".dockerfile", ".dockerignore",
}

# Technology detection rules: (indicator_file, tech_name)
TECH_INDICATORS = [
    ("requirements.txt", "Python"),
    ("pyproject.toml", "Python"),
    ("setup.py", "Python"),
    ("Pipfile", "Python"),
    ("package.json", "Node.js"),
    ("tsconfig.json", "TypeScript"),
    ("next.config.js", "Next.js"),
    ("next.config.ts", "Next.js"),
    ("next.config.mjs", "Next.js"),
    ("nuxt.config.ts", "Nuxt"),
    ("vite.config.ts", "Vite"),
    ("vite.config.js", "Vite"),
    ("docker-compose.yml", "Docker"),
    ("docker-compose.yaml", "Docker"),
    ("Dockerfile", "Docker"),
    (".github/workflows", "GitHub Actions"),
    ("vercel.json", "Vercel"),
    ("Cargo.toml", "Rust"),
    ("go.mod", "Go"),
    ("Gemfile", "Ruby"),
    ("composer.json", "PHP"),
    ("pom.xml", "Java/Maven"),
    ("build.gradle", "Java/Gradle"),
    ("Makefile", "Make"),
    (".env", "dotenv"),
    ("supabase", "Supabase"),
    ("prisma", "Prisma"),
    ("tailwind.config.js", "Tailwind CSS"),
    ("tailwind.config.ts", "Tailwind CSS"),
    ("postcss.config.js", "PostCSS"),
    ("jest.config.js", "Jest"),
    ("jest.config.ts", "Jest"),
    ("pytest.ini", "pytest"),
    ("setup.cfg", "pytest"),
    (".eslintrc.js", "ESLint"),
    ("wrangler.toml", "Cloudflare Workers"),
]

# Key file patterns that indicate entry points
ENTRY_POINT_PATTERNS = [
    "main.py", "app.py", "server.py", "gateway.py", "index.py",
    "index.js", "index.ts", "main.js", "main.ts", "server.js", "server.ts",
    "app.js", "app.ts", "main.go", "main.rs",
    "manage.py", "wsgi.py", "asgi.py",
]


def generate_repo_map(
    root_dir: str,
    max_depth: int = 3,
    max_files_per_dir: int = 25,
    include_loc: bool = True,
    include_techs: bool = True,
) -> str:
    """
    Generate a compact project structure map.

    Args:
        root_dir: Absolute path to project root
        max_depth: Maximum directory depth to scan
        max_files_per_dir: Skip dirs with more files than this (noise)
        include_loc: Count lines of code for source files
        include_techs: Detect technologies section

    Returns:
        Text-based project map, typically 50-200 lines
    """
    root = Path(root_dir)
    if not root.is_dir():
        return f"ERROR: {root_dir} is not a directory"

    project_name = root.name
    lines = [f"PROJECT: {project_name}/"]
    lines.append("=" * (len(project_name) + 10))

    # Build tree
    loc_map: Dict[str, int] = {}
    tree_lines = _build_tree_lines(root, root, max_depth, 0, max_files_per_dir, loc_map if include_loc else None)
    lines.extend(tree_lines)

    # Stats
    total_files = sum(1 for _ in root.rglob("*") if _.is_file() and not _should_skip_path(_))
    total_loc = sum(loc_map.values()) if loc_map else 0

    lines.append("")
    stats = [f"Files: {total_files}"]
    if total_loc > 0:
        stats.append(f"Source LOC: {total_loc:,}")
    lines.append(" | ".join(stats))

    # Technologies
    if include_techs:
        techs = _detect_technologies(root)
        if techs:
            lines.append(f"Stack: {', '.join(techs)}")

    # Entry points
    entry_points = _find_entry_points(root)
    if entry_points:
        lines.append(f"Entry: {', '.join(entry_points)}")

    # Key dependencies (from requirements.txt or package.json)
    deps = _get_key_dependencies(root)
    if deps:
        lines.append(f"Deps: {', '.join(deps)}")

    return "\n".join(lines)


def _should_skip_path(path: Path) -> bool:
    """Check if a path should be skipped."""
    for part in path.parts:
        if part in SKIP_DIRS:
            return True
    if path.name in SKIP_FILES:
        return True
    return False


def _build_tree_lines(
    path: Path,
    root: Path,
    max_depth: int,
    depth: int,
    max_files: int,
    loc_map: Optional[Dict[str, int]],
) -> List[str]:
    """Recursively build tree lines with LOC annotations."""
    if depth >= max_depth:
        return []

    lines = []
    prefix = "  " * depth

    try:
        entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except (PermissionError, OSError):
        return []

    # Separate dirs and files
    dirs = []
    files = []
    for entry in entries:
        if entry.name.startswith(".") and entry.name not in (".env",):
            continue
        if _should_skip_path(entry):
            continue
        if entry.is_dir():
            dirs.append(entry)
        elif entry.is_file():
            files.append(entry)

    # If too many files, summarize
    if len(files) > max_files:
        # Group by extension
        ext_counts: Dict[str, int] = {}
        for f in files:
            ext = f.suffix or "(no ext)"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
        summary = ", ".join(f"{count}{ext}" for ext, count in sorted(ext_counts.items(), key=lambda x: -x[1])[:5])
        lines.append(f"{prefix}[{len(files)} files: {summary}]")
    else:
        for f in files:
            rel_path = str(f.relative_to(root))
            loc_str = ""

            if loc_map is not None and f.suffix in SOURCE_EXTENSIONS:
                loc = _count_file_loc(f)
                if loc > 0:
                    loc_map[rel_path] = loc
                    loc_str = f" ({loc} LOC)"

            # Annotate key files
            annotation = _annotate_file(f)
            if annotation:
                loc_str = f"{loc_str} — {annotation}"

            lines.append(f"{prefix}{f.name}{loc_str}")

    # Recurse into directories
    for d in dirs:
        child_lines = _build_tree_lines(d, root, max_depth, depth + 1, max_files, loc_map)
        if child_lines:
            lines.append(f"{prefix}{d.name}/")
            lines.extend(child_lines)
        else:
            # Empty or skipped dir — still show it exists
            sub_count = sum(1 for _ in d.iterdir()) if d.exists() else 0
            if sub_count > 0:
                lines.append(f"{prefix}{d.name}/ [{sub_count} items]")

    return lines


def _count_file_loc(filepath: Path) -> int:
    """Count non-empty, non-comment lines in a source file."""
    try:
        with open(filepath, "r", errors="ignore") as f:
            count = 0
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and not stripped.startswith("//"):
                    count += 1
            return count
    except Exception:
        return 0


def _annotate_file(filepath: Path) -> str:
    """Return a short annotation for known file types."""
    name = filepath.name.lower()

    annotations = {
        "gateway.py": "FastAPI server",
        "autonomous_runner.py": "Job pipeline executor",
        "event_engine.py": "Event pub/sub",
        "tool_router.py": "Phase-gated tool dispatch",
        "cost_tracker.py": "Cost logging",
        "cost_breakdown.py": "Cost aggregation",
        "job_manager.py": "Job queue",
        "semantic_index.py": "Vector search",
        "ide_session.py": "Session persistence",
        "pa_integration.py": "PA bridge",
        "opencode_executor.py": "OpenCode CLI wrapper",
        "gateway_monitoring.py": "Real-time monitoring",
        "supabase_client.py": "DB client",
        "config.json": "Agent config",
        "agent_tools.py": "Tool definitions",
        "departments.py": "Department routing",
        "reflexion.py": "Learning system",
        "checkpoint.py": "Resume support",
    }

    return annotations.get(name, "")


def _detect_technologies(root: Path) -> List[str]:
    """Detect technologies from indicator files."""
    techs = []
    seen = set()

    for indicator, tech in TECH_INDICATORS:
        if tech in seen:
            continue
        indicator_path = root / indicator
        if indicator_path.exists():
            techs.append(tech)
            seen.add(tech)

    return techs


def _find_entry_points(root: Path) -> List[str]:
    """Find likely entry point files."""
    found = []
    for pattern in ENTRY_POINT_PATTERNS:
        matches = list(root.glob(pattern))
        if not matches:
            matches = list(root.glob(f"*/{pattern}"))
        for m in matches[:1]:
            rel = str(m.relative_to(root))
            if rel not in found:
                found.append(rel)
    return found[:5]


def _get_key_dependencies(root: Path) -> List[str]:
    """Extract top dependencies from requirements.txt or package.json."""
    deps = []

    # Python requirements
    req_file = root / "requirements.txt"
    if req_file.exists():
        try:
            with open(req_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith("-"):
                        pkg = line.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0].strip()
                        if pkg:
                            deps.append(pkg)
                        if len(deps) >= 10:
                            break
        except Exception:
            pass

    # Node package.json
    pkg_file = root / "package.json"
    if pkg_file.exists():
        try:
            import json
            with open(pkg_file) as f:
                pkg = json.load(f)
            for key in ("dependencies", "devDependencies"):
                for dep in list(pkg.get(key, {}).keys())[:5]:
                    deps.append(dep)
        except Exception:
            pass

    return deps[:12]


def generate_compact_map(root_dir: str) -> str:
    """Generate an ultra-compact map for tight token budgets (~500 tokens)."""
    return generate_repo_map(root_dir, max_depth=2, include_loc=False, include_techs=True)


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    print(generate_repo_map(target))
