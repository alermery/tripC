"""旅行选项的离线性价比评分。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from backend.app.services.preference_extractor import extract_preferences


def _to_float(value: Any, default: float = 0.0) -> float:
    """把任意值尽量转换为浮点数。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _query_flags(query: str) -> dict[str, bool]:
    """从用户问题中提取性价比相关的关键词标记。"""
    raw = str(query or "")
    return {
        "family": any(k in raw for k in ("亲子", "孩子", "父母", "老人")),
        "save_money": any(k in raw for k in ("省钱", "预算紧", "经济", "性价比")),
        "food": "美食" in raw,
        "weekend": "周末" in raw,
        "comfortable": any(k in raw for k in ("舒适", "轻松", "少折腾", "方便")),
        "study": any(k in raw for k in ("研学", "博物馆", "人文")),
    }


def _budget_price_score(total_price_yuan: float, budget_amount_yuan: float) -> float:
    """按预算上限计算价格得分。"""
    ratio = total_price_yuan / max(budget_amount_yuan, 1.0)
    if ratio <= 1:
        return 0.7 + 0.3 * (1 - ratio)
    overflow = ratio - 1
    return max(-1.5, 0.7 - overflow * 3.5)


def _relative_price_score(total_price_yuan: float, peer_prices: Sequence[float]) -> float:
    """在同批候选中按相对价格计算得分。"""
    prices = [float(p) for p in peer_prices if p is not None]
    if not prices:
        return 0.5
    lo = min(prices)
    hi = max(prices)
    if hi <= lo:
        return 1.0
    return 1 - (total_price_yuan - lo) / (hi - lo)


def _experience_weights(query: str) -> tuple[float, float, float]:
    """根据用户意图调整便利、特色和舒适三个体验权重。"""
    flags = _query_flags(query)
    convenience = 0.34
    feature = 0.33
    comfort = 0.33
    if flags["family"]:
        convenience += 0.12
        comfort += 0.08
        feature -= 0.05
    if flags["comfortable"]:
        comfort += 0.10
        convenience += 0.04
    if flags["food"]:
        feature += 0.12
        convenience += 0.03
    if flags["study"]:
        feature += 0.10
    if flags["weekend"]:
        convenience += 0.08
    s = convenience + feature + comfort
    return convenience / s, feature / s, comfort / s


def score_cost_effective_option(
    query: str,
    option: Mapping[str, Any],
    *,
    peer_prices: Sequence[float] | None = None,
) -> dict[str, Any]:
    """给单个旅行选项计算性价比分数与分项权重。"""
    pref = extract_preferences(query)
    flags = _query_flags(query)
    budget = pref.get("budget_amount_yuan")
    price_weight = float(pref.get("price_weight", 0.5))
    experience_weight = float(pref.get("experience_weight_score", 0.5))
    if flags["save_money"]:
        price_weight = max(price_weight, 0.68)
        experience_weight = 1 - price_weight

    total_price = _to_float(option.get("total_price_yuan"))
    if isinstance(budget, int) and budget > 0:
        price_score = _budget_price_score(total_price, float(budget))
    else:
        price_score = _relative_price_score(total_price, peer_prices or [])

    convenience_score = _to_float(option.get("convenience_score")) / 10.0
    feature_score = _to_float(option.get("feature_score")) / 10.0
    comfort_score = _to_float(option.get("comfort_score")) / 10.0
    convenience_weight, feature_weight, comfort_weight = _experience_weights(query)
    experience_score = (
        convenience_weight * convenience_score
        + feature_weight * feature_score
        + comfort_weight * comfort_score
    )
    total_score = price_weight * price_score + experience_weight * experience_score
    return {
        "option_name": option.get("option_name", ""),
        "total_score": round(total_score, 4),
        "price_score": round(price_score, 4),
        "experience_score": round(experience_score, 4),
        "price_weight": round(price_weight, 3),
        "experience_weight": round(experience_weight, 3),
        "convenience_weight": round(convenience_weight, 3),
        "feature_weight": round(feature_weight, 3),
        "comfort_weight": round(comfort_weight, 3),
        "budget_amount_yuan": budget,
    }


def rank_cost_effective_options(
    query: str,
    options: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """对多个候选旅行选项按性价比排序。"""
    peer_prices = [_to_float(option.get("total_price_yuan")) for option in options]
    ranked: list[dict[str, Any]] = []
    for option in options:
        row = dict(option)
        row.update(score_cost_effective_option(query, option, peer_prices=peer_prices))
        ranked.append(row)
    ranked.sort(key=lambda item: float(item.get("total_score") or 0.0), reverse=True)
    return ranked


def choose_best_cost_effective_option(
    query: str,
    options: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """返回性价比最高的单个旅行选项。"""
    ranked = rank_cost_effective_options(query, options)
    return ranked[0] if ranked else None
