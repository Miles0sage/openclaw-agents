"""
OpenClaw Streaming Response Engine
====================================
Real-time job progress streaming via Server-Sent Events (SSE) and WebSocket.
Provides live updates as jobs move through phases, execute tools, and produce output.

Usage:
    monitor = StreamingJobMonitor(job_id="abc123")
    async for event in monitor.stream():
        print(event)  # {"type": "phase_change", "phase": "EXECUTE", ...}

Architecture:
    - EventEngine subscriber for real-time updates
    - SSE generator for HTTP clients (GET /api/jobs/{job_id}/stream)
    - WebSocket push for persistent connections
    - In-memory ring buffer per job (last 100 events)
"""

import asyncio
import json
import logging
import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import AsyncGenerator, Dict, List, Optional, Any

logger = logging.getLogger("openclaw.streaming")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_BUFFER_SIZE = 100        # Max events to buffer per job
STREAM_POLL_INTERVAL = 0.3   # Seconds between polling for new events
STREAM_TIMEOUT = 600         # Max stream duration (10 minutes)
HEARTBEAT_INTERVAL = 15      # SSE heartbeat interval (seconds)


# ---------------------------------------------------------------------------
# StreamEvent — canonical event format for streaming
# ---------------------------------------------------------------------------

@dataclass
class StreamEvent:
    """A single streaming event for a job."""
    event_type: str           # phase_change, tool_call, tool_result, progress, error, complete
    job_id: str
    timestamp: str = ""
    phase: str = ""
    agent: str = ""
    tool_name: str = ""
    tool_input: Optional[Dict] = None
    tool_result: str = ""
    message: str = ""
    progress_pct: float = 0.0
    cost_usd: float = 0.0
    metadata: Optional[Dict] = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_sse(self) -> str:
        """Format as Server-Sent Event string."""
        data = json.dumps(asdict(self), default=str)
        return f"event: {self.event_type}\ndata: {data}\n\n"

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Phase progress mapping
# ---------------------------------------------------------------------------

PHASE_PROGRESS = {
    "RESEARCH": 0.10,
    "PLAN": 0.25,
    "EXECUTE": 0.60,
    "VERIFY": 0.80,
    "DELIVER": 0.95,
    "COMPLETE": 1.00,
}


# ---------------------------------------------------------------------------
# StreamBuffer — thread-safe ring buffer for job events
# ---------------------------------------------------------------------------

class StreamBuffer:
    """Thread-safe ring buffer that stores recent events for a job."""

    def __init__(self, max_size: int = MAX_BUFFER_SIZE):
        self._buffer: deque = deque(maxlen=max_size)
        self._lock = threading.Lock()
        self._event = asyncio.Event()
        self._cursor = 0  # Global sequence number

    def push(self, event: StreamEvent):
        """Add an event to the buffer."""
        with self._lock:
            self._cursor += 1
            self._buffer.append((self._cursor, event))
        # Signal any waiting consumers
        try:
            self._event.set()
        except RuntimeError:
            pass  # No event loop running

    def get_since(self, last_seq: int) -> List[tuple]:
        """Get all events after sequence number last_seq."""
        with self._lock:
            return [(seq, evt) for seq, evt in self._buffer if seq > last_seq]

    @property
    def latest_seq(self) -> int:
        with self._lock:
            return self._cursor

    async def wait_for_new(self, timeout: float = 1.0):
        """Wait for new events (async)."""
        self._event.clear()
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass


# ---------------------------------------------------------------------------
# StreamManager — global manager for all job streams
# ---------------------------------------------------------------------------

