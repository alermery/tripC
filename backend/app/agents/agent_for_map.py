"""Map agent."""

import threading

from langchain.agents import create_agent
from langchain_core.messages import BaseMessage, HumanMessage

from backend.app.agents.prompt_templates import MAP_PROMPT
from backend.app.agents.tongyi_llm import get_chat_tongyi
from backend.app.services.agent_stream_tokens import iter_agent_text_batched_deltas
from backend.app.tools.get_map import (
    geocode_address,
    get_user_location,
    nearby_hotels,
    nearby_restaurants,
    route_plan,
)


class MapAgent:
    def __init__(self):
        self.tools = [
            geocode_address,
            route_plan,
            get_user_location,
            nearby_hotels,
            nearby_restaurants,
        ]
        self.llm = get_chat_tongyi()
        self.agent = create_agent(
            tools=self.tools,
            model=self.llm,
            system_prompt=MAP_PROMPT,
        )

    def map_assistant_stream(
        self, location: str, *, cancel_requested: threading.Event | None = None
    ):
        try:
            messages: list[BaseMessage] = [HumanMessage(content=location)]
            cumulative = ""
            for piece, tool_hint in iter_agent_text_batched_deltas(
                self.agent,
                messages,
                cancel_requested=cancel_requested,
            ):
                if piece:
                    cumulative += piece
                if tool_hint is not None:
                    yield cumulative, [], tool_hint
                elif piece:
                    yield cumulative, [], None
            if not cumulative.strip():
                yield "（未生成可见回复，请重试或简化问题。）", [], None
        except Exception as exc:
            yield f"地图查询时发生错误：{exc}，请联系管理员。", [], None

    def map_assistant(self, location: str) -> tuple[str, list[dict[str, str]]]:
        text = ""
        for content, _, _ in self.map_assistant_stream(location):
            text = content
        return text, []
