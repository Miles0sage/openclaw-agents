"""
Real-Time Job Monitoring Module for OpenClaw Agency System

Provides live job state tracking, event subscription, and WebSocket management
for real-time monitoring of the 5-phase pipeline:
  RESEARCH → PLAN → EXECUTE → VERIFY → DELIVER

Components:
  - JobMonitor: Tracks job state, subscribes to events, maintains event log
  - WebSocketManager: Manages per-job WebSocket connections and broadcast
  - Helper functions: Phase timeline, singleton accessors

Usage:
    from gateway_monitoring import get_job_monitor, get_ws_manager

    monitor = get_job_monitor()
    state = monitor.get_live_state("job_123")

    ws_mgr = get_ws_manager()
    ws_mgr.connect("job_123", websocket)
    ws_mgr.broadcast("job_123", {"phase": "execute", "progress": 50})
"""

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Callable, Any

from event_engine import get_event_engine

logger = logging.getLogger("gateway_monitoring")

# Phase progress mapping: phase name -> (start_pct, end_pct)
PHASE_PROGRESS = {
    "research": (0, 20),
    "plan": (20, 40),
    "execute": (40, 70),
    "verify": (70, 90),
    "deliver": (90, 100),
    "completed": (100, 100),
}

# Auto-prune completed jobs older than this threshold
PRUNE_THRESHOLD_SECONDS = 3600  # 1 hour

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "./data")
JOBS_DIR = os.path.join(DATA_DIR, "jobs")


# ---------------------------------------------------------------------------
# JobMonitor Class
# ---------------------------------------------------------------------------


