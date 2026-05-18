"""旅行规划上下文工具。

负责从数据库提取 planner 相关历史，用于近期偏好摘要、同会话前文拼接和多轮消息恢复。
"""

from __future__ import annotations

import logging
from functools import lru_cache

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select

from backend.app.db import SessionLocal
from backend.app.models.chat_message import ChatMessage
from backend.app.models.user import User

logger = logging.getLogger(__name__)

_PLANNER_AGENT = "planner"
_RECENT_CONTEXT_VERSION = 0
_HISTORY_MESSAGES_VERSION = 0


def invalidate_travel_context_caches() -> None:
    global _RECENT_CONTEXT_VERSION, _HISTORY_MESSAGES_VERSION
    _RECENT_CONTEXT_VERSION += 1
    _HISTORY_MESSAGES_VERSION += 1
    _cached_recent_travel_context.cache_clear()
    _cached_recent_travel_context_by_user_id.cache_clear()
    _cached_planner_history_messages.cache_clear()


def resolve_user_id(username: str) -> int | None:
    name = (username or "").strip()
    if not name:
        return None
    return _resolve_user_id_cached(name)


@lru_cache(maxsize=1024)
def _resolve_user_id_cached(username: str) -> int | None:
    db = SessionLocal()
    try:
        return db.query(User.id).filter(User.username == username).scalar()
    finally:
        db.close()


@lru_cache(maxsize=256)
def _cached_recent_travel_context_by_user_id(
    user_id: int,
    limit_rows: int,
    max_items: int,
    version: int,
) -> str:
    db = SessionLocal()
    try:
        rows = (
            db.execute(
                select(ChatMessage.query)
                .where(
                    ChatMessage.user_id == user_id,
                    ChatMessage.agent == _PLANNER_AGENT,
                )
                .order_by(ChatMessage.created_at.desc())
                .limit(limit_rows)
            )
            .scalars()
            .all()
        )
        snippets: list[str] = []
        seen: set[str] = set()
        for query_text in rows:
            head = (query_text or "").split("\n\n")[0].strip()
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


@lru_cache(maxsize=256)
def _cached_recent_travel_context(username: str, limit_rows: int, max_items: int) -> str:
    uid = resolve_user_id(username)
    if uid is None:
        return ""
    return _cached_recent_travel_context_by_user_id(
        uid,
        limit_rows,
        max_items,
        _RECENT_CONTEXT_VERSION,
    )


def build_recent_travel_context(
    username: str,
    limit_rows: int = 12,
    max_items: int = 6,
    *,
    user_id: int | None = None,
) -> str:
    """构造近期旅行偏好摘要。"""
    if user_id is not None:
        out = _cached_recent_travel_context_by_user_id(
            user_id,
            limit_rows,
            max_items,
            _RECENT_CONTEXT_VERSION,
        )
    else:
        out = _cached_recent_travel_context(username, limit_rows, max_items)
    if not out:
        logger.debug("build_recent_travel_context: no snippets user=%s", username)
    return out


def _first_user_line(raw: str, *, limit: int) -> str:
    """截取用户问题的首段，避免把整段增强上下文再次注入。"""
    return (raw or "").split("\n\n")[0].strip()[:limit]


def build_same_conversation_prompt_block(
    username: str,
    conversation_id: str,
    *,
    max_turns: int = 8,
    max_user_chars: int = 900,
    max_assistant_chars: int = 1200,
) -> str:
    """构造同一会话的最近若干轮前文，用于指代消解。"""
    cid = (conversation_id or "").strip()
    uid = resolve_user_id(username)
    if not cid or uid is None:
        return ""
    db = SessionLocal()
    try:
        rows = (
            db.execute(
                select(ChatMessage.query, ChatMessage.reply)
                .where(
                    ChatMessage.user_id == uid,
                    ChatMessage.agent == _PLANNER_AGENT,
                    ChatMessage.conversation_id == cid,
                )
                .order_by(ChatMessage.created_at.desc())
                .limit(max_turns)
            )
            .all()
        )
        if not rows:
            return ""
        rows = list(reversed(rows))
        lines: list[str] = []
        for query_text, reply_text in rows:
            user_query = _first_user_line(query_text or "", limit=max_user_chars)
            reply = (reply_text or "").strip().replace("\r\n", "\n")[:max_assistant_chars]
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


@lru_cache(maxsize=512)
def _cached_planner_history_messages(
    user_id: int,
    conversation_id: str,
    max_turns: int,
    max_user_chars: int,
    max_assistant_chars: int,
    version: int,
) -> tuple[tuple[str, str], ...]:
    db = SessionLocal()
    try:
        rows = (
            db.execute(
                select(ChatMessage.query, ChatMessage.reply)
                .where(
                    ChatMessage.user_id == user_id,
                    ChatMessage.agent == _PLANNER_AGENT,
                    ChatMessage.conversation_id == conversation_id,
                )
                .order_by(ChatMessage.created_at.desc())
                .limit(max_turns)
            )
            .all()
        )
        if not rows:
            return ()
        rows = list(reversed(rows))
        out: list[tuple[str, str]] = []
        for query_text, reply_text in rows:
            user_query = _first_user_line(query_text or "", limit=max_user_chars)
            reply = (reply_text or "").strip()[:max_assistant_chars]
            if not user_query:
                continue
            out.append((user_query, reply))
        return tuple(out)
    finally:
        db.close()


def build_planner_history_messages(
    username: str,
    conversation_id: str,
    *,
    max_turns: int = 3,
    max_user_chars: int = 900,
    max_assistant_chars: int = 2200,
    user_id: int | None = None,
) -> list[HumanMessage | AIMessage]:
    """构造传给 Agent 的 LangChain 多轮消息列表。"""
    cid = (conversation_id or "").strip()
    uid = user_id if user_id is not None else resolve_user_id(username)
    if not cid or uid is None:
        return []
    pairs = _cached_planner_history_messages(
        uid,
        cid,
        max_turns,
        max_user_chars,
        max_assistant_chars,
        _HISTORY_MESSAGES_VERSION,
    )
    out: list[HumanMessage | AIMessage] = []
    for user_query, reply in pairs:
        out.append(HumanMessage(content=user_query))
        if reply:
            out.append(AIMessage(content=reply))
    return out
