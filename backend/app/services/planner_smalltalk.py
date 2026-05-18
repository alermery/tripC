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
    return (text or "").split("\n\n")[0].strip()


def _is_thanks_only(text: str) -> bool:
    return bool(_THANKS_RE.match(_first_user_line(text)))


def build_thanks_reply() -> str:
    return (
        "不客气。若接下来有目的地、出行天数、预算或交通偏好等需求，直接告诉我就好，"
        "我会继续为您整理行程。"
    ).strip()


@dataclass(frozen=True)
class PlannerShortcutContext:
    raw_user_query: str
    default_city: str = ""
    latitude: float | None = None
    longitude: float | None = None


def try_planner_fast_reply(ctx: PlannerShortcutContext) -> str | None:
    """Return a local fixed reply only for the safest acknowledgements."""
    text = _first_user_line(ctx.raw_user_query)
    if not text:
        return None
    if _is_thanks_only(text):
        logger.info("planner fast path: thanks")
        return build_thanks_reply()
    return None