class JobMonitor:
    """
    Tracks live state of all active jobs in the OpenClaw pipeline.

    Subscribes to event_engine events and maintains _live_state with:
    - phase: current pipeline phase
    - progress_pct: calculated progress percentage
    - active_tools: list of tools currently running
    - tokens_used: total tokens consumed
    - cost_usd: total cost in USD
    - last_event: timestamp of most recent event
    - events_log: list of all events for this job
    """

    def __init__(self) -> None:
        """Initialize monitor and subscribe to event_engine."""
        self._live_state: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._last_prune_time = time.time()

        # Subscribe to relevant events
        engine = get_event_engine()
        engine.subscribe("job.created", self._on_job_created)
        engine.subscribe("job.completed", self._on_job_completed)
        engine.subscribe("job.failed", self._on_job_failed)
        engine.subscribe("job.phase_started", self._on_phase_started)
        engine.subscribe("job.phase_completed", self._on_phase_completed)
        engine.subscribe("job.tool_called", self._on_tool_called)
        engine.subscribe("job.tool_completed", self._on_tool_completed)

        logger.info("JobMonitor initialized and subscribed to event engine")

    def _initialize_job_state(self, job_id: str) -> Dict[str, Any]:
        """Create initial state dict for a new job."""
        return {
            "job_id": job_id,
            "phase": "research",
            "progress_pct": 0,
            "active_tools": [],
            "tokens_used": 0,
            "cost_usd": 0.0,
            "last_event": datetime.now(timezone.utc).isoformat(),
            "events_log": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "status": "running",  # running, completed, failed
        }

    def _on_job_created(self, record: Dict[str, Any]) -> None:
        """Handle job.created event."""
        data = record.get("data", {})
        job_id = data.get("job_id")
        if not job_id:
            return

        with self._lock:
            if job_id not in self._live_state:
                self._live_state[job_id] = self._initialize_job_state(job_id)

            state = self._live_state[job_id]
            state["last_event"] = datetime.now(timezone.utc).isoformat()
            state["events_log"].append({
                "event": "job.created",
                "timestamp": state["last_event"],
                "data": data,
            })

            logger.debug(f"Job {job_id} created")

    def _on_job_completed(self, record: Dict[str, Any]) -> None:
        """Handle job.completed event."""
        data = record.get("data", {})
        job_id = data.get("job_id")
        if not job_id:
            return

        with self._lock:
            if job_id not in self._live_state:
                self._live_state[job_id] = self._initialize_job_state(job_id)

            state = self._live_state[job_id]
            state["phase"] = "completed"
            state["progress_pct"] = 100
            state["status"] = "completed"
            state["completed_at"] = datetime.now(timezone.utc).isoformat()
            state["last_event"] = state["completed_at"]
            state["events_log"].append({
                "event": "job.completed",
                "timestamp": state["completed_at"],
                "data": data,
            })

            if "tokens_used" in data:
                state["tokens_used"] = data["tokens_used"]
            if "cost_usd" in data:
                state["cost_usd"] = data["cost_usd"]

            logger.debug(f"Job {job_id} completed")

    def _on_job_failed(self, record: Dict[str, Any]) -> None:
        """Handle job.failed event."""
        data = record.get("data", {})
        job_id = data.get("job_id")
        if not job_id:
            return

        with self._lock:
            if job_id not in self._live_state:
                self._live_state[job_id] = self._initialize_job_state(job_id)

            state = self._live_state[job_id]
            state["status"] = "failed"
            state["completed_at"] = datetime.now(timezone.utc).isoformat()
            state["last_event"] = state["completed_at"]
            state["events_log"].append({
                "event": "job.failed",
                "timestamp": state["completed_at"],
                "data": data,
            })

            logger.warning(f"Job {job_id} failed: {data.get('reason', 'unknown')}")

    def _on_phase_started(self, record: Dict[str, Any]) -> None:
        """Handle job.phase_started event."""
        data = record.get("data", {})
        job_id = data.get("job_id")
        phase = data.get("phase", "").lower()
        if not job_id or not phase:
            return

        with self._lock:
            if job_id not in self._live_state:
                self._live_state[job_id] = self._initialize_job_state(job_id)

            state = self._live_state[job_id]
            state["phase"] = phase
            state["last_event"] = datetime.now(timezone.utc).isoformat()

            # Update progress to phase start percentage
            start_pct, _ = PHASE_PROGRESS.get(phase, (0, 0))
            state["progress_pct"] = start_pct

            state["events_log"].append({
                "event": "job.phase_started",
                "phase": phase,
                "timestamp": state["last_event"],
            })

            logger.debug(f"Job {job_id} phase started: {phase}")

    def _on_phase_completed(self, record: Dict[str, Any]) -> None:
        """Handle job.phase_completed event."""
        data = record.get("data", {})
        job_id = data.get("job_id")
        phase = data.get("phase", "").lower()
        if not job_id or not phase:
            return

        with self._lock:
            if job_id not in self._live_state:
                self._live_state[job_id] = self._initialize_job_state(job_id)

            state = self._live_state[job_id]
            state["last_event"] = datetime.now(timezone.utc).isoformat()

            # Update progress to phase end percentage
            _, end_pct = PHASE_PROGRESS.get(phase, (0, 0))
            state["progress_pct"] = end_pct

            state["events_log"].append({
                "event": "job.phase_completed",
                "phase": phase,
                "timestamp": state["last_event"],
            })

            logger.debug(f"Job {job_id} phase completed: {phase}")

    def _on_tool_called(self, record: Dict[str, Any]) -> None:
        """Handle job.tool_called event."""
        data = record.get("data", {})
        job_id = data.get("job_id")
        tool_name = data.get("tool_name")
        if not job_id or not tool_name:
            return

        with self._lock:
            if job_id not in self._live_state:
                self._live_state[job_id] = self._initialize_job_state(job_id)

            state = self._live_state[job_id]
            if tool_name not in state["active_tools"]:
                state["active_tools"].append(tool_name)

            state["last_event"] = datetime.now(timezone.utc).isoformat()
            state["events_log"].append({
                "event": "job.tool_called",
                "tool_name": tool_name,
                "timestamp": state["last_event"],
            })

    def _on_tool_completed(self, record: Dict[str, Any]) -> None:
        """Handle job.tool_completed event."""
        data = record.get("data", {})
        job_id = data.get("job_id")
        tool_name = data.get("tool_name")
        if not job_id or not tool_name:
            return

        with self._lock:
            if job_id not in self._live_state:
                self._live_state[job_id] = self._initialize_job_state(job_id)

            state = self._live_state[job_id]
            if tool_name in state["active_tools"]:
                state["active_tools"].remove(tool_name)

            state["last_event"] = datetime.now(timezone.utc).isoformat()

            # Track tokens if provided
            if "tokens_used" in data:
                state["tokens_used"] += data.get("tokens_used", 0)

            # Track cost if provided
            if "cost_usd" in data:
                state["cost_usd"] += data.get("cost_usd", 0.0)

            state["events_log"].append({
                "event": "job.tool_completed",
                "tool_name": tool_name,
                "tokens_used": data.get("tokens_used", 0),
                "cost_usd": data.get("cost_usd", 0.0),
                "timestamp": state["last_event"],
            })

    def _prune_old_jobs(self) -> None:
        """Remove completed jobs older than PRUNE_THRESHOLD_SECONDS."""
        now = time.time()
        if now - self._last_prune_time < 60:  # Prune at most every 60 seconds
            return

        self._last_prune_time = now
        current_time = datetime.now(timezone.utc)
        threshold_time = current_time - timedelta(seconds=PRUNE_THRESHOLD_SECONDS)

        with self._lock:
            to_remove = []
            for job_id, state in self._live_state.items():
                if state.get("status") == "completed" or state.get("status") == "failed":
                    completed_at_str = state.get("completed_at")
                    if completed_at_str:
                        try:
                            completed_at = datetime.fromisoformat(completed_at_str)
                            if completed_at < threshold_time:
                                to_remove.append(job_id)
                        except ValueError:
                            pass

            for job_id in to_remove:
                del self._live_state[job_id]
                logger.debug(f"Pruned completed job {job_id}")

    def get_live_state(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get current live state for a specific job.

        Returns dict with keys: job_id, phase, progress_pct, active_tools,
        tokens_used, cost_usd, last_event, events_log, created_at,
        completed_at, status
        """
        self._prune_old_jobs()

        with self._lock:
            state = self._live_state.get(job_id)
            if state:
                # Return a copy to prevent external modification
                return dict(state)
            return None

    def get_all_live_states(self) -> Dict[str, Dict[str, Any]]:
        """Get states for all currently active jobs."""
        self._prune_old_jobs()

        with self._lock:
            # Return copies to prevent external modification
            return {
                job_id: dict(state)
                for job_id, state in self._live_state.items()
            }

    def get_job_count(self) -> Dict[str, int]:
        """Get count of jobs by status."""
        self._prune_old_jobs()

        with self._lock:
            counts = {
                "running": 0,
                "completed": 0,
                "failed": 0,
                "total": len(self._live_state),
            }
            for state in self._live_state.values():
                status = state.get("status", "running")
                counts[status] = counts.get(status, 0) + 1
            return counts


# ---------------------------------------------------------------------------
# WebSocketManager Class
# ---------------------------------------------------------------------------


class WebSocketManager:
    """
    Manages WebSocket connections for real-time job monitoring.

    Maintains per-job-id connection lists and broadcasts state updates
    to all connected clients watching that job.
    """

    def __init__(self) -> None:
        """Initialize WebSocket manager."""
        self._connections: Dict[str, List[Any]] = {}
        self._lock = threading.RLock()
        logger.info("WebSocketManager initialized")

    def connect(self, job_id: str, websocket: Any) -> None:
        """Register a WebSocket connection for a job."""
        with self._lock:
            if job_id not in self._connections:
                self._connections[job_id] = []
            self._connections[job_id].append(websocket)
            logger.debug(f"WebSocket connected to job {job_id}")

    def disconnect(self, job_id: str, websocket: Any) -> None:
        """Unregister a WebSocket connection."""
        with self._lock:
            if job_id in self._connections:
                try:
                    self._connections[job_id].remove(websocket)
                    if not self._connections[job_id]:
                        del self._connections[job_id]
                    logger.debug(f"WebSocket disconnected from job {job_id}")
                except ValueError:
                    pass

    async def broadcast(self, job_id: str, data: Dict[str, Any]) -> None:
        """
        Broadcast a message to all WebSockets watching a job.

        Args:
            job_id: Job ID to broadcast to
            data: Message data (will be JSON-encoded)
        """
        with self._lock:
            connections = self._connections.get(job_id, [])
            connections_copy = list(connections)

        # Send to all connections asynchronously
        for websocket in connections_copy:
            try:
                await websocket.send_json(data)
            except Exception as e:
                logger.warning(f"Failed to send message to WebSocket: {e}")
                # Attempt to disconnect on failure
                self.disconnect(job_id, websocket)

    def get_connection_count(self, job_id: str) -> int:
        """Get number of active WebSocket connections for a job."""
        with self._lock:
            return len(self._connections.get(job_id, []))

    def get_all_connections_count(self) -> int:
        """Get total number of active WebSocket connections."""
        with self._lock:
            return sum(len(conns) for conns in self._connections.values())


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def get_job_phases_timeline(job_id: str) -> List[Dict[str, Any]]:
    """
    Extract phase start/end timeline from job's events log.

    Returns list of dicts with keys: phase, started_at, completed_at, duration_sec
    """
    monitor = get_job_monitor()
    state = monitor.get_live_state(job_id)

    if not state:
        return []

    events_log = state.get("events_log", [])
    timeline = {}

    for event in events_log:
        event_type = event.get("event")
        phase = event.get("phase")
        timestamp = event.get("timestamp")

        if not phase or not timestamp:
            continue

        if phase not in timeline:
            timeline[phase] = {"phase": phase, "started_at": None, "completed_at": None}

        if event_type == "job.phase_started":
            timeline[phase]["started_at"] = timestamp
        elif event_type == "job.phase_completed":
            timeline[phase]["completed_at"] = timestamp

    # Calculate durations
    result = []
    for phase_data in timeline.values():
        if phase_data["started_at"] and phase_data["completed_at"]:
            try:
                start = datetime.fromisoformat(phase_data["started_at"])
                end = datetime.fromisoformat(phase_data["completed_at"])
                duration = (end - start).total_seconds()
                phase_data["duration_sec"] = round(duration, 2)
            except ValueError:
                phase_data["duration_sec"] = None
        result.append(phase_data)

    return sorted(result, key=lambda x: x.get("started_at") or "")


# ---------------------------------------------------------------------------
# Singleton Accessors
# ---------------------------------------------------------------------------

_job_monitor_instance: Optional[JobMonitor] = None
_ws_manager_instance: Optional[WebSocketManager] = None
_singleton_lock = threading.Lock()


def get_job_monitor() -> JobMonitor:
    """Get or create the JobMonitor singleton."""
    global _job_monitor_instance
    if _job_monitor_instance is None:
        with _singleton_lock:
            if _job_monitor_instance is None:
                _job_monitor_instance = JobMonitor()
    return _job_monitor_instance


def get_ws_manager() -> WebSocketManager:
    """Get or create the WebSocketManager singleton."""
    global _ws_manager_instance
    if _ws_manager_instance is None:
        with _singleton_lock:
            if _ws_manager_instance is None:
                _ws_manager_instance = WebSocketManager()
    return _ws_manager_instance