class StreamManager:
    """Manages streaming buffers for all active jobs.

    Subscribes to EventEngine to capture job lifecycle events and
    routes them to per-job StreamBuffers.
    """

    def __init__(self):
        self._buffers: Dict[str, StreamBuffer] = {}
        self._lock = threading.Lock()
        self._active_streams: Dict[str, int] = defaultdict(int)  # job_id -> active consumer count
        logger.info("StreamManager initialized")

    def get_buffer(self, job_id: str) -> StreamBuffer:
        """Get or create a buffer for a job."""
        with self._lock:
            if job_id not in self._buffers:
                self._buffers[job_id] = StreamBuffer()
            return self._buffers[job_id]

    def push_event(self, job_id: str, event: StreamEvent):
        """Push an event to a job's stream buffer."""
        buf = self.get_buffer(job_id)
        buf.push(event)
        logger.debug(f"Stream event: job={job_id} type={event.event_type} phase={event.phase}")

    def emit_phase_change(self, job_id: str, phase: str, agent: str = "", message: str = ""):
        """Emit a phase change event."""
        self.push_event(job_id, StreamEvent(
            event_type="phase_change",
            job_id=job_id,
            phase=phase,
            agent=agent,
            message=message or f"Entering {phase} phase",
            progress_pct=PHASE_PROGRESS.get(phase, 0.0),
        ))

    def emit_tool_call(self, job_id: str, tool_name: str, tool_input: dict,
                       phase: str = "", agent: str = ""):
        """Emit a tool execution event."""
        self.push_event(job_id, StreamEvent(
            event_type="tool_call",
            job_id=job_id,
            tool_name=tool_name,
            tool_input=tool_input,
            phase=phase,
            agent=agent,
            message=f"Calling {tool_name}",
        ))

    def emit_tool_result(self, job_id: str, tool_name: str, result: str,
                         phase: str = "", cost_usd: float = 0.0):
        """Emit a tool result event."""
        # Truncate long results for streaming
        truncated = result[:500] + "..." if len(result) > 500 else result
        self.push_event(job_id, StreamEvent(
            event_type="tool_result",
            job_id=job_id,
            tool_name=tool_name,
            tool_result=truncated,
            phase=phase,
            cost_usd=cost_usd,
        ))

    def emit_progress(self, job_id: str, message: str, progress_pct: float = 0.0,
                      cost_usd: float = 0.0):
        """Emit a general progress event."""
        self.push_event(job_id, StreamEvent(
            event_type="progress",
            job_id=job_id,
            message=message,
            progress_pct=progress_pct,
            cost_usd=cost_usd,
        ))

    def emit_error(self, job_id: str, message: str, phase: str = ""):
        """Emit an error event."""
        self.push_event(job_id, StreamEvent(
            event_type="error",
            job_id=job_id,
            message=message,
            phase=phase,
        ))

    def emit_complete(self, job_id: str, message: str = "Job completed",
                      cost_usd: float = 0.0):
        """Emit a job completion event."""
        self.push_event(job_id, StreamEvent(
            event_type="complete",
            job_id=job_id,
            message=message,
            progress_pct=1.0,
            cost_usd=cost_usd,
        ))

    def cleanup_job(self, job_id: str):
        """Remove buffer for a completed job (after all consumers disconnect)."""
        with self._lock:
            if job_id in self._buffers and self._active_streams.get(job_id, 0) <= 0:
                del self._buffers[job_id]
                self._active_streams.pop(job_id, None)
                logger.debug(f"Cleaned up stream buffer for job {job_id}")

    async def stream_job(self, job_id: str) -> AsyncGenerator[str, None]:
        """Async generator that yields SSE events for a job.

        Usage:
            async for sse_line in manager.stream_job("abc123"):
                yield sse_line
        """
        buf = self.get_buffer(job_id)
        last_seq = 0
        start_time = time.monotonic()
        last_heartbeat = time.monotonic()

        with self._lock:
            self._active_streams[job_id] += 1

        try:
            # Send initial connection event
            init_event = StreamEvent(
                event_type="connected",
                job_id=job_id,
                message="Stream connected",
            )
            yield init_event.to_sse()

            while True:
                # Check timeout
                elapsed = time.monotonic() - start_time
                if elapsed > STREAM_TIMEOUT:
                    timeout_event = StreamEvent(
                        event_type="timeout",
                        job_id=job_id,
                        message=f"Stream timeout after {STREAM_TIMEOUT}s",
                    )
                    yield timeout_event.to_sse()
                    break

                # Get new events
                new_events = buf.get_since(last_seq)
                for seq, event in new_events:
                    last_seq = seq
                    yield event.to_sse()

                    # Stop streaming after completion
                    if event.event_type in ("complete", "error"):
                        return

                # Send heartbeat to keep connection alive
                now = time.monotonic()
                if now - last_heartbeat > HEARTBEAT_INTERVAL:
                    yield f": heartbeat {int(elapsed)}s\n\n"
                    last_heartbeat = now

                # Wait for new events
                await buf.wait_for_new(timeout=STREAM_POLL_INTERVAL)

        finally:
            with self._lock:
                self._active_streams[job_id] -= 1

    def register_with_event_engine(self, event_engine):
        """Subscribe to EventEngine events to auto-populate stream buffers."""
        def _on_phase_change(record):
            data = record.get("data", {})
            job_id = data.get("job_id", "")
            if job_id:
                self.emit_phase_change(
                    job_id=job_id,
                    phase=data.get("phase", ""),
                    agent=data.get("agent", ""),
                )

        def _on_tool_called(record):
            data = record.get("data", {})
            job_id = data.get("job_id", "")
            if job_id:
                self.emit_tool_call(
                    job_id=job_id,
                    tool_name=data.get("tool_name", ""),
                    tool_input=data.get("tool_input", {}),
                    phase=data.get("phase", ""),
                    agent=data.get("agent", ""),
                )

        def _on_tool_completed(record):
            data = record.get("data", {})
            job_id = data.get("job_id", "")
            if job_id:
                self.emit_tool_result(
                    job_id=job_id,
                    tool_name=data.get("tool_name", ""),
                    result=data.get("result", "")[:500],
                    phase=data.get("phase", ""),
                    cost_usd=data.get("cost_usd", 0.0),
                )

        def _on_job_completed(record):
            data = record.get("data", {})
            job_id = data.get("job_id", data.get("id", ""))
            if job_id:
                self.emit_complete(
                    job_id=job_id,
                    message=data.get("message", "Job completed"),
                    cost_usd=data.get("total_cost_usd", 0.0),
                )

        def _on_job_failed(record):
            data = record.get("data", {})
            job_id = data.get("job_id", data.get("id", ""))
            if job_id:
                self.emit_error(
                    job_id=job_id,
                    message=data.get("error", "Job failed"),
                    phase=data.get("phase", ""),
                )

        event_engine.subscribe("job.phase_change", _on_phase_change)
        event_engine.subscribe("job.tool_called", _on_tool_called)
        event_engine.subscribe("job.tool_completed", _on_tool_completed)
        event_engine.subscribe("job.completed", _on_job_completed)
        event_engine.subscribe("job.failed", _on_job_failed)
        logger.info("StreamManager registered with EventEngine")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_stream_manager: Optional[StreamManager] = None


def get_stream_manager() -> StreamManager:
    """Get the global StreamManager instance."""
    global _stream_manager
    if _stream_manager is None:
        _stream_manager = StreamManager()
    return _stream_manager


def init_stream_manager(event_engine=None) -> StreamManager:
    """Initialize and optionally wire to EventEngine."""
    mgr = get_stream_manager()
    if event_engine:
        mgr.register_with_event_engine(event_engine)
    return mgr
