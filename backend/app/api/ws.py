"""WebSocket chat endpoint."""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import uuid
from datetime import datetime, timezone
from typing import cast

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.db import SessionLocal
from backend.app.models.chat_message import ChatMessage
from backend.app.models.user import User
from backend.app.schemas.chat import AgentType
from backend.app.security import decode_access_token
from backend.app.services.assistant_service import get_assistant_service
from backend.app.services.planner_query_builder import build_enriched_planner_query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

_CANCEL_POLL_QUICK = 0.001
_CANCELLED_SUFFIX = "\n\n（已停止输出）"


def _parse_started_at(raw_value: str) -> datetime:
    try:
        value = str(raw_value or "").strip()
        if not value:
            return datetime.utcnow()
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except Exception:
        return datetime.utcnow()


def _mark_reply_cancelled(reply: str) -> str:
    text = str(reply or "")
    if "已停止输出" in text:
        return text
    if not text:
        return _CANCELLED_SUFFIX.strip()
    return text + _CANCELLED_SUFFIX


def _save_chat_message(
    username: str,
    user_query: str,
    reply: str,
    target_agent: AgentType,
    conversation_id: str,
    conversation_started_at: datetime,
) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            raise ValueError("User not found")
        db.add(
            ChatMessage(
                user_id=user.id,
                agent=target_agent,
                conversation_id=conversation_id,
                conversation_started_at=conversation_started_at,
                query=user_query,
                reply=reply,
            )
        )
        db.commit()
    finally:
        db.close()


def _queue_poll(q: queue.Queue, timeout: float) -> dict | None:
    try:
        return q.get(timeout=timeout)
    except queue.Empty:
        return None


def _apply_remaining_queue(q: queue.Queue, acc_full: str) -> str:
    while True:
        try:
            item = q.get_nowait()
        except queue.Empty:
            break
        kind = item.get("kind")
        if kind == "delta":
            acc_full += str(item.get("delta") or "")
        elif kind == "done":
            acc_full = str(item.get("full") or acc_full)
        elif kind == "error":
            err = str(item.get("message") or "")
            acc_full += f"\n\n（错误：{err}）"
    return acc_full


def _chat_stream_producer(
    q: queue.Queue,
    username: str,
    model_query: str,
    agent: AgentType,
    conversation_id: str,
    cancel_requested: threading.Event,
) -> None:
    try:
        service = get_assistant_service()
        prev_full = ""
        for full_text, _, tool_hint in service.chat_stream(
            model_query,
            agent,
            username=username,
            conversation_id=conversation_id,
            cancel_requested=cancel_requested,
        ):
            if cancel_requested.is_set():
                break
            if tool_hint:
                q.put({"kind": "tool_hint", "tool": str(tool_hint)})
            delta = full_text[len(prev_full) :]
            prev_full = full_text
            if delta:
                q.put({"kind": "delta", "delta": delta})
        q.put({"kind": "done", "full": prev_full})
    except Exception as exc:
        logger.exception("chat stream producer failed")
        q.put({"kind": "error", "message": str(exc)})


