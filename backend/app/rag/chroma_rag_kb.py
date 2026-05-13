from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from langchain_core.documents import Document
from backend.app.services.chroma_client import chroma_add_documents, chroma_similarity_search

RAG_KB_COLLECTION = "rag_kb"

# 将纯文本块写入独立集合 rag_kb，供 rag_kb_retriever 使用。
def add_rag_text_chunks(chunks: list[str], *, source_file: str, extra_meta: dict | None = None,) -> int:
    if not chunks:
        return 0
    docs: list[Document] = []
    ids: list[str] = []
    base = (extra_meta or {}).copy()
    base.setdefault("uploaded_at", datetime.now(timezone.utc).isoformat())
    for i, text in enumerate(chunks):
        t = (text or "").strip()
        if not t:
            continue
        chunk_id = hashlib.sha256(f"{source_file}:{i}:{t[:200]}".encode("utf-8")).hexdigest()[:48]
        docs.append(
            Document(
                page_content=t[:8000],
                metadata={**base, "source_file": source_file, "chunk_index": i},
            )
        )
        ids.append(chunk_id)
    if not docs:
        return 0
    try:
        chroma_add_documents(RAG_KB_COLLECTION, docs, ids)
    except Exception:
        return -1
    return len(docs)

def search_rag_kb(query: str, k: int = 5) -> list[Document]:
    try:
        return chroma_similarity_search(RAG_KB_COLLECTION, query, k=k, repair_on_corrupt=True)
    except Exception:
        return []
