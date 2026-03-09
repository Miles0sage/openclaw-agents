"""
Append-only journal for durable step logging (Tier 3 Bulletproof).

Each job gets a JSONL file: data/traces/{job_id}.jsonl
Records every phase/tool/error/checkpoint for crash recovery replay.
Complements checkpoints with a full audit trail.
"""

import json
import logging
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("openclaw.journal")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "os.environ.get("OPENCLAW_DATA_DIR", "./data")")
DEFAULT_TRACE_DIR = os.path.join(DATA_DIR, "traces")

EVENT_TYPES = (
    "job_start", "job_end",
    "phase_start", "phase_end",
    "tool_call", "tool_result",
    "checkpoint", "compaction", "stuck_detected", "error",
    "quality_score",
)


@dataclass
class JournalEntry:
    timestamp: str
    job_id: str
    event_type: str
    phase: str = ""
    step_index: int = -1
    data: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), default=str) + "\n"


class StepJournal:
    """Append-only JSONL journal per job. Thread-safe."""

    def __init__(self, trace_dir: str = None):
        self._trace_dir = Path(trace_dir or DEFAULT_TRACE_DIR)
        self._trace_dir.mkdir(parents=True, exist_ok=True)
        self._locks: Dict[str, threading.Lock] = {}
        self._lock_meta = threading.Lock()
        logger.info("StepJournal initialized at %s", self._trace_dir)

    def _path(self, job_id: str) -> Path:
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_id)
        return self._trace_dir / f"{safe_id}.jsonl"

    def _archive_path(self, job_id: str) -> Path:
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_id)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return self._trace_dir / f"{safe_id}.archive.{stamp}.jsonl"

    def _lock(self, job_id: str) -> threading.Lock:
        with self._lock_meta:
            if job_id not in self._locks:
                self._locks[job_id] = threading.Lock()
            return self._locks[job_id]

    def log(
        self,
        job_id: str,
        event_type: str,
        phase: str = "",
        step_index: int = -1,
        data: dict = None,
        duration_ms: float = 0.0,
    ) -> None:
        """Append one JSON line to data/traces/{job_id}.jsonl. Never raises."""
        if data is None:
            data = {}
        if event_type not in EVENT_TYPES:
            logger.warning("Unknown journal event_type=%s", event_type)
        try:
            entry = JournalEntry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                job_id=job_id,
                event_type=event_type,
                phase=phase or "",
                step_index=step_index,
                data=dict(data),
                duration_ms=duration_ms,
            )
            path = self._path(job_id)
            with self._lock(job_id):
                with open(path, "a", encoding="utf-8") as f:
                    f.write(entry.to_jsonl())
        except Exception as e:
            logger.warning("Journal log failed (job_id=%s, event_type=%s): %s", job_id, event_type, e)

    def get_entries(self, job_id: str, event_type: str = None) -> List[JournalEntry]:
        """Read back entries for a job, optionally filtered by event_type."""
        out: List[JournalEntry] = []
        path = self._path(job_id)
        if not path.exists():
            return out
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        e = JournalEntry(
                            timestamp=d.get("timestamp", ""),
                            job_id=d.get("job_id", ""),
                            event_type=d.get("event_type", ""),
                            phase=d.get("phase", ""),
                            step_index=d.get("step_index", -1),
                            data=d.get("data", {}),
                            duration_ms=float(d.get("duration_ms", 0)),
                        )
                        if event_type is None or e.event_type == event_type:
                            out.append(e)
                    except (json.JSONDecodeError, KeyError, TypeError):
                        continue
        except Exception as e:
            logger.warning("Journal get_entries failed (job_id=%s): %s", job_id, e)
        return out

    def get_last_entry(self, job_id: str) -> Optional[JournalEntry]:
        """Return the last journal entry for a job (for crash recovery)."""
        entries = self.get_entries(job_id)
        return entries[-1] if entries else None

    def get_summary(self, job_id: str) -> dict:
        """Return summary: total entries, phases completed, errors, duration, last event."""
        entries = self.get_entries(job_id)
        phases = list({e.phase for e in entries if e.phase})
        errors = [e for e in entries if e.event_type == "error"]
        last = entries[-1] if entries else None
        total_duration = sum(e.duration_ms for e in entries)
        return {
            "job_id": job_id,
            "total_entries": len(entries),
            "phases_seen": phases,
            "error_count": len(errors),
            "total_duration_ms": total_duration,
            "last_event": last.event_type if last else None,
            "last_timestamp": last.timestamp if last else None,
        }

    def clear(self, job_id: str) -> None:
        """Delete journal file for a job (cleanup after retention period)."""
        try:
            path = self._path(job_id)
            if path.exists():
                path.unlink()
        except Exception as e:
            logger.warning("Journal clear failed (job_id=%s): %s", job_id, e)

    def rotate(self, job_id: str, max_entries: int = 10000) -> None:
        """If journal exceeds max_entries, keep last max_entries//2 and archive the rest."""
        entries = self.get_entries(job_id)
        if len(entries) <= max_entries:
            return
        keep_count = max(1, max_entries // 2)
        keep = entries[-keep_count:]
        archived = entries[:-keep_count]
        path = self._path(job_id)
        try:
            with self._lock(job_id):
                archive_path = self._archive_path(job_id)
                with open(archive_path, "w", encoding="utf-8") as archive:
                    for e in archived:
                        archive.write(e.to_jsonl())
                with open(path, "w", encoding="utf-8") as f:
                    for e in keep:
                        f.write(e.to_jsonl())
        except Exception as e:
            logger.warning("Journal rotate failed (job_id=%s): %s", job_id, e)


_journal: Optional[StepJournal] = None


def init_journal(trace_dir: str = None, **kwargs) -> StepJournal:
    global _journal
    _journal = StepJournal(trace_dir=trace_dir or DEFAULT_TRACE_DIR, **kwargs)
    return _journal


def get_journal() -> StepJournal:
    global _journal
    if _journal is None:
        _journal = StepJournal()
    return _journal