async def _pump_agent_stream_to_websocket(
    websocket: WebSocket,
    message_id: str,
    q: queue.Queue,
    producer_thread: threading.Thread,
    incoming_queue: list,
    cancel_requested: threading.Event,
) -> tuple[bool, str, bool]:
    acc_full = ""
    user_cancelled = False

    async def drain_cancel(timeout: float) -> bool:
        try:
            msg = await asyncio.wait_for(websocket.receive_json(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        if not isinstance(msg, dict):
            incoming_queue.append(msg)
            return False
        if msg.get("type") == "cancel":
            mid = str(msg.get("message_id") or "")
            if not mid or mid == message_id:
                cancel_requested.set()
                return True
            incoming_queue.append(msg)
            return False
        incoming_queue.append(msg)
        return False

    if await drain_cancel(0.12):
        user_cancelled = True
    else:
        while True:
            if await drain_cancel(_CANCEL_POLL_QUICK):
                user_cancelled = True
                break
            item = await asyncio.to_thread(_queue_poll, q, 0.06)
            if item is None:
                if await drain_cancel(0.02):
                    user_cancelled = True
                    break
                if not producer_thread.is_alive() and q.empty():
                    logger.warning(
                        "chat stream producer stopped without done (message_id=%s)",
                        message_id,
                    )
                    break
                continue
            kind = item.get("kind")
            if kind == "delta":
                delta = str(item.get("delta") or "")
                if delta:
                    acc_full += delta
                    await websocket.send_json(
                        {
                            "type": "stream_chunk",
                            "message_id": message_id,
                            "chunk": delta,
                        }
                    )
                if await drain_cancel(_CANCEL_POLL_QUICK):
                    user_cancelled = True
                    break
            elif kind == "tool_hint":
                tool_name = str(item.get("tool") or "").strip()
                if tool_name:
                    await websocket.send_json(
                        {
                            "type": "tool_progress",
                            "message_id": message_id,
                            "tool": tool_name,
                        }
                    )
                if await drain_cancel(_CANCEL_POLL_QUICK):
                    user_cancelled = True
                    break
            elif kind == "done":
                acc_full = str(item.get("full") or acc_full)
                return True, acc_full, False
            elif kind == "error":
                err = str(item.get("message") or "")
                extra = f"\n\n（错误：{err}）"
                acc_full += extra
                await websocket.send_json(
                    {
                        "type": "stream_chunk",
                        "message_id": message_id,
                        "chunk": extra,
                    }
                )
                return True, acc_full, False

    if user_cancelled:
        await asyncio.to_thread(producer_thread.join, 0.5)
        return False, acc_full, True

    await asyncio.to_thread(producer_thread.join)
    acc_full = _apply_remaining_queue(q, acc_full)
    return False, acc_full, False


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    await websocket.accept()

    try:
        auth_payload = await asyncio.wait_for(websocket.receive_json(), timeout=15)
        if auth_payload.get("type") != "auth":
            await websocket.close(code=1008, reason="Auth required")
            return
        token = str(auth_payload.get("token", ""))
        username = decode_access_token(token)
        if not username:
            await websocket.close(code=1008, reason="Unauthorized")
            return
        await websocket.send_json({"type": "system", "message": "auth ok"})

        incoming_queue: list = []

        async def next_payload() -> dict:
            if incoming_queue:
                return incoming_queue.pop(0)
            return await websocket.receive_json()

        while True:
            payload = await next_payload()
            if isinstance(payload, dict) and payload.get("type") == "cancel":
                continue

            query = str(payload.get("query", "")).strip()
            user_query = query
            latitude = payload.get("latitude")
            longitude = payload.get("longitude")
            current_city = str(payload.get("current_city", "")).strip()
            current_address = str(payload.get("current_address", "")).strip()
            raw_conversation_id = str(payload.get("conversation_id", "")).strip()
            conversation_id_generated = not raw_conversation_id
            conversation_id = raw_conversation_id or f"conv_{uuid.uuid4().hex}"
            conversation_started_at = _parse_started_at(
                payload.get("conversation_started_at", "")
            )
            raw_agent = str(payload.get("agent", "")).strip().lower()
            if raw_agent not in ("weather", "map", "planner"):
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "请选择智能体：weather（天气）、map（地图）或 planner（旅行规划）",
                    }
                )
                continue
            agent = cast(AgentType, raw_agent)

            if not query:
                await websocket.send_json(
                    {"type": "error", "message": "query 不能为空"}
                )
                continue

            if latitude is not None and longitude is not None:
                query = (
                    f"{query}\n\n"
                    f"用户已授权定位，当前坐标为纬度：{latitude}，经度：{longitude}。\n"
                    "请优先结合定位信息进行回答。"
                )

            if current_city and agent == "planner":
                no_departure_hint = all(
                    keyword not in query for keyword in ("从", "出发", "departure", "from")
                )
                if no_departure_hint:
                    query = (
                        f"{query}\n\n"
                        f"用户未明确指出出发地时，请默认出发地为“{current_city}”。\n"
                        f"（定位地址：{current_address or current_city}）"
                    )

            logger.info(
                "ws chat message user=%s conversation_id=%s conversation_id_generated=%s "
                "agent=%s user_query_len=%d",
                username,
                conversation_id,
                conversation_id_generated,
                agent,
                len(user_query),
            )
            logger.debug(
                "ws user_query preview: %s",
                user_query[:500].replace("\n", "\\n"),
            )

            if agent == "planner":
                notes = str(payload.get("itinerary_notes", "") or "")
                memory_reset = bool(payload.get("planner_memory_reset"))
                query = build_enriched_planner_query(
                    username,
                    query,
                    notes,
                    preference_source=user_query,
                    conversation_id=conversation_id,
                    skip_cross_conversation_memory=memory_reset,
                )
                logger.info(
                    "planner enriched query len=%d (conversation_id=%s)",
                    len(query),
                    conversation_id,
                )
                logger.debug(
                    "planner enriched preview tail: %s",
                    (query[-800:] if len(query) > 800 else query).replace("\n", "\\n"),
                )

            message_id = str(uuid.uuid4())
            await websocket.send_json(
                {
                    "type": "stream_start",
                    "message_id": message_id,
                    "agent": agent,
                    "conversation_id": conversation_id,
                }
            )

            cancel_requested = threading.Event()
            q: queue.Queue = queue.Queue()
            producer_thread = threading.Thread(
                target=_chat_stream_producer,
                args=(q, username, query, agent, conversation_id, cancel_requested),
                daemon=True,
            )
            producer_thread.start()

            got_done, reply, user_cancelled = await _pump_agent_stream_to_websocket(
                websocket,
                message_id,
                q,
                producer_thread,
                incoming_queue,
                cancel_requested,
            )

            if user_cancelled:
                reply = _mark_reply_cancelled(reply)

            await websocket.send_json(
                {
                    "type": "stream_end",
                    "message_id": message_id,
                    "cancelled": user_cancelled,
                }
            )

            try:
                await asyncio.to_thread(
                    _save_chat_message,
                    username,
                    user_query,
                    reply,
                    agent,
                    conversation_id,
                    conversation_started_at,
                )
            except Exception:
                logger.exception(
                    "save chat failed user=%s conversation_id=%s",
                    username,
                    conversation_id,
                )

            logger.info(
                "chat done user=%s conversation_id=%s target_agent=%s reply_len=%d "
                "stream_done=%s cancelled=%s",
                username,
                conversation_id,
                agent,
                len(reply or ""),
                got_done,
                user_cancelled,
            )
    except WebSocketDisconnect:
        return
    except Exception:
        await websocket.send_json({"type": "error", "message": "WebSocket internal error"})
