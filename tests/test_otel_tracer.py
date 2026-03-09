"""Tests for otel_tracer.py — structured tracing engine."""
import json
import os
import tempfile
import pytest
from otel_tracer import Span, SpanContext, Tracer, get_tracer, init_tracer


class TestSpan:
    def test_span_creation(self):
        s = Span(trace_id="t1", span_id="s1", operation="test_op")
        assert s.trace_id == "t1"
        assert s.status == "ok"

    def test_span_finish(self):
        s = Span(trace_id="t1", span_id="s1", operation="test_op")
        s.start_time = __import__("time").time()
        s.finish("ok")
        assert s.status == "ok"
        assert s.duration_ms >= 0

    def test_set_attribute(self):
        s = Span(trace_id="t1", span_id="s1", operation="test_op")
        s.set_attribute("key", "value")
        assert s.attributes["key"] == "value"

    def test_add_event(self):
        s = Span(trace_id="t1", span_id="s1", operation="test_op")
        s.add_event("test_event", {"detail": 42})
        assert len(s.events) == 1
        assert s.events[0]["name"] == "test_event"

    def test_to_dict(self):
        s = Span(trace_id="t1", span_id="s1", operation="test_op")
        d = s.to_dict()
        assert d["trace_id"] == "t1"
        assert d["operation"] == "test_op"


class TestTracer:
    def test_span_context_manager(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            tracer = Tracer(export_path=path)
            with tracer.span("test_operation", trace_id="job1") as sp:
                sp.set_attribute("foo", "bar")
            # Check the span was exported
            with open(path) as f:
                lines = f.readlines()
            assert len(lines) >= 1
            data = json.loads(lines[0])
            assert data["operation"] == "test_operation"
            assert data["status"] == "ok"
        finally:
            os.unlink(path)

    def test_span_error(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            tracer = Tracer(export_path=path)
            with pytest.raises(ValueError):
                with tracer.span("failing_op", trace_id="job2") as sp:
                    raise ValueError("test error")
            with open(path) as f:
                data = json.loads(f.readline())
            assert data["status"] == "error"
            assert "ValueError" in str(data["attributes"])
        finally:
            os.unlink(path)

    def test_nested_spans(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            tracer = Tracer(export_path=path)
            with tracer.span("parent", trace_id="job3") as parent:
                with tracer.span("child", trace_id="job3", parent_span_id=parent.span_id) as child:
                    child.set_attribute("step", 1)
            with open(path) as f:
                lines = f.readlines()
            assert len(lines) == 2
            child_data = json.loads(lines[0])
            parent_data = json.loads(lines[1])
            assert child_data["parent_span_id"] == parent_data["span_id"]
        finally:
            os.unlink(path)

    def test_get_recent_traces(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            tracer = Tracer(export_path=path)
            with tracer.span("op1", trace_id="j1"):
                pass
            with tracer.span("op2", trace_id="j2"):
                pass
            traces = tracer.get_recent_traces(limit=5)
            assert len(traces) >= 1
        finally:
            os.unlink(path)

    def test_singleton(self):
        tracer = init_tracer()
        assert get_tracer() is tracer
