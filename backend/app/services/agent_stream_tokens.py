# LangGraph create_agent：从 model 节点取流式正文；伪流式为按批合并多段小增量再推送；
# 同时从 model 的 tool_call_chunks / tools 节点的 ToolMessage 提取工具名，供前端「正在使用某工具」提示。

from __future__ import annotations

import threading
from typing import Any, Iterator

from langchain_core.messages import AIMessageChunk, ToolMessage


def aimessage_chunk_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return str(content)


def _tool_names_from_aimessage_chunk(tok: AIMessageChunk) -> list[str]:
    names: list[str] = []
    tcc = getattr(tok, "tool_call_chunks", None) or []
    for tc in tcc:
        if isinstance(tc, dict):
            n = str(tc.get("name") or "").strip()
            if n:
                names.append(n)
        else:
            n = str(getattr(tc, "name", "") or "").strip()
            if n:
                names.append(n)
    return names


def iter_agent_text_and_tool_hints(
    agent: Any,
    messages: list[Any],
    *,
    cancel_requested: threading.Event | None = None,
) -> Iterator[tuple[str, str | None]]:
    """每次产出 (text_piece, tool_name)；二者至多一个非空。tool_name 表示模型刚选中的工具（或工具节点开始）。"""
    last_tool_emitted: str | None = None
    for chunk in agent.stream(
        {"messages": messages},
        stream_mode="messages",
        version="v2",
    ):
        if cancel_requested is not None and cancel_requested.is_set():
            break
        if not isinstance(chunk, dict) or chunk.get("type") != "messages":
            continue
        data = chunk.get("data")
        if not isinstance(data, tuple) or len(data) != 2:
            continue
        tok, meta = data
        node = meta.get("langgraph_node")

        if node == "tools" and isinstance(tok, ToolMessage):
            n = str(getattr(tok, "name", "") or "").strip()
            if n and n != last_tool_emitted:
                last_tool_emitted = n
                yield "", n
            last_tool_emitted = None
            continue

        if node != "model":
            continue
        if not isinstance(tok, AIMessageChunk):
            continue

        for n in _tool_names_from_aimessage_chunk(tok):
            if n and n != last_tool_emitted:
                last_tool_emitted = n
                yield "", n

        tcc = getattr(tok, "tool_call_chunks", None) or []
        piece = aimessage_chunk_text(getattr(tok, "content", None))
        if not piece and tcc:
            continue
        if piece:
            last_tool_emitted = None
            yield piece, None


def iter_agent_text_token_deltas(
    agent: Any,
    messages: list[Any],
    *,
    cancel_requested: threading.Event | None = None,
) -> Iterator[str]:
    for text_piece, tool_hint in iter_agent_text_and_tool_hints(
        agent, messages, cancel_requested=cancel_requested
    ):
        if tool_hint:
            continue
        if text_piece:
            yield text_piece


def iter_agent_text_batched_deltas(
    agent: Any,
    messages: list[Any],
    *,
    cancel_requested: threading.Event | None = None,
    min_chunk_chars: int = 36,
) -> Iterator[tuple[str, str | None]]:
    # 伪流式：在 token 流之上合并若干小段；遇到工具提示时先刷出缓冲区再单独产出 ("", tool_name)。
    buf: list[str] = []
    pending = 0
    for text_piece, tool_hint in iter_agent_text_and_tool_hints(
        agent, messages, cancel_requested=cancel_requested
    ):
        if tool_hint is not None:
            if buf:
                yield "".join(buf), None
                buf = []
                pending = 0
            yield "", tool_hint
        if not text_piece:
            continue
        buf.append(text_piece)
        pending += len(text_piece)
        if pending >= min_chunk_chars:
            yield "".join(buf), None
            buf = []
            pending = 0
    if buf:
        yield "".join(buf), None
