"""Trip planner agent."""

import threading

from langchain.agents import create_agent
from langchain_core.messages import BaseMessage, HumanMessage

from backend.app.agents.prompt_templates import PLANNER_PROMPT
from backend.app.agents.tongyi_llm import get_chat_tongyi
from backend.app.services.agent_stream_tokens import iter_agent_text_batched_deltas
from backend.app.tools.get_map import (
    geocode_address,
    get_user_location,
    nearby_hotels,
    nearby_restaurants,
    route_plan,
)
from backend.app.tools.get_tips import travel_safe_tips, travel_season_tips
from backend.app.tools.get_travel_details import (
    find_best_offers,
    get_travel_by_price_range,
    recommend_destination_customs,
    search_travel_deals,
    vector_store_retriever,
)
from backend.app.tools.get_weather import qweather_forecast
from backend.app.tools.rag_kb import rag_kb_retriever
from backend.app.tools.trip_agents_tools import trip_budget_skeleton


class PlannerAgent:
    def __init__(self):
        self.tools = [
            qweather_forecast,
            geocode_address,
            route_plan,
            get_user_location,
            nearby_hotels,
            nearby_restaurants,
            search_travel_deals,
            find_best_offers,
            get_travel_by_price_range,
            recommend_destination_customs,
            trip_budget_skeleton,
            vector_store_retriever,
            travel_season_tips,
            travel_safe_tips,
            rag_kb_retriever,
        ]
        self.llm = get_chat_tongyi()
        self.agent = create_agent(
            tools=self.tools,
            model=self.llm,
            system_prompt=PLANNER_PROMPT,
        )

    def planner_assistant_stream(
        self,
        user_query: str,
        *,
        history_messages: list[BaseMessage] | None = None,
        cancel_requested: threading.Event | None = None,
    ):
        try:
            messages = [*(history_messages or []), HumanMessage(content=user_query)]
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
            yield f"旅行规划时发生错误：{exc}，请联系管理员。", [], None

    def planner_assistant(
        self, user_query: str, *, history_messages: list[BaseMessage] | None = None
    ) -> tuple[str, list[dict[str, str]]]:
        text = ""
        for content, _, _ in self.planner_assistant_stream(
            user_query, history_messages=history_messages
        ):
            text = content
        return text, []
