from backend.app.services import user_travel_context as utc


def test_build_recent_travel_context_uses_cache(monkeypatch):
    calls = {"count": 0}

    def fake_cached(username, limit_rows, max_items):
        calls["count"] += 1
        return f"{username}:{limit_rows}:{max_items}"

    monkeypatch.setattr(utc, "_cached_recent_travel_context", fake_cached)
    result = utc.build_recent_travel_context("alice", 4, 2)
    assert result == "alice:4:2"
    assert calls["count"] == 1
