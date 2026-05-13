# 旅行规划智能体：自我介绍与明显非行程类问题的本地快捷回复，避免走完整工具链。

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_INTRO_RE = re.compile(
    r"(^|[\s，,。.!！？?])("
    r"你是谁|你哪位|你是什么|什么助手|哪个助手|什么智能体|哪个智能体|"
    r"自我介绍|介绍[一下]?你[自己]?|介绍下你|"
    r"你(能|会)做什么|你(能|会)干什么|你的功能|有哪些功能|能帮我什么|"
    r"你叫什么|你的名字|什么名字|什么模型|你是gpt|你是ai|"
    r"who\s*are\s*you|what\s*are\s*you|introduce\s+yourself"
    r")([\s，,。.!！？?]|$)",
    re.IGNORECASE,
)

_THANKS_RE = re.compile(
    r"^\s*(谢谢|感谢|多谢|谢了|thanks|thank\s+you|thx)\s*[!！。.…]*\s*$",
    re.IGNORECASE,
)

_GREETING_RE = re.compile(
    r"^\s*(你好|您好|hi|hello)\s*[!！。.…]*\s*$",
    re.IGNORECASE,
)

_TRAVEL_HINT = (
    "旅行",
    "旅游",
    "行程",
    "攻略",
    "酒店",
    "民宿",
    "机票",
    "航班",
    "火车",
    "高铁",
    "动车",
    "天气",
    "地图",
    "路线",
    "导航",
    "景点",
    "门票",
    "预算",
    "度假",
    "出行",
    "包车",
    "自驾",
    "住宿",
    "签证",
    "目的地",
    "出发",
    "动线",
    "路书",
    "日程",
    "游玩",
    "亲子",
    "蜜月",
    "几日",
    "几天",
    "一日",
    "两日",
    "三日",
    "四日",
    "一晚",
    "两晚",
    "三日游",
    "日游",
    "自由行",
    "跟团",
    "帮我规划",
    "规划一下",
    "安排一下",
    "去哪",
    "去玩",
)

_TECH_META = (
    "invoke",
    "stream",
    "langchain",
    "langgraph",
    "openai",
    "openapi",
    "restful",
    "graphql",
    "websocket",
    "socket",
    "api",
    "sdk",
    "jwt",
    "oauth",
    "postgres",
    "postgresql",
    "mysql",
    "redis",
    "docker",
    "kubernetes",
    "k8s",
    "github",
    "源码",
    "源代码",
    "后端",
    "前端",
    "数据库",
    "技术实现",
    "如何实现",
    "怎么实现",
    "架构设计",
    "部署方式",
    "通义",
    "qwen",
    "embedding",
    "向量数据库",
    "微调",
    "训练数据",
    "token",
    "python",
    "javascript",
    "typescript",
    "fastapi",
    "langsmith",
)

_DURATION_RE = re.compile(r"\d+\s*[天晚夜日]")

_CHITCHAT_NON_TRAVEL = (
    "星期几",
    "几号",
    "几点",
    "股票",
    "彩票",
    "密码",
    "验证码",
    "写代码",
    "编程",
    "数学题",
    "法律",
    "看病",
    "医院",
)

_SHORT_CJK_ONLY_RE = re.compile(r"^[\u4e00-\u9fff]{2,12}$")
_COORD_LIKE_RE = re.compile(
    r"1[0-1]\d\.\d+|2[0-8]\.\d+|\b\d{2,3}\.\d{4,8}\b"
)  # 粗略：常见纬度或小数坐标片段


def _first_user_line(text: str) -> str:
    return (text or "").split("\n\n")[0].strip()


def _has_travel_intent(text: str) -> bool:
    t = text
    for k in _TRAVEL_HINT:
        if k in t:
            return True
    if _DURATION_RE.search(t):
        return True
    return False


def _has_tech_meta(text: str) -> bool:
    low = text.lower()
    for k in _TECH_META:
        if k.lower() in low:
            return True
    return False


