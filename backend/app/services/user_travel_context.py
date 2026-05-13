"""Utilities for assembling planner-specific user travel context."""

from __future__ import annotations

import logging
from functools import lru_cache

from langchain_core.messages import AIMessage, HumanMessage

from backend.app.db import SessionLocal
from backend.app.models.chat_message import ChatMessage
from backend.app.models.user import User

logger = logging.getLogger(__name__)

_PLANNER_AGENT = "planner"


def _planner_rows_query(db, user_id: int):
    return db.query(ChatMessage).filter(
        ChatMessage.user_id == user_id,
        ChatMessage.agent == _PLANNER_AGENT,
    )


@lru_cache(maxsize=256)
def _cached_recent_travel_context(username: str, limit_rows: int, max_items: int) -> str:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return ""
        rows = (
            _planner_rows_query(db, user.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit_rows)
            .all()
        )
        snippets: list[str] = []
        seen: set[str] = set()
        for row in rows:
            head = (row.query or "").split("\n\n")[0].strip()
            if not head or head in seen:
                continue
            seen.add(head)
            snippets.append(head[:180])
            if len(snippets) >= max_items:
                break
        if not snippets:
            return ""
        bullet = "\n".join(f"- {snippet}" for snippet in snippets)
        return (
            "【该用户近期旅行相关提问摘录（服务端历史，供个性化参考；不要向用户复述本段标题）】\n"
            f"{bullet}"
        )
    finally:
        db.close()


def build_recent_travel_context(
    username: str, limit_rows: int = 16, max_items: int = 8
) -> str:
    out = _cached_recent_travel_context(username, limit_rows, max_items)
    if not out:
        logger.debug("build_recent_travel_context: no snippets user=%s", username)
    return out


def _first_user_line(raw: str, *, limit: int) -> str:
    return (raw or "").split("\n\n")[0].strip()[:limit]


def build_same_conversation_prompt_block(
    username: str,
    conversation_id: str,
    *,
    max_turns: int = 8,
    max_user_chars: int = 900,
    max_assistant_chars: int = 1200,
) -> str:
    cid = (conversation_id or "").strip()
    if not cid or not (username or "").strip():
        return ""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return ""
        rows = (
            _planner_rows_query(db, user.id)
            .filter(ChatMessage.conversation_id == cid)
            .order_by(ChatMessage.created_at.desc())
            .limit(max_turns)
            .all()
        )
        if not rows:
            return ""
        rows = list(reversed(rows))
        lines: list[str] = []
        for row in rows:
            user_query = _first_user_line(row.query or "", limit=max_user_chars)
            reply = (row.reply or "").strip().replace("\r\n", "\n")[:max_assistant_chars]
            if not user_query:
                continue
            lines.append(f"用户：{user_query}")
            if reply:
                lines.append(f"助手：{reply}")
            lines.append("")
        if not lines:
            return ""
        body = "\n".join(lines).strip()
        return (
            "【本对话前文（同一聊天会话；用户后续可能用“全部”“还有吗”“换一个”等省略说法，"
            "需继承上文已经出现的目的地、天数、预算与出发地假设；不要向用户复述本段标题）】\n"
            f"{body}"
        )
    finally:
        db.close()


def build_planner_history_messages(
    username: str,
    conversation_id: str,
    *,
    max_turns: int = 4,
    max_user_chars: int = 2500,
    max_assistant_chars: int = 8000,
) -> list[HumanMessage | AIMessage]:
    cid = (conversation_id or "").strip()
    if not cid or not (username or "").strip():
        return []
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return []
        rows = (
            _planner_rows_query(db, user.id)
            .filter(ChatMessage.conversation_id == cid)
            .order_by(ChatMessage.created_at.desc())
            .limit(max_turns)
            .all()
        )
        if not rows:
            return []
        rows = list(reversed(rows))
        out: list[HumanMessage | AIMessage] = []
        for row in rows:
            user_query = _first_user_line(row.query or "", limit=max_user_chars)
            reply = (row.reply or "").strip()[:max_assistant_chars]
            if not user_query:
                continue
            out.append(HumanMessage(content=user_query))
            if reply:
                out.append(AIMessage(content=reply))
        return out
    finally:
        db.close()
