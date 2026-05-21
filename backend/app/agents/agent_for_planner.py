"""旅行规划智能体。"""

import threading
import re

from langchain.agents import create_agent
from langchain_core.messages import BaseMessage, HumanMessage

from backend.app.agents.prompt_templates import PLANNER_PROMPT
from backend.app.agents.tongyi_llm import get_chat_tongyi
from backend.app.services.agent_stream_tokens import iter_agent_text_batched_deltas
from backend.app.services.planner_query_builder import ensure_preference_block
from backend.app.services.preference_extractor import extract_preferences
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


_BUDGET_FIELD_RE = re.compile(
    r"(?P<prefix>(?:总预算|预算|预算上限|预算约束|费用上限|总费用|整体费用)"
    r"[^0-9¥￥元]{0,24}[¥￥]?\s*)"
    r"(?P<amount>\d{2,7})"
    r"(?P<suffix>\s*(?:元|块)?)"
)


def _build_locked_fact_prefix(user_query: str) -> str:
    """从用户原问题中提取预算和天数硬约束，生成模型前置提醒。"""
    pref = extract_preferences(user_query)
    lines: list[str] = []
    budget = pref.get("budget_amount_yuan")
    scope = pref.get("budget_scope")
    days = pref.get("duration_days")
    if isinstance(budget, int):
        if scope == "per_person":
            lines.append(f"- **人均预算**：¥{budget}（按用户原文锁定，未提供人数时不折算总预算）")
        else:
            lines.append(f"- **总预算**：¥{budget}（按用户原文锁定）")
    if isinstance(days, int):
        lines.append(f"- **行程天数**：{days} 天（按用户原文锁定）")
    if not lines:
        return ""
    return "## 已锁定用户约束（供模型遵守，不得向用户复述本段标题）\n" + "\n".join(lines) + "\n\n"


def _sanitize_locked_facts(text: str, user_query: str) -> str:
    """智能体内部进行预算约束。"""
    cleaned = re.sub(
        r"^\s*## 已锁定用户约束[^\n]*\n(?:- .*\n)*\s*",
        "",
        str(text or ""),
    )
    cleaned = re.sub(
        r"^\s*(?:行程天数|总预算|人均预算)[：:][^\n]*硬约束[^\n]*\n+",
        "",
        cleaned,
        flags=re.MULTILINE,
    )

    pref = extract_preferences(user_query)
    budget = pref.get("budget_amount_yuan")
    if not isinstance(budget, int) or budget <= 0:
        return cleaned
    truncated_values: set[int] = set()
    n = budget
    while n >= 10 and n % 10 == 0:
        n //= 10
        truncated_values.add(n)
    if not truncated_values:
        return cleaned

    def repl(match: re.Match[str]) -> str:
        """把被模型截短的预算数字替换回用户原始完整预算。"""
        try:
            amount = int(match.group("amount"))
        except ValueError:
            return match.group(0)
        if amount not in truncated_values:
            return match.group(0)
        return f"{match.group('prefix')}{budget}{match.group('suffix')}"

    return _BUDGET_FIELD_RE.sub(repl, cleaned)


class PlannerAgent:
    """封装旅行规划所需的天气、地图、套餐和知识库工具。"""

    def __init__(self):
        """初始化规划工具集、通义模型和 Agent 实例。"""
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
        """以流式方式生成旅行规划，并在输出前清理内部约束提示。"""
        try:
            guarded_query = ensure_preference_block(user_query)
            messages = [*(history_messages or []), HumanMessage(content=guarded_query)]
            fact_prefix = _build_locked_fact_prefix(user_query)
            cumulative = fact_prefix
            for piece, tool_hint in iter_agent_text_batched_deltas(
                self.agent,
                messages,
                cancel_requested=cancel_requested,
            ):
                if piece:
                    cumulative += piece
                visible = _sanitize_locked_facts(cumulative, user_query)
                if tool_hint is not None:
                    yield visible, [], tool_hint
                elif piece:
                    yield visible, [], None
            visible = _sanitize_locked_facts(cumulative, user_query)
            if not visible.strip():
                yield "（未生成可见回复，请重试或简化问题。）", [], None
            elif visible != cumulative:
                yield visible, [], None
        except Exception as exc:
            yield f"旅行规划时发生错误：{exc}，请联系管理员。", [], None

    def planner_assistant(
        self, user_query: str, *, history_messages: list[BaseMessage] | None = None
    ) -> tuple[str, list[dict[str, str]]]:
        """同步生成旅行规划，返回最终文本。"""
        text = ""
        for content, _, _ in self.planner_assistant_stream(
            user_query, history_messages=history_messages
        ):
            text = content
        return text, []
