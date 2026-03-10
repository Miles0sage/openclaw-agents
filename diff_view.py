# Generates git-style unified diffs for compact change visualization
"""
diff_view.py — Generate git-style unified diffs for code edits.

Instead of returning full file contents after edits, agents see
only the changed lines with context. Cuts context size by ~50%.

Usage:
    from diff_view import unified_diff, format_edit_result

    diff = unified_diff(old_content, new_content, filename="auth.py")
    result = format_edit_result(filename, old_content, new_content, success=True)
"""

import difflib
import logging
from typing import Optional

logger = logging.getLogger("diff_view")


# Generate git-style unified diff showing only changed lines with context
def unified_diff(
    old_content: str,
    new_content: str,
    filename: str = "file",
    context_lines: int = 3,
) -> str:
    """
    Generate a unified diff showing only changes with context.

    Args:
        old_content: Original file content
        new_content: Modified file content
        filename: Display name for the file
        context_lines: Number of context lines around each change

    Returns:
        Unified diff string, or empty string if no changes
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    # Ensure last lines end with newline for clean diff
    if old_lines and not old_lines[-1].endswith("\n"):
        old_lines[-1] += "\n"
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        n=context_lines,
    )

    return "".join(diff)


def format_edit_result(
    filename: str,
    old_content: str,
    new_content: str,
    success: bool = True,
    error: Optional[str] = None,
) -> str:
    """
    Format a complete edit result message for agent consumption.

    Returns a compact string with:
    - Status line
    - Unified diff
    - Change statistics
    """
    if not success:
        return f"EDIT FAILED: {filename}\nError: {error or 'Unknown error'}"

    if old_content == new_content:
        return f"NO CHANGES: {filename} (content unchanged)"

    diff = unified_diff(old_content, new_content, filename)

    if not diff:
        return f"EDIT OK: {filename} (no visible diff)"

    # Count changes
    added = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))

    stats = f"+{added} -{removed}"
    header = f"EDIT OK: {filename} [{stats}]"

    return f"{header}\n{diff}"


def summarize_changes(
    old_content: str,
    new_content: str,
    filename: str = "file",
) -> str:
    """
    Ultra-compact change summary (1-2 lines) for event logs.

    Example: "auth.py: +3 -1 lines (added scope validation)"
    """
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()

    added = 0
    removed = 0

    for line in difflib.unified_diff(old_lines, new_lines, n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1

    if added == 0 and removed == 0:
        return f"{filename}: no changes"

    return f"{filename}: +{added} -{removed} lines"


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    old = """def hello():
    print("Hello")
    return True

def goodbye():
    print("Bye")
"""

    new = """def hello():
    print("Hello, World!")
    # Validate input
    if not valid:
        raise ValueError("Invalid")
    return True

def goodbye():
    print("Bye")
"""

    print(unified_diff(old, new, "example.py"))
    print("---")
    print(format_edit_result("example.py", old, new))
    print("---")
    print(summarize_changes(old, new, "example.py"))
