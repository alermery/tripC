from __future__ import annotations

from datetime import datetime

from langchain_core.tools import tool

from backend.app.rag.chroma_rag_kb import search_rag_kb

_DEFAULT_TOP_K = 16
_MAX_TOP_K = 40

_RAG_KB_RETRIEVER_DESCRIPTION = (
    "检索管理员通过 RAG 页面上传的内部知识库（Chroma 集合 rag_kb）。\n\n"
    "适用于自由行攻略、路书、游记、目的地日程、景点说明、航班/铁路站内资料等场景。\n"
    "如果多个上传文件同时命中，优先返回最近一次上传文件中的片段；"
    "只有最新文件信息不足时，再补充更早上传的片段。"
)


def _uploaded_at_sort_key(doc) -> tuple[int, datetime]:
    """把文档按上传时间转换成可排序的键。"""
    meta = getattr(doc, "metadata", {}) or {}
    raw = str(meta.get("uploaded_at") or "").strip()
    if not raw:
        return (1, datetime.min)
    try:
        return (0, datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None))
    except Exception:
        return (1, datetime.min)


@tool(description=_RAG_KB_RETRIEVER_DESCRIPTION)
def rag_kb_retriever(query: str, top_k: int = _DEFAULT_TOP_K) -> str:
    """检索管理员上传的 RAG 知识库并按时间优先返回片段。"""
    k = max(1, min(int(top_k), _MAX_TOP_K))
    docs = search_rag_kb(query, k=max(k * 3, k))
    docs = sorted(docs, key=_uploaded_at_sort_key, reverse=True)[:k]
    if not docs:
        return "rag_kb 中未检索到相关片段（可能尚未上传或 embedding 服务不可用）。"

    lines: list[str] = ["【RAG 知识库片段】"]
    for i, doc in enumerate(docs, 1):
        meta = getattr(doc, "metadata", {}) or {}
        src = meta.get("source_file", "unknown")
        uploaded_at = meta.get("uploaded_at", "unknown")
        lines.append(
            f"--- 片段{i}（来源文件: {src}；uploaded_at: {uploaded_at}）---\n"
            f"{doc.page_content}\n"
        )
    return "\n".join(lines)
