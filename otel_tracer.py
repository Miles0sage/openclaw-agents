"""
OpenClaw Observability / Tracing Engine
=========================================
Structured tracing for every job execution. Produces OpenTelemetry-compatible
span data without requiring external dependencies.

Usage:
    tracer = get_tracer()
    with tracer.span("phase_execute", job_id="abc", phase="PLAN") as span:
        span.set_attribute("agent", "coder_agent")
        ... do work ...
        span.set_attribute("tool_count", 5)

Architecture:
    - Zero external dependencies (JSON file exporter by default)
    - OpenTelemetry-compatible span format (can export to Jaeger/Zipkin later)
    - Hierarchical spans (job -> phase -> tool_call)
    - Query API for trace analysis
    - Automatic cleanup of old traces
"""

import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger("openclaw.tracer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")
TRACES_DIR = os.path.join(DATA_DIR, "traces")
TRACES_LOG = os.path.join(TRACES_DIR, "traces.jsonl")
MAX_TRACE_AGE_DAYS = 7
MAX_ATTRIBUTES = 50


# ---------------------------------------------------------------------------
# Span Model
# ---------------------------------------------------------------------------

@dataclass
class Span:
    """A single trace span representing a unit of work."""
    trace_id: str              # Groups all spans for one job
    span_id: str               # Unique ID for this span
    parent_span_id: str = ""   # Parent span (empty = root)
    operation: str = ""        # e.g., "phase_execute", "tool_call", "model_call"
    start_time: float = 0.0    # Unix timestamp (monotonic)
    end_time: float = 0.0
    duration_ms: float = 0.0
    status: str = "ok"         # ok, error
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)

    def set_attribute(self, key: str, value: Any):
        """Set a span attribute (key-value metadata)."""
        if len(self.attributes) < MAX_ATTRIBUTES:
            self.attributes[key] = value

    def add_event(self, name: str, attributes: Optional[Dict] = None):
        """Add a timestamped event to this span."""
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })

    def finish(self, status: str = "ok"):
        """Mark span as finished."""
        self.end_time = time.time()
        self.duration_ms = round((self.end_time - self.start_time) * 1000, 2)
        self.status = status

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "operation": self.operation,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events,
        }


# ---------------------------------------------------------------------------
# SpanContext — used with context manager
# ---------------------------------------------------------------------------

class SpanContext:
    """Context manager wrapper around a Span for use with `with` blocks."""

    def __init__(self, span: Span, tracer: 'Tracer'):
        self._span = span
        self._tracer = tracer

    def set_attribute(self, key: str, value: Any):
        self._span.set_attribute(key, value)

    def add_event(self, name: str, attributes: Optional[Dict] = None):
        self._span.add_event(name, attributes)

    @property
    def span_id(self) -> str:
        return self._span.span_id

    @property
    def trace_id(self) -> str:
        return self._span.trace_id

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        status = "error" if exc_type else "ok"
        if exc_type:
            self._span.set_attribute("error.type", str(exc_type.__name__))
            self._span.set_attribute("error.message", str(exc_val)[:500])
        self._span.finish(status)
        self._tracer._record_span(self._span)
        return False  # Don't suppress exceptions


# ---------------------------------------------------------------------------
# Tracer — main tracing engine
# ---------------------------------------------------------------------------

