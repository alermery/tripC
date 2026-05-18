"""
从自然语言中做轻量级偏好提取（规则为主，无额外 LLM 调用），供规划智能体增强上下文。
用户意图理解 — 偏好提取、性价比倾向初判。
"""

from __future__ import annotations

import re
from typing import Any


_BUDGET_WITH_LABEL_RE = re.compile(
    r"(?P<label>总预算|预算|人均|每人|总费用|费用)\s*[:：]?\s*"
    r"(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>万元|万|元|块)?"
)
_BUDGET_WITH_UNIT_RE = re.compile(
    r"(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>万元|万|元|块)"
    r"(?:以内|左右|以下|上下)?"
)


def _amount_to_yuan(amount: str, unit: str | None) -> int | None:
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if unit in ("万", "万元"):
        value *= 10000
    return int(round(value))


def _apply_budget_match(out: dict[str, Any], match: re.Match[str], *, scope: str) -> None:
    out["budget_phrase"] = match.group(0)
    amount = _amount_to_yuan(match.group("amount"), match.groupdict().get("unit"))
    if amount is not None:
        out["budget_amount_yuan"] = amount
        out["budget_scope"] = scope


def extract_preferences(text: str) -> dict[str, Any]:
    if not text or not str(text).strip():
        return {}
    raw = str(text).strip()
    out: dict[str, Any] = {}

    m = _BUDGET_WITH_LABEL_RE.search(raw)
    if m:
        label = m.group("label")
        scope = "per_person" if label in ("人均", "每人") else "total_or_unspecified"
        _apply_budget_match(out, m, scope=scope)

    if "budget_phrase" not in out:
        m = _BUDGET_WITH_UNIT_RE.search(raw)
        if m:
            _apply_budget_match(out, m, scope="total_or_unspecified")

    m = re.search(r"(\d+)\s*(?:天|晚|日)(?:的|以内)?(?:行程|游|假|计划)?", raw)
    if m:
        try:
            out["duration_days"] = int(m.group(1))
        except ValueError:
            pass

    modes: list[str] = []
    for k in ("高铁", "动车", "飞机", "航班", "自驾", "租车", "火车", "大巴", "地铁", "公交"):
        if k in raw and k not in modes:
            modes.append(k)
    if modes:
        out["transport_modes"] = modes

    interests: list[str] = []
    for k in ("亲子", "蜜月", "美食", "摄影", "徒步", "博物馆", "人文", "自然风光", "海滨", "滑雪", "古镇", "打卡"):
        if k in raw and k not in interests:
            interests.append(k)
    if interests:
        out["interests"] = interests

    price_keys = ("便宜", "省钱", "性价比", "经济", "穷游", "预算紧", "少花钱", "低价")
    exp_keys = ("体验", "舒适", "品质", "豪华", "深度", "不紧", "松弛", "享受")

    if any(k in raw for k in price_keys):
        out["price_sensitivity"] = "high"
    if any(k in raw for k in exp_keys):
        out["experience_weight"] = "high"

    if out.get("price_sensitivity") == "high" and out.get("experience_weight") == "high":
        out["cpex_tradeoff_note"] = "用户同时强调省钱与体验，请分档给出「经济优先 / 平衡 / 舒适优先」方案并说明取舍依据。"

    # 量化性价比偏好向量（w_price + w_experience = 1），用于课题「性价比偏好建模」
    w_price = 0.5
    w_exp = 0.5
    if out.get("price_sensitivity") == "high":
        w_price += 0.22
        w_exp -= 0.12
    if out.get("experience_weight") == "high":
        w_exp += 0.22
        w_price -= 0.12
    w_price = max(0.15, min(0.85, w_price))
    w_exp = max(0.15, min(0.85, w_exp))
    s = w_price + w_exp
    out["price_weight"] = round(w_price / s, 3)
    out["experience_weight_score"] = round(w_exp / s, 3)

    return out


def format_preferences_for_prompt(pref: dict[str, Any]) -> str:
    if not pref:
        return ""
    lines = [
        "【从本轮用户表述中提取的结构化偏好（系统自动生成，请勿向用户复述本段标题）】",
    ]
    if bp := pref.get("budget_phrase"):
        lines.append(f"- 预算相关表述：{bp}")
    budget_amount = pref.get("budget_amount_yuan")
    budget_scope = pref.get("budget_scope")
    if isinstance(budget_amount, int):
        if budget_scope == "per_person":
            lines.append(
                f"- 人均预算数值（硬约束）：{budget_amount} 元；未提供人数时不得当作总预算，"
                "预算估算需标注为人均或先说明人数假设。"
            )
        else:
            lines.append(
                f"- 预算数值（硬约束）：{budget_amount} 元；调用 trip_budget_skeleton 时 "
                "total_budget_yuan 必须使用该完整数值，禁止省略、截断、缩放或重新估算。"
            )
    if d := pref.get("duration_days"):
        lines.append(
            f"- 行程天数数值（硬约束）：{d} 天；调用 trip_budget_skeleton 时 trip_days 必须使用该天数。"
        )
    if tm := pref.get("transport_modes"):
        lines.append(f"- 出行方式倾向：{', '.join(tm)}")
    if it := pref.get("interests"):
        lines.append(f"- 兴趣/主题：{', '.join(it)}")
    ps = pref.get("price_sensitivity")
    ew = pref.get("experience_weight")
    if ps == "high" or ew == "high":
        bits = []
        if ps == "high":
            bits.append("偏价格敏感")
        if ew == "high":
            bits.append("偏体验与品质")
        lines.append("- 性价比倾向初判：" + "；".join(bits))
    pw = pref.get("price_weight")
    ew_score = pref.get("experience_weight_score")
    if isinstance(pw, (int, float)) and isinstance(ew_score, (int, float)):
        lines.append(
            f"- 量化偏好向量（价格权重 {pw}，体验权重 {ew_score}；"
            "数值越大表示该维度在方案权衡中占比越高，请在「多维度性价比评估」中显式引用）"
        )
    if note := pref.get("cpex_tradeoff_note"):
        lines.append(f"- {note}")
    return "\n".join(lines)
