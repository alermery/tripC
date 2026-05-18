from datetime import datetime

from backend.app.api.ws import (
    _initial_progress_tool,
    _mark_reply_cancelled,
    _normalize_tool_event,
    _parse_started_at,
)


def test_parse_started_at_normalizes_offset_time():
    parsed = _parse_started_at("2026-05-13T08:00:00+08:00")
    assert isinstance(parsed, datetime)
    assert parsed.isoformat() == "2026-05-13T00:00:00"


def test_mark_reply_cancelled_appends_suffix_once():
    first = _mark_reply_cancelled("hello")
    second = _mark_reply_cancelled(first)
    assert "已停止输出" in first
    assert second == first


def test_planner_stream_has_initial_progress_tool():
    assert _initial_progress_tool("planner") == "planner_prepare"
    assert _initial_progress_tool("weather") is None
    assert _initial_progress_tool("map") is None


def test_normalize_tool_event_accepts_legacy_name():
    assert _normalize_tool_event("rag_kb_retriever") == {
        "name": "rag_kb_retriever",
        "phase": "selected",
        "call_id": "rag_kb_retriever",
    }


def test_normalize_tool_event_accepts_structured_event():
    assert _normalize_tool_event(
        {"name": "route_plan", "phase": "completed", "call_id": "call_1"}
    ) == {
        "name": "route_plan",
        "phase": "completed",
        "call_id": "call_1",
    }
