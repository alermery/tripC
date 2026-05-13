# 预算类工具，供规划智能体调用。

from __future__ import annotations
from langchain_core.tools import tool

@tool(description="按总预算与天数给出交通、住宿、餐饮、门票、机动的大致占比（economy / balanced / comfort）。")
def trip_budget_skeleton(total_budget_yuan: int, trip_days: int, style: str = "balanced") -> str:
    if total_budget_yuan <= 0 or trip_days <= 0:
        return "总预算与天数须为正整数。"
    st = (style or "balanced").strip().lower()
    if st in ("econ", "cheap", "省", "经济"):
        st = "economy"
    elif st in ("lux", "舒适", "品质"):
        st = "comfort"
    else:
        st = "balanced"

    profiles = {
        "economy": (0.28, 0.26, 0.18, 0.18, 0.10),
        "balanced": (0.25, 0.30, 0.20, 0.15, 0.10),
        "comfort": (0.22, 0.38, 0.20, 0.12, 0.08),
    }
    trans, stay, food, ticket, buffer_ = profiles[st]
    per_day = total_budget_yuan / trip_days

    def line(name: str, ratio: float) -> str:
        amt = int(total_budget_yuan * ratio)
        return f"- {name}：约 {ratio * 100:.0f}%（约 ¥{amt}）"

    return (
        f"预算骨架（{st}，共 ¥{total_budget_yuan} / {trip_days} 天，日均约 ¥{per_day:.0f}）\n"
        f"{line('大交通', trans)}\n"
        f"{line('住宿', stay)}\n"
        f"{line('餐饮', food)}\n"
        f"{line('门票与活动', ticket)}\n"
        f"{line('机动', buffer_)}\n"
        "比例为常见自由行参考，请结合目的地与季节调整。"
    )