class Tracer:
    """Structured tracing engine for OpenClaw jobs.

    Creates hierarchical spans that track job execution:
    - Root span: entire job (trace_id = job_id)
    - Child spans: phases (RESEARCH, PLAN, EXECUTE, VERIFY, DELIVER)
    - Grandchild spans: tool calls, model calls
    """

    def __init__(self, export_path: str = TRACES_LOG):
        self._export_path = export_path
        self._lock = threading.Lock()
        self._active_spans: Dict[str, Span] = {}  # span_id -> Span
        self._trace_roots: Dict[str, str] = {}    # trace_id -> root span_id

        # Ensure traces directory exists
        Path(self._export_path).parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Tracer initialized (export: {self._export_path})")

    def span(self, operation: str, trace_id: str = "", parent_span_id: str = "",
             **attributes) -> SpanContext:
        """Create a new span.

        Args:
            operation: Name of the operation (e.g., "phase_execute", "tool_call")
            trace_id: Trace ID (usually job_id). Auto-generated if empty.
            parent_span_id: Parent span ID for nesting.
            **attributes: Initial span attributes.

        Returns:
            SpanContext for use in `with` blocks.
        """
        span = Span(
            trace_id=trace_id or str(uuid.uuid4()),
            span_id=str(uuid.uuid4())[:16],
            parent_span_id=parent_span_id,
            operation=operation,
            start_time=time.time(),
            attributes=dict(attributes),
        )

        with self._lock:
            self._active_spans[span.span_id] = span
            if not parent_span_id:
                self._trace_roots[span.trace_id] = span.span_id

        return SpanContext(span, self)

    def _record_span(self, span: Span):
        """Write completed span to log file."""
        with self._lock:
            self._active_spans.pop(span.span_id, None)

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **span.to_dict(),
        }

        try:
            with open(self._export_path, "a") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except Exception as e:
            logger.error(f"Failed to write span: {e}")

    def get_trace(self, trace_id: str) -> List[dict]:
        """Retrieve all spans for a trace (job).

        Reads from the log file and filters by trace_id.
        Returns spans sorted by start_time.
        """
        spans = []
        log_path = Path(self._export_path)
        if not log_path.exists():
            return spans

        try:
            with open(log_path, "r") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        if record.get("trace_id") == trace_id:
                            spans.append(record)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Error reading traces: {e}")

        return sorted(spans, key=lambda s: s.get("start_time", 0))

    def get_trace_summary(self, trace_id: str) -> dict:
        """Get a high-level summary of a trace."""
        spans = self.get_trace(trace_id)
        if not spans:
            return {"trace_id": trace_id, "spans": 0}

        total_duration = 0
        phases = []
        tools = []
        errors = []

        for s in spans:
            duration = s.get("duration_ms", 0)
            total_duration = max(total_duration, duration)
            op = s.get("operation", "")

            if "phase" in op:
                phases.append({
                    "phase": s.get("attributes", {}).get("phase", op),
                    "duration_ms": duration,
                    "status": s.get("status", "ok"),
                })
            elif "tool" in op:
                tools.append({
                    "tool": s.get("attributes", {}).get("tool_name", op),
                    "duration_ms": duration,
                    "status": s.get("status", "ok"),
                })
            if s.get("status") == "error":
                errors.append({
                    "operation": op,
                    "error": s.get("attributes", {}).get("error.message", "unknown"),
                })

        return {
            "trace_id": trace_id,
            "total_spans": len(spans),
            "total_duration_ms": total_duration,
            "phases": phases,
            "tool_calls": len(tools),
            "tools": tools[:20],  # Cap for response size
            "errors": errors,
            "agent": spans[0].get("attributes", {}).get("agent", "unknown") if spans else "unknown",
        }

    def get_recent_traces(self, limit: int = 20) -> List[dict]:
        """Get summaries of recent traces."""
        log_path = Path(self._export_path)
        if not log_path.exists():
            return []

        # Collect unique trace IDs from recent spans
        trace_ids = []
        seen = set()
        try:
            with open(log_path, "r") as f:
                lines = f.readlines()
            # Read backwards for most recent
            for line in reversed(lines):
                try:
                    record = json.loads(line)
                    tid = record.get("trace_id", "")
                    if tid and tid not in seen:
                        seen.add(tid)
                        trace_ids.append(tid)
                        if len(trace_ids) >= limit:
                            break
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            logger.error(f"Error reading traces: {e}")

        return [self.get_trace_summary(tid) for tid in trace_ids]

    def cleanup_old_traces(self, max_age_days: int = MAX_TRACE_AGE_DAYS):
        """Remove traces older than max_age_days."""
        log_path = Path(self._export_path)
        if not log_path.exists():
            return 0

        cutoff = time.time() - (max_age_days * 86400)
        kept = []
        removed = 0

        try:
            with open(log_path, "r") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        if record.get("start_time", 0) >= cutoff:
                            kept.append(line)
                        else:
                            removed += 1
                    except json.JSONDecodeError:
                        continue

            if removed > 0:
                with open(log_path, "w") as f:
                    f.writelines(kept)
                logger.info(f"Cleaned up {removed} old trace spans")
        except Exception as e:
            logger.error(f"Error cleaning traces: {e}")

        return removed


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_tracer: Optional[Tracer] = None


def get_tracer() -> Tracer:
    """Get the global Tracer instance."""
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer


def init_tracer(export_path: Optional[str] = None) -> Tracer:
    """Initialize the global Tracer."""
    global _tracer
    _tracer = Tracer(export_path=export_path or TRACES_LOG)
    return _tracer
