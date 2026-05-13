from datetime import datetime

from backend.app.api.ws import _mark_reply_cancelled, _parse_started_at


def test_parse_started_at_normalizes_offset_time():
    parsed = _parse_started_at("2026-05-13T08:00:00+08:00")
    assert isinstance(parsed, datetime)
    assert parsed.isoformat() == "2026-05-13T00:00:00"


def test_mark_reply_cancelled_appends_suffix_once():
    first = _mark_reply_cancelled("hello")
    second = _mark_reply_cancelled(first)
    assert "已停止输出" in first
    assert second == first
