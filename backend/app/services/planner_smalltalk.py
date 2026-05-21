"""Planner shortcut replies.

Keep local fixed replies extremely narrow so most user questions are handled by
the model instead of heuristic rules.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_THANKS_RE = re.compile(
    r"^\s*(谢谢|感谢|多谢|谢了|thanks|thank\s+you|thx)\s*[!！。.…]*\s*$",
    re.IGNORECASE,
)


def _first_user_line(text: str) -> str:
    """截取用户输入首段，忽略后续增强上下文。"""
    return (text or "").split("\n\n")[0].strip()


def _is_thanks_only(text: str) -> bool:
    """判断是否只是礼貌性致谢。"""
    return bool(_THANKS_RE.match(_first_user_line(text)))


def build_thanks_reply() -> str:
    """生成简短的致谢回复。"""
    return (
        "不客气。若接下来有目的地、出行天数、预算或交通偏好等需求，直接告诉我就好，"
        "我会继续为您整理行程。"
    ).strip()


@dataclass(frozen=True)
class PlannerShortcutContext:
    """规划智能体快捷回复所需的最小上下文。"""
    raw_user_query: str
    default_city: str = ""
    latitude: float | None = None
    longitude: float | None = None


def try_planner_fast_reply(ctx: PlannerShortcutContext) -> str | None:
    """仅对最安全的致谢类输入返回本地固定回复。"""
    text = _first_user_line(ctx.raw_user_query)
    if not text:
        return None
    if _is_thanks_only(text):
        logger.info("planner fast path: thanks")
        return build_thanks_reply()
    return None
