"""Tests for streaming.py — SSE event streaming for jobs."""
import pytest
from streaming import StreamEvent, StreamBuffer, StreamManager, get_stream_manager, init_stream_manager


class TestStreamEvent:
    def test_to_sse_basic(self):
        e = StreamEvent(event_type="progress", job_id="j1", message="hello")
        sse = e.to_sse()
        assert "event: progress" in sse
        assert '"job_id"' in sse
        assert sse.endswith("\n\n")

    def test_to_sse_with_phase(self):
        e = StreamEvent(event_type="phase_change", job_id="j1", phase="execute", agent="coder")
        sse = e.to_sse()
        assert "execute" in sse
        assert "coder" in sse


class TestStreamBuffer:
    def test_push_and_get(self):
        buf = StreamBuffer(max_size=10)
        e1 = StreamEvent(event_type="progress", job_id="j1", message="one")
        e2 = StreamEvent(event_type="progress", job_id="j1", message="two")
        buf.push(e1)
        buf.push(e2)
        events = buf.get_since(0)
        assert len(events) == 2
        # get_since returns (seq, event) tuples
        assert events[0][1].message == "one"

    def test_buffer_overflow(self):
        buf = StreamBuffer(max_size=3)
        for i in range(5):
            buf.push(StreamEvent(event_type="progress", job_id="j1", message=f"msg{i}"))
        events = buf.get_since(0)
        assert len(events) <= 3

    def test_get_events_since(self):
        buf = StreamBuffer(max_size=10)
        for i in range(5):
            buf.push(StreamEvent(event_type="progress", job_id="j1", message=f"msg{i}"))
        events = buf.get_since(3)
        assert len(events) == 2

    def test_latest_seq(self):
        buf = StreamBuffer(max_size=10)
        assert buf.latest_seq == 0
        buf.push(StreamEvent(event_type="progress", job_id="j1", message="a"))
        assert buf.latest_seq == 1


class TestStreamManager:
    def test_emit_phase_change(self):
        mgr = StreamManager()
        mgr.emit_phase_change("j1", "research", agent="coder", message="Starting research")
        buf = mgr.get_buffer("j1")
        events = buf.get_since(0)
        assert len(events) == 1
        assert events[0][1].event_type == "phase_change"
        assert events[0][1].phase == "research"

    def test_emit_tool_call(self):
        mgr = StreamManager()
        mgr.emit_tool_call("j1", "file_read", {"path": "/foo"}, phase="execute")
        buf = mgr.get_buffer("j1")
        events = buf.get_since(0)
        assert events[0][1].tool_name == "file_read"

    def test_emit_complete(self):
        mgr = StreamManager()
        mgr.emit_complete("j1", message="done", cost_usd=0.05)
        buf = mgr.get_buffer("j1")
        events = buf.get_since(0)
        assert events[0][1].event_type == "complete"
        assert events[0][1].progress_pct == 1.0

    def test_cleanup_job(self):
        mgr = StreamManager()
        mgr.emit_progress("j1", "test")
        assert "j1" in mgr._buffers
        mgr.cleanup_job("j1")
        assert "j1" not in mgr._buffers

    def test_singleton(self):
        mgr = init_stream_manager()
        assert get_stream_manager() is mgr
