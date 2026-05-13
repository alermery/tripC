# 对话编排服务：按用户显式选择的智能体类型调用天气 / 地图 / 行程智能体。

import logging
import threading
from functools import lru_cache

from backend.app.agents.agent_for_map import MapAgent
from backend.app.agents.agent_for_planner import PlannerAgent
from backend.app.agents.agent_for_weather import WeatherAgent
from backend.app.schemas.chat import AgentType
from backend.app.services.user_travel_context import build_planner_history_messages

logger = logging.getLogger(__name__)


# 应用内统一入口，封装各 LangChain Agent 的构造与调用。
class AssistantService:
    def __init__(self) -> None:
        self._weather = WeatherAgent()
        self._map = MapAgent()
        self._planner = PlannerAgent()

    def chat(
        self,
        query: str,
        agent: AgentType,
        *,
        username: str | None = None,
        conversation_id: str | None = None,
    ) -> tuple[AgentType, str, list[dict[str, str]]]:
        if agent == "weather":
            text, tools = self._weather.weather_assistant(query)
            return "weather", text, tools
        if agent == "map":
            text, tools = self._map.map_assistant(query)
            return "map", text, tools
        # planner
        hist: list = []
        if username and conversation_id:
            hist = build_planner_history_messages(username, conversation_id)
        logger.info(
            "AssistantService.chat planner user=%s conversation_id=%s history_lc_messages=%d query_len=%d",
            username or "",
            conversation_id or "",
            len(hist),
            len(query or ""),
        )
        text, tools = self._planner.planner_assistant(query, history_messages=hist)
        return "planner", text, tools

    def chat_stream(
        self,
        query: str,
        agent: AgentType,
        *,
        username: str | None = None,
        conversation_id: str | None = None,
        cancel_requested: threading.Event | None = None,
    ):
        # 与 chat 相同路由；流式为 LangGraph messages + 通义流式，正文按批（多 token）累积推送。
        if agent == "weather":
            yield from self._weather.weather_assistant_stream(
                query, cancel_requested=cancel_requested
            )
            return
        if agent == "map":
            yield from self._map.map_assistant_stream(query, cancel_requested=cancel_requested)
            return
        hist: list = []
        if username and conversation_id:
            hist = build_planner_history_messages(username, conversation_id)
        logger.info(
            "AssistantService.chat_stream planner user=%s conversation_id=%s history_lc_messages=%d query_len=%d",
            username or "",
            conversation_id or "",
            len(hist),
            len(query or ""),
        )
        yield from self._planner.planner_assistant_stream(
            query, history_messages=hist, cancel_requested=cancel_requested
        )


@lru_cache
def get_assistant_service() -> AssistantService:
    # 缓存单例，避免每次请求都重新创建大模型客户端。
    return AssistantService()