def _is_intro(text: str) -> bool:
    line = _first_user_line(text)
    if len(line) > 80:
        return False
    if _has_travel_intent(line):
        return False
    return bool(_INTRO_RE.search(line))


def _is_thanks_only(text: str) -> bool:
    return bool(_THANKS_RE.match(_first_user_line(text)))


def _is_off_topic(text: str) -> bool:
    """明显非行程需求：无行程语义，且为短闲聊、泛问或技术/实现类表述。"""
    line = _first_user_line(text)
    if not line:
        return False
    if _has_travel_intent(line):
        return False
    if _COORD_LIKE_RE.search(line) and len(line) < 48:
        # 可能仅粘贴坐标，仍交给规划器
        return False
    if _has_tech_meta(line):
        return True
    if len(line) <= 36:
        return True
    if len(line) <= 96 and ("?" in line or "？" in line) and not _has_travel_intent(line):
        return True
    return False


def _format_city(city: str) -> str:
    c = (city or "").strip()
    if not c:
        return "当前定位城市"
    if c.endswith("市") or c.endswith("县") or c.endswith("区") or c.endswith("州"):
        return c
    return f"{c}市"


def _format_coords(lat: float | None, lon: float | None) -> str:
    if lat is None or lon is None:
        return "未检测到有效定位坐标"
    try:
        return f"{float(lat):.6f}, {float(lon):.6f}"
    except (TypeError, ValueError):
        return "未检测到有效定位坐标"


def build_intro_reply() -> str:
    return (
        "我是**小C助手**里的**旅行规划智能体**，名字即「小C」行程助手这一角色。\n\n"
        "**主要功能**：结合工具为您整理可读行程，包括目的地与套餐检索、交通与地图动线、"
        "天气与装备建议、文化与安全提示、预算骨架等；您只需说明出发地、目的地、天数或预算偏好等，"
        "我会按需调用工具并输出结构化 Markdown 方案。"
    ).strip()


def build_thanks_reply() -> str:
    return (
        "不客气。若接下来有目的地、出行天数、预算或交通偏好等需求，直接告诉我就好，"
        "我会继续为您整理行程。"
    ).strip()


def build_off_topic_reply(*, default_city: str, latitude: float | None, longitude: float | None) -> str:
    city = _format_city(default_city)
    coord = _format_coords(latitude, longitude)
    return (
        "您的问题涉及技术实现或与行程规划无直接关联的内容；本智能体专注于**旅游行程规划**、"
        "**交通动线**、**天气与装备**、**文化与安全提示**、**套餐与费用信息**等的整合与推荐，"
        "不处理底层接口形态（例如 invoke 与 stream 如何选择）或通用编程、非旅行类咨询。\n\n"
        "若您有**旅行目的地**、**行程天数**、**预算范围**、**交通偏好**、**景点兴趣**等具体需求，"
        "请尽量写清楚，我将按需调用相应工具生成完整行程方案。\n\n"
        f"当前默认出发地为：**{city}**（依据定位坐标 {coord}）。\n"
        "请告知您的目的地、出行天数或其他偏好，以便启动规划流程。"
    ).strip()


@dataclass(frozen=True)
class PlannerShortcutContext:
    raw_user_query: str
    default_city: str = ""
    latitude: float | None = None
    longitude: float | None = None


def try_planner_fast_reply(ctx: PlannerShortcutContext) -> str | None:
    """
    若命中快捷路径则返回完整可见回复（单段），否则返回 None 走完整智能体。
    """
    text = _first_user_line(ctx.raw_user_query)
    if not text:
        return None
    if _is_intro(text):
        logger.info("planner fast path: intro")
        return build_intro_reply()
    if _is_thanks_only(text):
        logger.info("planner fast path: thanks")
        return build_thanks_reply()
    if _is_off_topic(text):
        logger.info("planner fast path: off_topic")
        return build_off_topic_reply(
            default_city=ctx.default_city,
            latitude=ctx.latitude,
            longitude=ctx.longitude,
        )
    return None
