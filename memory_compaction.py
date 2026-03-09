"""
Memory Compaction Strategy — Auto-saves important facts before context compaction.

Implements the compaction hook that:
1. Detects when Claude Code is about to compact context (>50% threshold)
2. Extracts important facts from current conversation
3. Flushes them to MEMORY.md before compaction happens
4. Ensures critical decisions aren't lost

This module can be called by settings.json hooks or directly.
"""

import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger("memory_compaction")


class MemoryCompactor:
    """
    Automatic memory compaction during context cleanup.

    Watches for compaction signals and extracts facts to save.
    """

    def __init__(self, memory_dir: str = "/root/.claude/projects/-root/memory"):
        self.memory_dir = memory_dir
        self.memory_index = os.path.join(memory_dir, "MEMORY.md")
        self.compaction_log = os.path.join(memory_dir, ".compaction_log.json")

        # Ensure memory dir exists
        os.makedirs(memory_dir, exist_ok=True)

    def extract_important_facts(self, conversation: str) -> List[Dict]:
        """
        Extract important facts from conversation before compaction.

        Returns list of facts with content, tags, importance.
        """
        facts = []

        # Simple heuristics to find important statements
        # In production, this could use NLP or Claude's judgment
        patterns = [
            ("decision:", 8),  # Explicit decisions
            ("decided to:", 8),
            ("important:", 7),
            ("critical:", 9),
            ("TODO:", 6),
            ("NOTE:", 6),
            ("learning:", 7),
            ("bug found:", 8),
            ("pattern:", 6),
            ("preference:", 6),
        ]

        lines = conversation.split("\n")
        for line in lines:
            line_lower = line.lower().strip()
            if not line_lower or len(line_lower) < 20:
                continue

            for pattern, default_importance in patterns:
                if pattern in line_lower:
                    fact = {
                        "content": line.strip(),
                        "tags": ["auto_extracted", pattern.replace(":", "")],
                        "importance": default_importance,
                        "extracted_at": datetime.now(timezone.utc).isoformat(),
                    }
                    facts.append(fact)
                    break

        return facts

    def before_compaction(self, conversation: str, context_pct: int = 50) -> Dict:
        """
        Called before context compaction (when >50% threshold is reached).

        Args:
            conversation: Current session conversation text
            context_pct: Current context usage percentage

        Returns:
            Dict with saved_facts_count, file_path, etc.
        """
        logger.info(f"Compaction triggered at {context_pct}% context usage")

        # Extract facts
        facts = self.extract_important_facts(conversation)

        if not facts:
            return {"saved_facts_count": 0, "message": "No important facts to save"}

        # Save facts to MEMORY.md
        self._append_to_memory_md(facts)

        # Log compaction event
        self._log_compaction_event(context_pct, len(facts))

        return {
            "saved_facts_count": len(facts),
            "memory_file": self.memory_index,
            "context_pct": context_pct,
            "message": f"Saved {len(facts)} important facts to MEMORY.md before compaction"
        }

    def _append_to_memory_md(self, facts: List[Dict]):
        """Append facts to MEMORY.md under Pending Items section."""
        if not facts:
            return

        # Read current MEMORY.md
        if os.path.exists(self.memory_index):
            with open(self.memory_index, "r") as f:
                content = f.read()
        else:
            content = "# Claude Code Memory -- Index\n\n"

        # Find or create Pending Items section
        pending_marker = "## Pending Items"
        if pending_marker not in content:
            # Add new pending section
            content += "\n\n## Pending Items\n"

        # Prepare fact entries
        fact_lines = []
        for fact in facts:
            tags_str = ", ".join(fact["tags"])
            importance = fact.get("importance", 5)
            fact_lines.append(f"- **[imp={importance}, {tags_str}]** {fact['content']}")

        # Append to memory file
        fact_section = "\n".join(fact_lines)
        with open(self.memory_index, "a") as f:
            f.write(f"\n\n### Auto-extracted facts ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n")
            f.write(fact_section + "\n")

        logger.info(f"Appended {len(facts)} facts to MEMORY.md")

    def _log_compaction_event(self, context_pct: int, facts_count: int):
        """Log compaction event for tracking."""
        try:
            if os.path.exists(self.compaction_log):
                with open(self.compaction_log) as f:
                    log = json.load(f)
            else:
                log = {"compactions": []}

            log["compactions"].append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "context_pct": context_pct,
                "facts_saved": facts_count
            })

            with open(self.compaction_log, "w") as f:
                json.dump(log, f, indent=2)
        except Exception as e:
            logger.error(f"Error logging compaction: {e}")

    def flush_pending_to_memory(self, pending_items: List[str]) -> Dict:
        """
        Manually flush a list of pending items to MEMORY.md.

        Used when closing a session to save all outstanding items.
        """
        if not pending_items:
            return {"flushed_count": 0}

        facts = [
            {
                "content": item,
                "tags": ["pending_flush"],
                "importance": 6,
                "extracted_at": datetime.now(timezone.utc).isoformat(),
            }
            for item in pending_items
        ]

        self._append_to_memory_md(facts)
        return {"flushed_count": len(facts), "file": self.memory_index}


# Global compactor instance
_compactor: Optional[MemoryCompactor] = None


def get_compactor() -> MemoryCompactor:
    """Get or create global memory compactor."""
    global _compactor
    if _compactor is None:
        _compactor = MemoryCompactor()
    return _compactor


def compact_before_context_cleanup(conversation: str, context_pct: int = 50) -> Dict:
    """
    Called before Claude Code compacts context.

    This should be hooked into settings.json or called manually when needed.
    """
    compactor = get_compactor()
    return compactor.before_compaction(conversation, context_pct)


def flush_pending(items: List[str]) -> Dict:
    """Flush pending items to MEMORY.md."""
    compactor = get_compactor()
    return compactor.flush_pending_to_memory(items)
