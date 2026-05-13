import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from langchain_core.tools import tool

from backend.app.services.chroma_client import chroma_similarity_search
from backend.app.services.travel_package_query import (
    query_find_best_offers,
    query_search_travel_deals,
    query_travel_by_price_range,
)

logger = logging.getLogger(__name__)


class Config:
    collection_name = "travel_deals"
    persist_directory = str(Path(__file__).resolve().parents[2] / "chroma_db")
    similarity_threshold = 3


CUSTOMS_CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "中国各地风俗.csv"


def _uploaded_at_sort_key(doc) -> tuple[int, datetime]:
    meta = getattr(doc, "metadata", {}) or {}
    raw = str(meta.get("uploaded_at") or "").strip()
    if not raw:
        return (1, datetime.min)
    try:
        return (0, datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None))
    except Exception:
        return (1, datetime.min)


@tool(description="根据用户给出的旅游目的地，检索本地知识库中的特色风俗与文化体验。")
def recommend_destination_customs(destination: str, max_items: int = 8) -> str:
    if not CUSTOMS_CSV_PATH.is_file():
        return "[错误] 未找到本地风俗数据文件。"
    rows: list[dict[str, str]] = []
    with CUSTOMS_CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            province = (row.get("省份") or "").strip()
            detail = (row.get("风俗详情") or "").strip()
            if destination in province or destination in detail:
                rows.append({"province": province, "detail": detail})
    if not rows:
        return f"知识库中暂无与“{destination}”高度匹配的风俗条目。"
    picked = rows[: max(1, min(max_items, 20))]
    lines = [f"**{destination} 路线特色风俗与体验推荐**\n"]
    for idx, row in enumerate(picked, 1):
        lines.append(f"**{idx}. {row['province']}**\n{row['detail']}\n")
    return "\n".join(lines)


@tool(description="查询旅游套餐：按出发地、可选价格上限与目的地关键词在 Neo4j 图谱中检索。")
def search_travel_deals(
    departure: str,
    max_price: Optional[int] = None,
    keywords: Optional[str] = None,
) -> str:
    try:
        results = query_search_travel_deals(departure, max_price=max_price, keywords=keywords)
    except Exception as exc:
        logger.exception("search_travel_deals failed")
        return f"[错误] 套餐检索失败：{exc}"
    if not results:
        return f"[错误] {departure} 出发暂无合适旅游套餐"
    lines = [f"**{departure} 出发旅游推荐**\n"]
    for idx, row in enumerate(results[:10], 1):
        itinerary = (row.get("itinerary") or "")[:60]
        price = row.get("price")
        offer = row.get("offer") or "无优惠"
        lines.append(f"{idx}. **{itinerary}**\n   价格: ¥{price} | 优惠: {offer}\n")
    return "\n".join(lines)


@tool(description="出发地 + 目的地关键词 + 价格上限，在 Neo4j 中取性价比优先的若干条。")
def find_best_offers(departure: str, destination_keywords: str, max_price: int = 200_000) -> str:
    try:
        results = query_find_best_offers(departure, destination_keywords, max_price=max_price)
    except Exception as exc:
        logger.exception("find_best_offers failed")
        return f"[错误] 套餐检索失败：{exc}"
    if not results:
        return f"[错误] {departure} -> {destination_keywords} 未检索到符合条件的套餐。"
    lines = [f"**{departure} -> {destination_keywords} 性价比推荐**\n"]
    for idx, row in enumerate(results[:5], 1):
        itinerary = (row.get("itinerary") or "")[:70]
        price = row.get("price")
        offer = row.get("offer") or "无"
        score = float(row.get("score") or 0)
        lines.append(f"{idx}. **{itinerary}**\n   价格: ¥{price} | 优惠: {offer} | 评分: {score:.0f}\n")
    return "\n".join(lines)


@tool(description="按出发地与价格区间查询 Neo4j 套餐。")
def get_travel_by_price_range(departure: str, min_price: int, max_price: int) -> str:
    try:
        results = query_travel_by_price_range(departure, min_price, max_price)
    except Exception as exc:
        logger.exception("get_travel_by_price_range failed")
        return f"[错误] 套餐检索失败：{exc}"
    if not results:
        return f"[错误] {departure} 在 {min_price}-{max_price} 元区间内无套餐"
    lines = [f"**{departure} ¥{min_price}-{max_price} 套餐**\n"]
    for row in results[:10]:
        itinerary = (row.get("itinerary") or "")[:60]
        price = row.get("price")
        offer = row.get("offer") or ""
        lines.append(f"- {itinerary} ... ¥{price} {offer}")
    return "\n".join(lines)


@tool(description="检索 Chroma 集合 travel_deals。若多个上传文件同时命中，优先展示最近上传文件中的结果。")
def vector_store_retriever(query: str) -> str:
    try:
        results = chroma_similarity_search(
            Config.collection_name,
            query,
            k=max(6, int(Config.similarity_threshold) * 3),
            repair_on_corrupt=True,
        )
        results = sorted(results, key=_uploaded_at_sort_key, reverse=True)[
            : max(1, int(Config.similarity_threshold))
        ]
        formatted: list[str] = []
        for doc in results:
            content = doc.page_content if hasattr(doc, "page_content") else str(doc)
            meta = getattr(doc, "metadata", {}) or {}
            source = meta.get("source_file") or meta.get("source") or "unknown"
            uploaded_at = meta.get("uploaded_at", "unknown")
            formatted.append(f"来源: {source}\nuploaded_at: {uploaded_at}\n内容: {content}\n")
        return "\n".join(formatted) if formatted else "未找到相关信息"
    except Exception as exc:
        return f"检索过程中发生错误: {exc}"
